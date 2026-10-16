"""요청·해석 서비스 (F02). 해석 결과는 revision 으로만 쌓이고 원문을 바꾸면 이전 해석은 무효."""
from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from rentwise.api.errors import ApiError
from rentwise.contracts.types import CandidateRef, InterpretationInput, Intent
from rentwise.db import tables as T
from rentwise.db.database import J, row_to_dict
from rentwise.engine_registry import get_engine
from rentwise.timeutil import now, to_db


def _req(conn: Connection, request_id: str):
    r = conn.execute(select(T.requests).where(T.requests.c.id == request_id)).first()
    if r is None:
        raise ApiError(404, "NOT_FOUND", "요청을 찾을 수 없습니다.", {"request_id": request_id})
    return r


def create_request(conn: Connection, source_customer_id: str | None, received_at: str, text: str,
                   external_key: str | None, actor: str) -> dict:
    if not text.strip():
        raise ApiError(422, "EMPTY_TEXT", "요청 원문을 입력해 주세요.")
    if len(text) > 2000:
        raise ApiError(422, "TEXT_TOO_LONG", "요청 원문은 2000자 이하여야 합니다.")
    if source_customer_id and conn.execute(
            select(T.customers.c.id).where(T.customers.c.id == source_customer_id)).first() is None:
        raise ApiError(422, "UNKNOWN_CUSTOMER", "등록되지 않은 거래처입니다.", {"customer_id": source_customer_id})
    n = conn.execute(select(func.count()).select_from(T.requests)).scalar_one() + 1
    rid = f"REQ-{n:02d}-{uuid.uuid4().hex[:4]}"
    conn.execute(insert(T.requests).values(
        id=rid, external_key=external_key, source_customer_id=source_customer_id, received_at=to_db(received_at),
        request_text=text, status="RECEIVED", revision=1, created_by=actor))
    return request_view(conn, rid)


def latest_interpretation(conn: Connection, request_id: str) -> dict | None:
    r = conn.execute(select(T.interpretations).where(T.interpretations.c.request_id == request_id)
                     .order_by(T.interpretations.c.revision.desc())).first()
    if r is None:
        return None
    d = row_to_dict(T.interpretations, r)
    d["payload"] = json.loads(d.pop("payload_json"))
    d["call"] = json.loads(d.pop("call_json")) if d.get("call_json") else None
    d["acknowledged_paths"] = json.loads(d.pop("acknowledged_json")) if d.get("acknowledged_json") else []
    return d


def request_view(conn: Connection, request_id: str) -> dict:
    r = row_to_dict(T.requests, _req(conn, request_id))
    r["text"] = r.pop("request_text")
    r["interpretation"] = latest_interpretation(conn, request_id)
    plans = conn.execute(select(T.plans.c.id, T.plans.c.status, T.plans.c.created_at)
                         .where(T.plans.c.request_id == request_id).order_by(T.plans.c.created_at.desc())).all()
    r["plans"] = [{"id": p.id, "status": p.status} for p in plans]
    return r


