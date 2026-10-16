"""계획 생성·비교·확정 (F03 연결, F04).

- 초안(plan) 저장은 운영 Job/Reservation/Rental/Asset 을 바꾸지 않는다.
- 확정은 workspace 행 잠금 → revision 재검사 → 최신 snapshot validate → 예약/작업/현행 계획 교체 → revision+1 → commit.
- DB 잠금 안에서 LLM·탐색을 실행하지 않는다 (validate 만).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection

from rentwise.api.errors import ApiError
from rentwise.config import settings
from rentwise.contracts.types import NormalizedOperation, PlanItem, SolverInput, SolverResult
from rentwise.db import tables as T
from rentwise.db.database import J, _plan_item_row, plan_item_from_row, read_snapshot, row_to_dict
from rentwise.engine_registry import get_engine
from rentwise.services.requests import _req, latest_interpretation
from rentwise.timeutil import iso, now, parse, to_db

HORIZON_DAYS = 7


def canonical_hash(obj: Any) -> str:
    body = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


def _ws(conn: Connection, lock: bool = False):
    q = select(T.workspace_state).where(T.workspace_state.c.id == "DEMO")
    if lock and conn.dialect.name != "sqlite":
        q = q.with_for_update()
    return conn.execute(q).one()


def _normalize(conn: Connection, intent: dict, snapshot: dict) -> tuple[list[NormalizedOperation], list[str]]:
    """사람이 확인한 해석 → 배정 입력. RESCHEDULE 는 기존 작업 조건을 명시적으로 상속하고 상속 목록을 남긴다."""
    jobs = {j["id"]: j for j in snapshot["jobs"]}
    ops, inherited = [], []
    for i, op in enumerate(intent["operations"]):
        d = dict(op)
        if op["operation"] == "RESCHEDULE":
            base = jobs.get(op.get("target_job_id") or "")
            if base is None:
                raise ApiError(422, "TARGET_JOB_REQUIRED", "변경할 기존 작업을 지정해 주세요.",
                               {"path": f"operations.{i}.target_job_id"})
            for f in ("item_id", "from_id", "to_id", "due_at"):
                if d.get(f) in (None, []) and base.get(f) is not None:
                    d[f] = base[f]
                    inherited.append(f"operations.{i}.{f}")
            if not d.get("asset_ids"):
                d["asset_ids"] = base["asset_ids"]
                inherited.append(f"operations.{i}.asset_ids")
        if d.get("window_start") and d.get("window_end") and parse(d["window_end"]) <= parse(d["window_start"]):
            raise ApiError(422, "INVALID_WINDOW", "방문 종료 시각은 시작 시각보다 늦어야 합니다.",
                           {"path": f"operations.{i}.window_end"})
        if d.get("due_at") and d.get("window_end") and parse(d["due_at"]) < parse(d["window_end"]):
            raise ApiError(422, "DUE_BEFORE_WINDOW", "완료 기한이 방문 종료보다 이릅니다. 기한을 다시 확인해 주세요.",
                           {"path": f"operations.{i}.due_at", "due_at": d["due_at"], "window_end": d["window_end"]})
        d.pop("evidence", None)
        ops.append(NormalizedOperation(**d))
    return ops, inherited


def create_plan(conn: Connection, request_id: str, interpretation_revision: int, base_state_revision: int,
                overrides: list[dict], actor: str) -> dict:
    req = _req(conn, request_id)
    interp = latest_interpretation(conn, request_id)
    if interp is None or interp["revision"] != interpretation_revision:
        raise ApiError(409, "STALE_INTERPRETATION", "최신 해석 버전이 아닙니다. 다시 불러와 주세요.",
                       {"expected": interpretation_revision, "actual": interp["revision"] if interp else None},
                       retryable=True)
    pending = [c["path"] for c in interp["payload"]["needs_confirmation"] if c["path"] not in interp["acknowledged_paths"]]
    if interp["origin"] != "HUMAN" or pending:
        raise ApiError(422, "UNCONFIRMED_FIELDS", "확인이 필요한 항목이 남아 있습니다.", {"paths": pending})
    ws = _ws(conn)
    if ws.state_revision != base_state_revision:
        raise ApiError(409, "STALE_SNAPSHOT", "운영 상태가 바뀌었습니다. 새로고침 후 다시 계산하세요.",
                       {"expected": base_state_revision, "actual": ws.state_revision}, retryable=True)
    snapshot = read_snapshot(conn)
    ops, inherited = _normalize(conn, interp["payload"], snapshot)
    anchor = parse(json.loads(settings.seed_path.read_text(encoding="utf-8"))["manifest"]["clock_anchor"]) \
        if settings.seed_path.exists() else now()
    h0 = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    body = {
        "request_id": request_id, "interpretation_revision": interpretation_revision,
        "base_plan_id": ws.current_plan_id, "base_state_revision": ws.state_revision,
        "horizon_start": iso(h0), "horizon_end": iso(h0 + timedelta(days=HORIZON_DAYS)),
        "dataset_version": ws.dataset_version, "travel_version": "travel-v1", "policy_version": "policy-v1",
        "operations": [o.model_dump() for o in ops], "snapshot": snapshot, "overrides": overrides,
        "max_search_ms": 2000, "max_candidates": 1000,
    }
    input_hash = canonical_hash(body)
    solver_input = SolverInput(**body, input_hash=input_hash)
    engine = get_engine()
    result: SolverResult = engine.solve(solver_input)

    n = conn.execute(select(func.count()).select_from(T.plans)).scalar_one() + 1
    pid = f"PL-D{n:02d}-{uuid.uuid4().hex[:4]}"
    status = "READY" if result.status == "FEASIBLE" else "UNRESOLVED"
    meta = result.model_dump(exclude={"candidate_items"})
    meta["inherited_paths"] = inherited
    conn.execute(insert(T.plans).values(
        id=pid, revision=1, base_plan_id=ws.current_plan_id, base_state_revision=ws.state_revision,
        request_id=request_id, interpretation_revision=interpretation_revision, status=status,
        solver_status=result.status, solver_version=result.solver_version, engine_mode=engine.mode,
        policy_version="policy-v1", travel_version="travel-v1", input_hash=input_hash,
        result_json=json.dumps(meta, ensure_ascii=False, default=str),
        operations_json=J([o.model_dump() for o in ops]), created_at=now()))
    rows = []
    for p in result.candidate_items:
        d = p.model_dump()
        d["id"], d["plan_id"] = f"PI-{pid}-{p.job_id}", pid
        rows.append(_plan_item_row(d))
    if rows:
        conn.execute(insert(T.plan_items), rows)
    conn.execute(update(T.requests).where(T.requests.c.id == req.id).values(status="DRAFTED"))
    return plan_view(conn, pid)


# --------------------------------------------------------------------------- 조회·비교
def _plan(conn: Connection, plan_id: str):
    p = conn.execute(select(T.plans).where(T.plans.c.id == plan_id)).first()
    if p is None:
        raise ApiError(404, "NOT_FOUND", "계획을 찾을 수 없습니다.", {"plan_id": plan_id})
    return p


def _items(conn: Connection, plan_id: str) -> dict[str, dict]:
    rows = conn.execute(select(T.plan_items).where(T.plan_items.c.plan_id == plan_id)).all()
    return {r.job_id: plan_item_from_row(r) for r in rows}


def _service_start(item: dict | None) -> str | None:
    if not item:
        return None
    for s in item["segments"]:
        if s["kind"] in ("SERVICE", "PREP"):
            return s["start_at"]
    return item["start_at"]


def plan_view(conn: Connection, plan_id: str) -> dict:
    p = _plan(conn, plan_id)
    ws = _ws(conn)
    pd = row_to_dict(T.plans, p)
    meta = json.loads(pd.pop("result_json") or "{}")
    pd["operations"] = json.loads(pd.pop("operations_json") or "[]")
    if pd["status"] == "READY" and p.base_state_revision != ws.state_revision:
        pd["status"] = "STALE"
    after = _items(conn, plan_id)
    before = _items(conn, p.base_plan_id) if p.base_plan_id else {}
    names = {
        "employee": {r.id: r.name for r in conn.execute(select(T.employees.c.id, T.employees.c.name))},
        "location": {r.id: r.name for r in conn.execute(select(T.locations.c.id, T.locations.c.name))},
    }
    jobs = {r.id: row_to_dict(T.jobs, r) for r in conn.execute(select(T.jobs))}
    affected = set(meta.get("affected_job_ids", []))
    rows = []
    for job_id in sorted(set(before) | set(after), key=lambda j: (after.get(j) or before.get(j))["start_at"]):
        b, a = before.get(job_id), after.get(job_id)
        changed = (b is None) or (a is None) or any(
            b[k] != a[k] for k in ("employee_id", "asset_ids")) or parse(b["start_at"]) != parse(a["start_at"]) \
            or parse(b["end_at"]) != parse(a["end_at"])
        if not changed and job_id not in affected:
            continue
        job = jobs.get(job_id, {})
        site = job.get("from_id") if job.get("kind") in ("PICKUP", "AS", "TRANSFER") else job.get("to_id")
        side = lambda x: None if x is None else {  # noqa: E731
            "employee_id": x["employee_id"], "employee_name": names["employee"].get(x["employee_id"]),
            "asset_ids": x["asset_ids"], "start_at": x["start_at"], "end_at": x["end_at"],
            "service_start_at": _service_start(x), "segments": x["segments"]}
        rows.append({"job_id": job_id, "kind": job.get("kind"), "site_id": site,
                     "site_name": names["location"].get(site), "changed": changed,
                     "before": side(b), "after": side(a), "reason_codes": (a or {}).get("reason_codes", [])})
    pd.update({
        "result": {k: meta.get(k) for k in ("reservation_changes", "affected_job_ids", "impact_edges", "violations",
                                            "unresolved", "objective", "search_stats", "inherited_paths")},
        "diff": rows,
        "current_state_revision": ws.state_revision,
        "is_mock": pd.get("engine_mode") == "mock",
    })
    return pd


# --------------------------------------------------------------------------- 확정·보류
def confirm(conn: Connection, plan_id: str, expected_plan_revision: int, base_state_revision: int,
            actor: str, trace_id: str) -> dict:
    ws = _ws(conn, lock=True)  # 모든 운영 쓰기 직렬화
    p = _plan(conn, plan_id)
    if p.status == "CONFIRMED":
        raise ApiError(409, "ALREADY_APPLIED", "이미 확정된 계획입니다.", {"plan_id": plan_id})
    if p.revision != expected_plan_revision:
        raise ApiError(409, "STALE_PLAN", "계획이 수정되었습니다. 다시 불러와 주세요.",
                       {"expected": expected_plan_revision, "actual": p.revision}, retryable=True)
    if p.base_state_revision != ws.state_revision or base_state_revision != ws.state_revision:
        raise ApiError(409, "STALE_PLAN", "기준 상태가 바뀌었습니다. 재조회 후 재계산하세요.",
                       {"expected": base_state_revision, "actual": ws.state_revision}, retryable=True)
    if p.status != "READY":
        raise ApiError(422, "PLAN_NOT_READY", "실행 가능한 계획만 확정할 수 있습니다.", {"status": p.status})
    dup = conn.execute(select(T.plans.c.id).where(
        (T.plans.c.request_id == p.request_id) & (T.plans.c.interpretation_revision == p.interpretation_revision)
        & (T.plans.c.status == "CONFIRMED"))).first()
    if dup:
        raise ApiError(409, "ALREADY_APPLIED", "같은 요청이 이미 확정되었습니다.", {"plan_id": dup.id})

    # 잠금 안에서 최신 snapshot 으로 최종 검사 (탐색·LLM 없음)
    snapshot = read_snapshot(conn)
    cand = list(_items(conn, plan_id).values())
    vr = get_engine().validate(snapshot, [PlanItem(**{k: v for k, v in c.items() if k in PlanItem.model_fields})
                                          for c in cand])
    if vr.status != "VALID":
        raise ApiError(422, "CONSTRAINT_VIOLATION", "제약 위반이 있어 확정할 수 없습니다.",
                       {"violations": [v.model_dump() for v in vr.violations], "missing_fields": vr.missing_fields})

    meta = json.loads(p.result_json or "{}")
    ts = now()
    # 1) 예약 교체
    for ch in meta.get("reservation_changes", []):
        if ch["action"] in ("REPLACE", "CANCEL") and ch["old_id"]:
            conn.execute(update(T.reservations).where(T.reservations.c.id == ch["old_id"])
                         .values(status="SUPERSEDED" if ch["action"] == "REPLACE" else "CANCELLED"))
        if ch["action"] in ("REPLACE", "CREATE") and ch["reservation"]:
            r = ch["reservation"]
            conn.execute(insert(T.reservations).values(
                id=r["id"], asset_id=r["asset_id"], rental_id=r.get("rental_id"), start_at=to_db(r["start_at"]),
                end_at=to_db(r.get("end_at")), release_job_id=r.get("release_job_id"), plan_id=plan_id,
                status="ACTIVE", review_required=False))
    # 2) 작업 갱신 (예정값만. 실제 상태는 현장 event 로만 변경)
    before = _items(conn, p.base_plan_id) if p.base_plan_id else {}
    ops = {o.get("target_job_id"): o for o in json.loads(p.operations_json or "[]") if o.get("target_job_id")}
    for c in cand:
        b = before.get(c["job_id"])
        if b and b["asset_ids"] == c["asset_ids"] and parse(b["start_at"]) == parse(c["start_at"]) \
                and b["employee_id"] == c["employee_id"] and c["job_id"] not in ops:
            continue
        vals: dict[str, Any] = {"asset_ids_json": J(c["asset_ids"]), "revision": T.jobs.c.revision + 1}
        op = ops.get(c["job_id"])
        if op:
            vals.update(window_start=to_db(op.get("window_start")), window_end=to_db(op.get("window_end")),
                        due_at=to_db(op.get("due_at")))
        elif any(s["kind"] == "PREP" for s in c["segments"]):
            vals.update(window_start=to_db(c["start_at"]), window_end=to_db(c["end_at"]), due_at=to_db(c["end_at"]))
        conn.execute(update(T.jobs).where(T.jobs.c.id == c["job_id"]).values(**vals))
        if b and b["asset_ids"] != c["asset_ids"]:  # 대체 개체 → 기존 개체 재사용 의존 해제
            conn.execute(delete(T.dependencies).where((T.dependencies.c.successor_job_id == c["job_id"])
                                                      & (T.dependencies.c.reason == "ASSET_REUSE")))
    # 3) 현행 계획 교체·revision 증가
    if p.base_plan_id:
        conn.execute(update(T.plans).where(T.plans.c.id == p.base_plan_id).values(status="SUPERSEDED"))
    conn.execute(update(T.plans).where(T.plans.c.id == plan_id)
                 .values(status="CONFIRMED", confirmed_by=actor, confirmed_at=ts))
    new_rev = ws.state_revision + 1
    conn.execute(update(T.workspace_state).where(T.workspace_state.c.id == ws.id)
                 .values(state_revision=new_rev, current_plan_id=plan_id))
    if p.request_id:
        conn.execute(update(T.requests).where(T.requests.c.id == p.request_id).values(status="CONFIRMED"))
    conn.execute(insert(T.audit_log).values(
        id=uuid.uuid4().hex[:20], actor=actor, action="PLAN_CONFIRM", entity_id=plan_id,
        old_revision=ws.state_revision, new_revision=new_rev, occurred_at=ts, trace_id=trace_id))
    return {"confirmed_plan_id": plan_id, "new_state_revision": new_rev, "confirmed_at": iso(ts)}


def hold(conn: Connection, plan_id: str, expected_plan_revision: int, reason: str, actor: str) -> dict:
    _ws(conn, lock=True)
    p = _plan(conn, plan_id)
    if p.status in ("CONFIRMED", "SUPERSEDED"):
        raise ApiError(409, "PLAN_CLOSED", "이미 확정된 계획은 보류할 수 없습니다.")
    if p.revision != expected_plan_revision:
        raise ApiError(409, "STALE_PLAN", "계획이 수정되었습니다. 다시 불러와 주세요.", retryable=True)
    conn.execute(update(T.plans).where(T.plans.c.id == plan_id).values(status="HELD"))
    if p.request_id:
        conn.execute(update(T.requests).where(T.requests.c.id == p.request_id).values(status="HELD"))
    conn.execute(insert(T.audit_log).values(id=uuid.uuid4().hex[:20], actor=actor, action=f"PLAN_HOLD:{reason[:40]}",
                                            entity_id=plan_id, occurred_at=now()))
    return {"plan_id": plan_id, "status": "HELD"}
