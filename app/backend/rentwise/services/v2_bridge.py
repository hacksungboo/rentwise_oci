"""B 저장 구조 ↔ A v2 core(solve/validate) 연결 (real 모드의 회수 지연 경로).

A 의 RealEngine(v1 호환)은 B v1 저장 범위(직원 변경·AS 창 안 시각)만 자동 후보로 낸다.
회수 지연은 반납 → 정비 → 다음 납품(같은 모델 대체)까지 작업 창·예약·대여·의존을 함께 바꾸므로
A 의 v2 core 를 직접 호출하고, B 가 그 완전 후보(candidate plan)를 그대로 저장한다.

- 엔진 코드는 바꾸지 않는다. 형식 변환·ID 발급·저장만 B 가 맡는다.
- v2 가 다루지 않는 B 값(예: 대여 없이 잡힌 납품 예약)은 변환 중 임시 대여로 감싸고 저장 때 되돌린다.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from rentwise.contracts import types as c

SYNTH_RENTAL = "R-HOLD-"            # rental_id 가 없는 예약을 v2 에 넘길 때 쓰는 임시 대여 ID 접두사
REASON_TO_V2 = {"ASSET_REUSE": "READY_DELIVERY"}   # B 의존 사유 → v2 가 자산 연결로 인식하는 사유
PRIORITY_TO_V2 = {"HIGH": "URGENT", "URGENT": "URGENT"}


class BridgeUnsupported(Exception):
    """v2 경로로 처리할 수 없는 요청 → 호출자가 기존 경로(A v1)로 넘긴다."""


def supports(ops: list[dict]) -> bool:
    """v2 core 가 처리하는 요청: 기존 회수(PICKUP) 일정 변경."""
    return bool(ops) and all(o.get("operation") == "RESCHEDULE" and o.get("kind") == "PICKUP" for o in ops)


# --------------------------------------------------------------------------- 변환
def _windows(ws: list[dict]) -> list[dict]:
    return [{"start": w.get("start", w.get("start_at")), "end": w.get("end", w.get("end_at"))} for w in ws]


def to_v2_snapshot(snap: dict, *, state_revision: int, as_of: str, dataset_version: str,
                   travel_version: str, policy_version: str, horizon_start: str, horizon_end: str) -> dict:
    s = deepcopy(snap)
    jobs_by_id = {j["id"]: j for j in s["jobs"]}
    plans_by_job = {p["job_id"]: p for p in s["plan_items"]}
    customers_by_loc = {cu["location_id"]: cu for cu in s["customers"]}

    for cu in s["customers"]:
        cu["visit_windows"] = _windows(cu["visit_windows"])
    for sh in s["shifts"]:
        sh["break_windows"] = _windows(sh["break_windows"])
    for it in s["items"]:
        m = it["service_minutes_by_kind"]
        it["model"] = it.pop("model_name", None) or it.get("model") or it["id"]
        it.setdefault("transfer_service_minutes", {"pickup": m["TRANSFER"], "delivery": m["TRANSFER"]})
    for j in s["jobs"]:
        j["priority"] = PRIORITY_TO_V2.get(j.get("priority"), "NORMAL")
        if j["kind"] == "TRANSFER":
            # B v1 은 도착지 창을 따로 저장하지 않는다 → 확정된 계획의 두 번째 방문부터 기한까지
            svc = [x for x in (plans_by_job.get(j["id"]) or {}).get("segments", []) if x["kind"] == "SERVICE"]
            j.setdefault("destination_window_start", svc[1]["start_at"] if len(svc) > 1 else j["window_start"])
            j.setdefault("destination_window_end", j["due_at"])
            j.setdefault("direct_transfer_confirmed", True)
        else:
            j.setdefault("destination_window_start", None)
            j.setdefault("destination_window_end", None)
            j.setdefault("direct_transfer_confirmed", False)
    for p in s["plan_items"]:
        p["segments_json"] = p.pop("segments")
        p.setdefault("reason_codes", [])
    pairs = {(t["from_id"], t["to_id"]) for t in s["travel_times"]}
    ref = s["travel_times"][0] if s["travel_times"] else {"source": "SYNTHETIC_FIXED", "version": travel_version}
    for loc in s["locations"]:
        if (loc["id"], loc["id"]) not in pairs:
            s["travel_times"].append({"from_id": loc["id"], "to_id": loc["id"], "minutes": 0,
                                      "source": ref["source"], "version": ref["version"]})
    for d in s["dependencies"]:
        d["reason"] = REASON_TO_V2.get(d["reason"], d["reason"])

    # 대여 없는 예약(신규 납품 예약)을 임시 PLANNED 대여로 감싼다
    for r in s["reservations"]:
        if r["rental_id"] is not None:
            continue
        delivery = next((j for j in s["jobs"] if j["kind"] == "DELIVERY" and r["asset_id"] in j["asset_ids"]
                         and j["id"] in plans_by_job and plans_by_job[j["id"]]["start_at"] == r["start_at"]), None)
        cust = customers_by_loc.get(delivery["to_id"]) if delivery else None
        if cust is None:
            raise BridgeUnsupported(f"RESERVATION_WITHOUT_DELIVERY:{r['id']}")
        rid = SYNTH_RENTAL + r["id"]
        s["rentals"].append({"id": rid, "asset_id": r["asset_id"], "customer_id": cust["id"], "actual_start": None,
                             "actual_end": None, "expected_return_at": None, "status": "PLANNED"})
        r["rental_id"] = rid
    del jobs_by_id

    s.update(schema_version="rental.snapshot.v2", bundle_version="rental.bundle.v2",
             state_revision=state_revision, as_of=as_of, dataset_version=dataset_version,
             travel_version=travel_version, policy_version=policy_version,
             horizon_start=horizon_start, horizon_end=horizon_end)
    return s


def build_input(v2snap: dict, ops: list[dict], *, request_id: str, request_revision: int,
                interpretation_revision: int, plan_id: str, base_plan_id: str | None,
                overrides: list[dict]) -> dict:
    from rentwise.contracts.v2.normalize import normalize_operation
    from rentwise.contracts.v2.schema import ContractError
    from rentwise.contracts.v2.serialization import solver_input_hash

    customers = {cu["id"]: cu for cu in v2snap["customers"]}
    jobs = {j["id"]: j for j in v2snap["jobs"]}
    normalized = []
    for o in ops:
        job = jobs.get(o.get("target_job_id") or "")
        if job is None or job["kind"] != "PICKUP":
            raise BridgeUnsupported("TARGET_NOT_PICKUP")
        rental = next((r for r in v2snap["rentals"] if r["status"] == "ACTIVE" and r["asset_id"] in job["asset_ids"]
                       and customers[r["customer_id"]]["location_id"] == job["from_id"]), None)
        if rental is None:
            raise BridgeUnsupported("PICKUP_RENTAL_NOT_FOUND")
        try:
            normalized.append(normalize_operation(
                v2snap, "RESCHEDULE", job["id"],
                {"window_start": o["window_start"], "window_end": o["window_end"], "due_at": o["due_at"]},
                confirmed=True, rental_id=rental["id"], return_policy="NOT_APPLICABLE"))
        except ContractError as exc:
            raise BridgeUnsupported("NORMALIZE:" + ",".join(exc.paths)) from None

    all_jobs = {j["id"]: j for j in v2snap["jobs"]}
    rentals = sorted({r["rental_id"] for r in v2snap["reservations"] if r["status"] == "ACTIVE"})
    body = dict(
        schema_version="rental.solver.v2", bundle_version="rental.bundle.v2",
        request_id=request_id, request_revision=request_revision, interpretation_revision=interpretation_revision,
        plan_id=plan_id, base_plan_id=base_plan_id, base_state_revision=v2snap["state_revision"],
        **{k: v2snap[k] for k in ("horizon_start", "horizon_end", "dataset_version", "travel_version", "policy_version")},
        operations=normalized, approved_job_ids=[op["job"]["id"] for op in normalized], snapshot=v2snap,
        overrides=[{k: v for k, v in o.items() if k in ("job_id", "employee_id", "asset_ids", "start_at")} for o in overrides],
        id_allocations=dict(
            plan_items=[{"job_id": jid, "id": f"PI-{plan_id}-{jid}"} for jid in sorted(all_jobs)],
            reservations=[{"rental_id": rid, "id": f"RS-{plan_id}-{rid.removeprefix(SYNTH_RENTAL)}"} for rid in rentals],
            dependencies=[{"job_id": jid, "id": f"DP-{plan_id}-{jid}"} for jid in sorted(all_jobs)
                          if all_jobs[jid]["kind"] == "DELIVERY"]),
        max_search_ms=2000, max_candidates=1000)
    body["input_hash"] = solver_input_hash(body)
    return body


# --------------------------------------------------------------------------- 결과 → B
def _v1_item(p: dict) -> c.PlanItem:
    return c.PlanItem(id=p["id"], plan_id=p["plan_id"], job_id=p["job_id"], employee_id=p["employee_id"],
                      asset_ids=p["asset_ids"], start_at=p["start_at"], end_at=p["end_at"],
                      segments=[c.Segment(**s) for s in p["segments_json"]], reason_codes=p["reason_codes"])


def _b_reservation(r: dict) -> dict:
    r = deepcopy(r)
    if r["rental_id"] and r["rental_id"].startswith(SYNTH_RENTAL):
        r["rental_id"] = None
    return r


def reservation_changes(v2snap: dict, candidate: dict) -> list[c.ReservationChange]:
    """바뀐 예약만 REPLACE/CREATE 로 (v2 는 전부 새 ID 로 내므로 내용이 같은 건 걸러낸다)."""
    keys = ("asset_id", "start_at", "end_at", "release_job_id")
    old = {r["rental_id"]: r for r in v2snap["reservations"] if r["status"] == "ACTIVE"}
    out = []
    for r in candidate["reservations"]:
        prev = old.get(r["rental_id"])
        if prev is not None and all(prev[k] == r[k] for k in keys):
            continue
        out.append(c.ReservationChange(action="REPLACE" if prev else "CREATE",
                                       old_id=prev["id"] if prev else None, reservation=_b_reservation(r)))
    return out


def to_v1_result(v2snap: dict, res: dict) -> tuple[c.SolverResult, dict | None]:
    cand = res.get("candidate_plan")
    viol = [c.Violation(**{k: v for k, v in x.items() if k in c.Violation.model_fields}) for x in res["violations"]]
    out = c.SolverResult(
        status=res["status"],
        candidate_items=[_v1_item(p) for p in cand["plan_items"]] if cand else [],
        reservation_changes=reservation_changes(v2snap, cand) if cand else [],
        affected_job_ids=res["affected_job_ids"],
        impact_edges=[c.ImpactEdge(**e) for e in res["impact_edges"]],
        violations=viol,
        unresolved=[c.Unresolved(job_id=u.get("job_id"), code=u["code"], details=u.get("details") or {})
                    for u in res["unresolved"]],
        objective=res["objective"], search_stats=c.SearchStats(**res["search_stats"]),
        input_hash=res["input_hash"], solver_version=res["solver_version"])
    return out, cand


def solve(v2input: dict) -> dict:
    from rentwise.engine import solve as v2_solve
    return v2_solve(v2input)


def validate(v2snap: dict, candidate: dict) -> c.ValidationResult:
    from rentwise.engine import validate as v2_validate
    r = v2_validate(v2snap, candidate)
    return c.ValidationResult(
        status=r["status"], missing_fields=r["missing_fields"],
        violations=[c.Violation(**{k: v for k, v in x.items() if k in c.Violation.model_fields}) for x in r["violations"]])


def restore_reason(old_deps: dict[str, dict], d: dict) -> str:
    """기존 의존은 원래 B 사유로, 새 의존은 v2 사유 그대로."""
    return old_deps[d["id"]]["reason"] if d["id"] in old_deps else d["reason"]


def changed_jobs(v2snap: dict, candidate: dict) -> list[dict[str, Any]]:
    old = {j["id"]: j for j in v2snap["jobs"]}
    keys = ("window_start", "window_end", "due_at", "asset_ids")
    return [j for j in candidate["jobs"] if j["id"] in old and any(old[j["id"]][k] != j[k] for k in keys)]