def list_requests(conn: Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(select(T.requests).order_by(T.requests.c.received_at.desc(), T.requests.c.id.desc())
                        .limit(limit)).all()
    out = []
    for r in rows:
        d = row_to_dict(T.requests, r)
        d["text"] = d.pop("request_text")
        out.append(d)
    return out


def _existing_jobs_summary(conn: Connection, customer_id: str | None) -> list[dict[str, Any]]:
    if not customer_id:
        return []
    loc = conn.execute(select(T.customers.c.location_id).where(T.customers.c.id == customer_id)).scalar_one()
    rows = conn.execute(select(T.jobs).where(
        ((T.jobs.c.from_id == loc) | (T.jobs.c.to_id == loc)) & (T.jobs.c.kind != "PREP")
        & (T.jobs.c.status.in_(["UNASSIGNED", "ASSIGNED"]))).order_by(T.jobs.c.window_start).limit(15)).all()
    out = []
    for j in rows:
        d = row_to_dict(T.jobs, j)
        out.append({"id": d["id"], "kind": d["kind"], "customer_id": customer_id, "item_id": d["item_id"],
                    "asset_ids": json.loads(d["asset_ids_json"]), "window_start": d["window_start"],
                    "window_end": d["window_end"], "due_at": d["due_at"]})
    return out


def interpret(conn: Connection, request_id: str, expected_request_revision: int) -> dict:
    req = _req(conn, request_id)
    if req.revision != expected_request_revision:
        raise ApiError(409, "STALE_REQUEST", "요청이 변경되었습니다. 다시 불러와 주세요.",
                       {"expected": expected_request_revision, "actual": req.revision}, retryable=True)
    if req.status in ("CONFIRMED", "CANCELLED"):
        raise ApiError(409, "REQUEST_CLOSED", "이미 확정되었거나 취소된 요청입니다.")
    cust = [CandidateRef(id=c.id, name=c.name) for c in conn.execute(select(T.customers.c.id, T.customers.c.name))]
    items = [CandidateRef(id=i.id, name=i.model_name) for i in conn.execute(select(T.items.c.id, T.items.c.model_name))]
    inp = InterpretationInput(
        request_id=req.id, request_revision=req.revision,
        received_at=row_to_dict(T.requests, req)["received_at"], text=req.request_text,
        source_customer_id=req.source_customer_id, candidate_customers=cust, candidate_items=items,
        existing_jobs=_existing_jobs_summary(conn, req.source_customer_id))
    engine = get_engine()
    result = engine.interpret(inp)
    if result.status != "OK" or result.payload is None:
        err = result.error
        raise ApiError(502, (err.code if err else "AI_SCHEMA_INVALID"),
                       (err.message if err else "해석 결과를 사용할 수 없습니다. 조건을 직접 입력해 주세요."),
                       retryable=bool(err and err.retryable))
    _check_ids(conn, result.payload)
    rev = _next_interp_rev(conn, request_id)
    conn.execute(insert(T.interpretations).values(
        id=f"INT-{uuid.uuid4().hex[:10]}", request_id=request_id, revision=rev, origin=result.call.origin,
        model_id=result.call.model_id, schema_version=result.payload.schema_version,
        payload_json=result.payload.model_dump_json(), call_json=result.call.model_dump_json(),
        acknowledged_json=J([]), created_at=now()))
    conn.execute(update(T.requests).where(T.requests.c.id == request_id).values(status="NEEDS_REVIEW"))
    return request_view(conn, request_id)


def _next_interp_rev(conn, request_id) -> int:
    cur = conn.execute(select(func.max(T.interpretations.c.revision))
                       .where(T.interpretations.c.request_id == request_id)).scalar()
    return (cur or 0) + 1


def _check_ids(conn: Connection, intent: Intent) -> None:
    """모델/사람이 넣은 ID가 실제 존재하는지 검사 (유령 ID 금지)."""
    known = {
        "customer": {r.id for r in conn.execute(select(T.customers.c.id))},
        "item": {r.id for r in conn.execute(select(T.items.c.id))},
        "asset": {r.id for r in conn.execute(select(T.assets.c.id))},
        "job": {r.id for r in conn.execute(select(T.jobs.c.id))},
    }
    bad = []
    for i, op in enumerate(intent.operations):
        for field, kind in (("source_customer_id", "customer"), ("destination_customer_id", "customer"),
                            ("item_id", "item"), ("target_job_id", "job")):
            v = getattr(op, field)
            if v is not None and v not in known[kind]:
                bad.append(f"operations.{i}.{field}")
        for a in op.asset_ids:
            if a not in known["asset"]:
                bad.append(f"operations.{i}.asset_ids")
    if bad:
        raise ApiError(422, "UNKNOWN_REFERENCE", "존재하지 않는 ID가 포함되어 있습니다.", {"paths": bad})


def save_interpretation(conn: Connection, request_id: str, expected_request_revision: int,
                        payload: dict, acknowledged_paths: list[str], actor: str) -> dict:
    req = _req(conn, request_id)
    if req.revision != expected_request_revision:
        raise ApiError(409, "STALE_REQUEST", "요청이 변경되었습니다. 다시 불러와 주세요.", retryable=True)
    try:
        intent = Intent.model_validate(payload)
    except ValidationError as e:
        raise ApiError(422, "INVALID_INTERPRETATION", "조건 형식이 올바르지 않습니다.",
                       {"errors": [{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()][:20]})
    _check_ids(conn, intent)
    pending = [c.path for c in intent.needs_confirmation if c.path not in acknowledged_paths]
    rev = _next_interp_rev(conn, request_id)
    conn.execute(insert(T.interpretations).values(
        id=f"INT-{uuid.uuid4().hex[:10]}", request_id=request_id, revision=rev, origin="HUMAN", model_id=None,
        schema_version=intent.schema_version, payload_json=intent.model_dump_json(), call_json=None,
        acknowledged_json=J(acknowledged_paths), reviewed_by=actor, reviewed_at=now(), created_at=now()))
    conn.execute(update(T.requests).where(T.requests.c.id == request_id)
                 .values(status="READY" if not pending else "NEEDS_REVIEW"))
    view = request_view(conn, request_id)
    view["pending_confirmations"] = pending
    return view
