"""Persistent, operator-driven FIFO. AI calls run outside DB transactions.

One open queue per DEMO workspace, at most three requests. Completion is derived
from request status so the existing atomic confirmation also advances the queue.
No worker, automatic confirmation, polling model calls, or background retries.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import insert, select, update

from rentwise.api.errors import ApiError
from rentwise.db import tables as T
from rentwise.db.database import get_db_engine
from rentwise.services import requests as requests
from rentwise.timeutil import iso, now

TERMINAL = ("CONFIRMED", "HELD", "CANCELLED")
LEASE_SECONDS = 120  # Interpreter has a 45s total deadline; recovery after process loss.


def _queue(conn, queue_id):
    row = conn.execute(select(T.request_queues).where(T.request_queues.c.id == queue_id)).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "대기열을 찾을 수 없습니다.")
    return row


def _rows(conn, queue_id):
    return conn.execute(select(T.request_queue_items.c.request_id, T.request_queue_items.c.position,
                               T.request_queue_items.c.hold_reason, T.requests.c.status)
                        .join(T.requests, T.requests.c.id == T.request_queue_items.c.request_id)
                        .where(T.request_queue_items.c.queue_id == queue_id)
                        .order_by(T.request_queue_items.c.position)).all()


def _head(conn, queue_id):
    return next((r for r in _rows(conn, queue_id) if r.status not in TERMINAL), None)


def _busy(queue):
    return bool(queue.processing_token and queue.processing_until and queue.processing_until > now())


def guard_request(conn, request_id: str):
    """Protect all legacy mutation paths too; return queue_id for queued requests."""
    item = conn.execute(select(T.request_queue_items).where(
        T.request_queue_items.c.request_id == request_id)).first()
    if item is None:
        return None
    from rentwise.services.plans import _ws
    _ws(conn, lock=True)
    _assert_current(conn, item.queue_id, request_id)
    return item.queue_id


def _assert_current(conn, queue_id, request_id, *, token=None):
    q = _queue(conn, queue_id)
    head = _head(conn, queue_id)
    if head is None or head.request_id != request_id:
        raise ApiError(409, "QUEUE_OUT_OF_TURN", "앞 요청을 확정하거나 보류한 뒤 처리해 주세요.",
                       {"current_request_id": head.request_id if head else None}, retryable=True)
    if _busy(q) and q.processing_token != token:
        raise ApiError(409, "QUEUE_BUSY", "이 요청을 해석 중입니다. 잠시 후 대기열을 새로고침해 주세요.",
                       {"retry_after_seconds": LEASE_SECONDS}, retryable=True)
    return q


def latest(conn):
    qid = conn.execute(select(T.request_queues.c.id).order_by(
        T.request_queues.c.created_at.desc(), T.request_queues.c.id.desc()).limit(1)).scalar()
    return view(conn, qid) if qid else None


def view(conn, queue_id):
    from rentwise.services.plans import _ws
    q = _queue(conn, queue_id)
    head = _head(conn, queue_id)
    items = []
    for row in _rows(conn, queue_id):
        request = requests.request_view(conn, row.request_id)
        state = row.status if row.status in TERMINAL or (head and row.request_id == head.request_id) else "WAITING"
        if head and row.request_id == head.request_id and _busy(q):
            state = "INTERPRETING"
        items.append({"position": row.position, "state": state, "request": request,
                      "hold_reason": row.hold_reason})
    return {"id": q.id, "created_at": iso(q.created_at), "status": "ACTIVE" if head else "DONE",
            "current_request_id": head.request_id if head else None, "state_revision": _ws(conn).state_revision,
            "items": items}


def create(conn, items: list[dict], actor: str):
    from rentwise.services.plans import _ws
    from rentwise.services.operations import clock_anchor
    _ws(conn, lock=True)
    open_item = conn.execute(select(T.request_queue_items.c.queue_id).join(
        T.requests, T.requests.c.id == T.request_queue_items.c.request_id)
        .where(T.requests.c.status.not_in(TERMINAL)).limit(1)).first()
    if open_item:
        raise ApiError(409, "QUEUE_ALREADY_ACTIVE", "진행 중인 대기열을 먼저 처리해 주세요.",
                       {"queue_id": open_item.queue_id})
    if not 1 <= len(items) <= 3:
        raise ApiError(422, "QUEUE_SIZE", "한 번에 1~3개 요청을 접수할 수 있습니다.")
    qid = "RQ-" + uuid.uuid4().hex[:16]
    conn.execute(insert(T.request_queues).values(id=qid, created_at=now(), created_by=actor))
    received = clock_anchor()
    for pos, body in enumerate(items, 1):
        r = requests.create_request(conn, body.get("source_customer_id"), received,
                                    body["text"], None, actor)
        conn.execute(insert(T.request_queue_items).values(queue_id=qid, position=pos, request_id=r["id"]))
    return view(conn, qid)


def interpret_current(queue_id: str, request_id: str, expected_request_revision: int):
    from rentwise.services.plans import _ws
    # Commit lease first; do not retain a DB connection during the model call.
    token = uuid.uuid4().hex
    with get_db_engine().begin() as conn:
        _ws(conn, lock=True)
        _assert_current(conn, queue_id, request_id)
        inp = requests.interpretation_input(conn, request_id, expected_request_revision)
        if requests.latest_interpretation(conn, request_id) is not None:
            return requests.request_view(conn, request_id)  # Reload/double-click must not bill twice.
        conn.execute(update(T.request_queues).where(T.request_queues.c.id == queue_id).values(
            processing_token=token, processing_until=now() + timedelta(seconds=LEASE_SECONDS)))
    try:
        engine = requests.get_engine()
        result = engine.interpret(inp)
        from rentwise.services.ai_ledger import record_call
        record_call(request_id, engine.mode, result)
        with get_db_engine().begin() as conn:
            _ws(conn, lock=True)
            q = _assert_current(conn, queue_id, request_id, token=token)
            if q.processing_token != token or not _busy(q):
                raise ApiError(409, "QUEUE_LEASE_EXPIRED", "해석 처리 시간이 지났습니다. 대기열을 새로고침해 주세요.")
            requests.interpretation_input(conn, request_id, expected_request_revision)
            return requests.store_interpretation(conn, request_id, result)
    finally:
        with get_db_engine().begin() as conn:
            conn.execute(update(T.request_queues).where(
                (T.request_queues.c.id == queue_id) & (T.request_queues.c.processing_token == token))
                .values(processing_token=None, processing_until=None))


def create_plan(conn, queue_id, request_id, interpretation_revision, actor):
    from rentwise.services import plans
    ws = plans._ws(conn, lock=True)
    _assert_current(conn, queue_id, request_id)
    # Deliberately obtain the current workspace revision on the server, never a
    # batch-creation revision or the preceding request's saved candidate.
    return plans.create_plan(conn, request_id, interpretation_revision, ws.state_revision, [], actor)


def note_hold(conn, request_id, reason):
    conn.execute(update(T.request_queue_items).where(T.request_queue_items.c.request_id == request_id)
                 .values(hold_reason=reason[:200]))


def hold(conn, queue_id, request_id, reason, actor):
    from rentwise.services.plans import _ws
    _ws(conn, lock=True)
    _assert_current(conn, queue_id, request_id)
    reason = reason.strip()
    if not reason:
        raise ApiError(422, "HOLD_REASON_REQUIRED", "보류 사유를 입력해 주세요.")
    conn.execute(update(T.requests).where(T.requests.c.id == request_id).values(status="HELD"))
    conn.execute(update(T.plans).where((T.plans.c.request_id == request_id) &
                                     T.plans.c.status.in_(("READY", "UNRESOLVED"))).values(status="HELD"))
    note_hold(conn, request_id, reason)
    conn.execute(insert(T.audit_log).values(id=uuid.uuid4().hex[:20], actor=actor,
                                            action="QUEUE_HOLD", entity_id=request_id, occurred_at=now()))
    return view(conn, queue_id)
