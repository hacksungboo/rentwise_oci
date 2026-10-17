"""FIFO HTTP integration. Real engine + FakeClient only; never calls OpenAI."""
import copy
import json
import os
from dataclasses import replace
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from sqlalchemy import delete, func, insert, select, update

from tests.test_real_mode import delay_intent, real, response  # noqa: F401 (pytest fixture)

TEXTS = [
    "안녕하세요 한빛상사입니다. 오늘 프린터 회수를 오후 2시로 미뤄 주실 수 있을까요?",
    "바른법무사무소입니다. 오늘 AS 방문을 오전 10시 15분으로 변경해주세요.",
    "다온회계법인입니다. 내일 AS 방문을 오후 2시 15분으로 변경해주세요.",
]


def bodies(busy=False):
    out = {"items": [{"source_customer_id": cid, "text": text} for cid, text in
                      zip(("C-H", "C-B", "C-D"), TEXTS)]}
    if busy:
        out["items"][1] = {"source_customer_id": "C-G", "text": "가람건축입니다. 오늘 AS 방문을 오전 10시 45분으로 변경해주세요."}
        out["items"][2]["text"] = "다온회계사무소입니다. 내일 AS 방문을 오후 2시 15분으로 변경해주세요."
    return out


def create(c, *, busy=False, **kw):
    r = c.post("/api/v1/request-queues", json=bodies(busy), **kw)
    assert r.status_code == 201, r.text
    return r.json()


def interpreted(c, q, index):
    rid = q["items"][index]["request"]["id"]
    r = c.post(f"/api/v1/request-queues/{q['id']}/interpret",
               json={"request_id": rid, "expected_request_revision": 1})
    assert r.status_code == 200, r.text
    return r.json()


def intent(index, busy=False):
    p = delay_intent()
    if index:
        op = p["operations"][0]
        op.update(kind="AS", target_job_id="J-AS1" if index == 1 else "J-AS2",
                  source_customer_id="C-B" if index == 1 else "C-D", item_id="WP-A" if index == 1 else "PR-A",
                  asset_ids=["W01"] if index == 1 else ["P03"],
                  window_start="2026-10-16T10:15:00+09:00" if index == 1 else "2026-10-17T14:15:00+09:00",
                  evidence=[{"path": "kind", "quote": "AS"}, {"path": "operation", "quote": "변경"},
                            {"path": "window_start", "quote": "오늘 AS 방문을 오전 10시 15분" if index == 1
                             else "내일 AS 방문을 오후 2시 15분"}])
        if busy and index == 1:
            op["source_customer_id"] = "C-G"
            op["window_start"] = "2026-10-16T10:45:00+09:00"
            op["evidence"][-1]["quote"] = "오늘 AS 방문을 오전 10시 45분"
    return p


def reviewed(c, req, index, busy=False):
    payload = req["interpretation"]["payload"]
    op = payload["operations"][0]
    # Multiple AS jobs for one customer correctly require a human target selection.
    op["target_job_id"] = ["J-PICK1", "J-AS1", "J-AS2"][index]
    op["window_end"] = ["2026-10-16T14:10:00+09:00", "2026-10-16T11:00:00+09:00", "2026-10-17T15:00:00+09:00"][index]
    op["due_at"] = ["2026-10-16T17:00:00+09:00", "2026-10-16T11:00:00+09:00", "2026-10-17T15:00:00+09:00"][index]
    if busy and index == 1:
        op["window_end"] = op["due_at"] = "2026-10-16T11:30:00+09:00"
    r = c.put(f"/api/v1/requests/{req['id']}/interpretation", json={
        "expected_request_revision": 1, "payload": payload,
        "acknowledged_paths": [x["path"] for x in payload["needs_confirmation"]]})
    assert r.status_code == 200, r.text
    return r.json()


def plan(c, q, req):
    r = c.post(f"/api/v1/request-queues/{q['id']}/plan", json={
        "request_id": req["id"], "interpretation_revision": req["interpretation"]["revision"]})
    assert r.status_code == 201, r.text
    return r.json()


def snapshot():
    from rentwise.db import database
    with database.get_db_engine().connect() as conn:
        return database.read_snapshot(conn)


def code(r, expected, status=409):
    assert r.status_code == status, r.text
    assert r.json()["error"]["code"] == expected, r.text


def test_three_real_requests_confirm_from_latest_and_preserve_predecessors(admin, real):
    provider = real(*(response(intent(i)) for i in range(3)))
    before = snapshot()
    q = create(admin)
    assert snapshot() == before
    assert [i["state"] for i in q["items"]] == ["RECEIVED", "WAITING", "WAITING"]
    prior = None
    for index in range(3):
        req = interpreted(admin, q, index)
        assert provider.calls == index + 1
        # Repeated browser request restores the interpretation without another paid attempt.
        assert interpreted(admin, q, index) == req
        assert provider.calls == index + 1
        req = reviewed(admin, req, index)
        before_draft = snapshot()
        p = plan(admin, q, req)
        assert p["status"] == "READY", json.dumps(p["result"], ensure_ascii=False)
        assert p["base_state_revision"] == 7 + index
        if prior:
            assert p["base_plan_id"] == prior
        assert snapshot() == before_draft
        r = admin.post(f"/api/v1/plans/{p['id']}/confirm", json={
            "expected_plan_revision": p["revision"], "base_state_revision": p["base_state_revision"]},
            headers={"Idempotency-Key": f"confirm-{index}"})
        assert r.status_code == 200, r.text
        assert r.json()["new_state_revision"] == 8 + index
        assert admin.post(f"/api/v1/plans/{p['id']}/confirm", json={
            "expected_plan_revision": p["revision"], "base_state_revision": p["base_state_revision"]},
            headers={"Idempotency-Key": f"confirm-{index}"}).json() == r.json()
        latest = snapshot()
        if index:
            fields = ("employee_id", "asset_ids", "start_at", "end_at", "segments")
            old_items = {p["job_id"]: p for p in before_draft["plan_items"]}
            new_items = {p["job_id"]: p for p in latest["plan_items"]}
            protected = ["J-PICK1", "J-PREP1", "J-DEL1"] + (["J-AS1"] if index == 2 else [])
            assert all({k: old_items[j][k] for k in fields} == {k: new_items[j][k] for k in fields} for j in protected)
        jobs = {j["id"]: j for j in latest["jobs"]}
        assert jobs["J-PICK1"]["window_start"].startswith("2026-10-16T14:00")
        assert jobs["J-DEL1"]["asset_ids"] == ["P02"]
        if index >= 1:
            assert jobs["J-AS1"]["window_start"].startswith("2026-10-16T10:15")
        assert latest["assets"] == before["assets"]
        prior = p["id"]
        q = admin.get(f"/api/v1/request-queues/{q['id']}").json()
        assert q["state_revision"] == 8 + index
        assert all(i["state"] == "CONFIRMED" for i in q["items"][:index + 1])
    assert q["status"] == "DONE" and q["current_request_id"] is None
    assert admin.get("/api/v1/request-queues/latest").json()["queue"] == q


def test_busy_queue_confirms_as_after_recovery_without_rejecting_existing_transfer(admin, real, monkeypatch):
    """The source window belongs to the first TRANSFER stop, not the destination."""
    path = os.environ.get("RENTWISE_BUSY_SEED")
    if not path:
        pytest.skip("RENTWISE_BUSY_SEED operational fixture not supplied; no gold data used")
    from rentwise.db import database
    from rentwise.services import plans
    monkeypatch.setattr(plans, "settings", replace(plans.settings, seed_path=Path(path)))
    with database.get_db_engine().begin() as conn:
        database.load_seed(conn, json.loads(Path(path).read_text()))
    provider = real(*(response(intent(i, True)) for i in range(3)))
    q = create(admin, busy=True)
    for i in range(3):
        req = reviewed(admin, interpreted(admin, q, i), i, True)
        before = snapshot()
        p = plan(admin, q, req)
        assert snapshot() == before
        assert p["status"] == "READY", p["result"]
        assert p["base_state_revision"] == 7 + i
        r = admin.post(f"/api/v1/plans/{p['id']}/confirm", json={
            "expected_plan_revision": 1, "base_state_revision": 7 + i})
        assert r.status_code == 200, r.text
        s = snapshot()
        jobs = {j["id"]: j for j in s["jobs"]}
        assert jobs["J-PICK1"]["window_start"].startswith("2026-10-16T14:00")
        assert jobs["J-DEL1"]["asset_ids"] == ["P02"]
        old_transfer = next(p for p in before["plan_items"] if p["job_id"] == "J-TRF1")
        transfer = next(p for p in s["plan_items"] if p["job_id"] == "J-TRF1")
        for field in ("employee_id", "asset_ids", "start_at", "end_at", "segments"):
            assert transfer[field] == old_transfer[field]
    q = admin.get(f"/api/v1/request-queues/{q['id']}").json()
    assert q["status"] == "DONE" and q["state_revision"] == 10
    assert [i["state"] for i in q["items"]] == ["CONFIRMED"] * 3
    assert provider.calls == 3


@pytest.mark.parametrize("bad", [[], [{}] * 4, [{"text": " "}],
    [{"source_customer_id": "C-H", "text": "first"}, {"source_customer_id": "unknown", "text": "last"}]])
def test_invalid_batch_is_atomic(admin, bad):
    from rentwise.db import database, tables as T
    before = snapshot()
    assert admin.post("/api/v1/request-queues", json={"items": bad}).status_code == 422
    assert snapshot() == before
    with database.get_db_engine().connect() as c:
        for t in (T.requests, T.request_queues, T.request_queue_items):
            assert c.execute(select(func.count()).select_from(t)).scalar() == 0


def test_batch_idempotency_and_only_one_open_queue(admin):
    headers = {"Idempotency-Key": "batch-one"}
    q = create(admin, headers=headers)
    assert create(admin, headers=headers) == q
    changed = bodies()
    changed["items"][0]["text"] += "!"
    code(admin.post("/api/v1/request-queues", json=changed, headers=headers), "IDEMPOTENCY_KEY_REUSED")
    code(admin.post("/api/v1/request-queues", json=bodies()), "QUEUE_ALREADY_ACTIVE")


def test_concurrent_batch_retries_do_not_duplicate_requests(admin):
    headers = {"Idempotency-Key": "concurrent-batch"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(admin.post, "/api/v1/request-queues", json=bodies(), headers=headers) for _ in range(2)]
        results = [r.result() for r in calls]
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    assert results[0].json() == results[1].json()
    assert len(admin.get("/api/v1/requests").json()["items"]) == 3


def test_concurrent_confirms_advance_only_once(admin, real):
    real(response(intent(0)))
    q = create(admin)
    p = plan(admin, q, reviewed(admin, interpreted(admin, q, 0), 0))
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(admin.post, f"/api/v1/plans/{p['id']}/confirm", json={
            "expected_plan_revision": 1, "base_state_revision": 7}) for _ in range(2)]
        results = [r.result() for r in calls]
    assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]
    latest = admin.get(f"/api/v1/request-queues/{q['id']}").json()
    assert latest["state_revision"] == 8
    assert latest["current_request_id"] == q["items"][1]["request"]["id"]


def test_confirm_rollback_does_not_advance_queue(admin, real, monkeypatch):
    from rentwise.api.errors import ApiError
    from rentwise.services import plans
    real(response(intent(0)))
    q = create(admin)
    p = plan(admin, q, reviewed(admin, interpreted(admin, q, 0), 0))
    before = snapshot()
    original = plans._finish_confirm

    def fail_after_updates(*args, **kwargs):
        original(*args, **kwargs)
        raise ApiError(503, "TEST_ROLLBACK", "시험용 저장 실패")

    monkeypatch.setattr(plans, "_finish_confirm", fail_after_updates)
    code(admin.post(f"/api/v1/plans/{p['id']}/confirm", json={
        "expected_plan_revision": 1, "base_state_revision": 7}), "TEST_ROLLBACK", 503)
    assert snapshot() == before
    latest = admin.get(f"/api/v1/request-queues/{q['id']}").json()
    assert latest["current_request_id"] == q["current_request_id"] and latest["state_revision"] == 7


@pytest.mark.parametrize("path,body", [
    ("/requests/{rid}/interpret", {"expected_request_revision": 1}),
    ("/requests/{rid}/interpretation", {"expected_request_revision": 1, "payload": delay_intent()}),
    ("/plans", {"request_id": "{rid}", "interpretation_revision": 1, "base_state_revision": 7}),
    ("/request-queues/{qid}/interpret", {"request_id": "{rid}", "expected_request_revision": 1}),
    ("/request-queues/{qid}/plan", {"request_id": "{rid}", "interpretation_revision": 1}),
    ("/request-queues/{qid}/hold", {"request_id": "{rid}", "reason": "skip"}),
])
def test_later_request_cannot_bypass_fifo(admin, path, body):
    q = create(admin)
    rid = q["items"][1]["request"]["id"]
    body = copy.deepcopy(body)
    if body.get("request_id") == "{rid}":
        body["request_id"] = rid
    method = admin.put if "interpretation" in path else admin.post
    code(method("/api/v1" + path.format(rid=rid, qid=q["id"]), json=body), "QUEUE_OUT_OF_TURN")
    assert admin.get(f"/api/v1/request-queues/{q['id']}").json() == q


def test_failure_stays_at_head_manual_fallback_hold_and_resume(admin, real):
    from rentwise.engine.interpret import ProviderFailure
    provider = real(ProviderFailure("AI_TIMEOUT"), response(intent(1)))
    q = create(admin)
    rid = q["current_request_id"]
    code(admin.post(f"/api/v1/request-queues/{q['id']}/interpret", json={
        "request_id": rid, "expected_request_revision": 1}), "AI_TIMEOUT", 502)
    assert provider.calls == 1
    q2 = admin.get("/api/v1/request-queues/latest").json()["queue"]
    assert q2["current_request_id"] == rid and q2["items"][0]["state"] == "RECEIVED"
    assert provider.calls == 1  # Reads/resume do not automatically call the model.
    code(admin.post(f"/api/v1/requests/{rid}/interpret", json={"expected_request_revision": 1}), "QUEUE_ENDPOINT_REQUIRED")
    req = reviewed(admin, {"id": rid, "interpretation": {"payload": intent(0)}}, 0)
    assert req["interpretation"]["origin"] == "HUMAN"
    before = snapshot()
    code(admin.post(f"/api/v1/request-queues/{q['id']}/hold", json={"request_id": rid, "reason": " "}),
         "HOLD_REASON_REQUIRED", 422)
    held = admin.post(f"/api/v1/request-queues/{q['id']}/hold", json={"request_id": rid, "reason": "고객 재확인"})
    assert held.status_code == 200
    assert held.json()["items"][0]["hold_reason"] == "고객 재확인"
    assert held.json()["current_request_id"] == q["items"][1]["request"]["id"]
    assert snapshot() == before
    code(admin.put(f"/api/v1/requests/{rid}/interpretation", json={
        "expected_request_revision": 1, "payload": intent(0)}), "QUEUE_OUT_OF_TURN")
    assert interpreted(admin, q, 1)["interpretation"]["origin"] == "AI"


def test_model_wait_has_no_db_connection_and_prevents_concurrent_or_skipped_work(admin, real, monkeypatch):
    from rentwise.db import database
    from rentwise.services import requests
    from sqlalchemy import event
    real(response(intent(0)))
    q = create(admin)
    rid = q["current_request_id"]
    engine = requests.get_engine()
    actual = engine.interpret
    entered, release = Event(), Event()
    active_connections = []
    event.listen(database.get_db_engine(), "checkout", lambda *a: active_connections.append(1))
    event.listen(database.get_db_engine(), "checkin", lambda *a: active_connections.pop())

    def blocked(inp):
        assert not active_connections
        entered.set()
        assert release.wait(10)
        return actual(inp)

    monkeypatch.setattr(engine, "interpret", blocked)
    url = f"/api/v1/request-queues/{q['id']}/interpret"
    body = {"request_id": rid, "expected_request_revision": 1}
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(admin.post, url, json=body)
        try:
            assert entered.wait(5)
            assert admin.get(f"/api/v1/request-queues/{q['id']}").json()["items"][0]["state"] == "INTERPRETING"
            code(admin.post(url, json=body), "QUEUE_BUSY")
            code(admin.post(f"/api/v1/request-queues/{q['id']}/hold", json={"request_id": rid, "reason": "skip"}), "QUEUE_BUSY")
            code(admin.put(f"/api/v1/requests/{rid}/interpretation", json={
                "expected_request_revision": 1, "payload": intent(0)}), "QUEUE_BUSY")
        finally:
            release.set()
        assert pending.result().status_code == 200


def test_expired_lease_recovers_after_process_loss(admin, real):
    from rentwise.db import database, tables as T
    from rentwise.timeutil import now
    real(response(intent(0)))
    q = create(admin)
    with database.get_db_engine().begin() as c:
        c.execute(update(T.request_queues).values(processing_token="lost", processing_until=now() - timedelta(seconds=1)))
    assert interpreted(admin, q, 0)["interpretation"]["origin"] == "AI"


def test_plan_hold_advances_but_stale_drafts_cannot_confirm(admin, real):
    real(response(intent(0)), response(intent(1)))
    q = create(admin)
    req = reviewed(admin, interpreted(admin, q, 0), 0)
    p = plan(admin, q, req)
    second_draft = plan(admin, q, req)
    assert admin.post(f"/api/v1/plans/{p['id']}/hold", json={"expected_plan_revision": 1, "reason": "책임자 보류"}).status_code == 200
    code(admin.post(f"/api/v1/plans/{second_draft['id']}/confirm", json={
        "expected_plan_revision": 1, "base_state_revision": 7}), "QUEUE_OUT_OF_TURN")
    q2 = admin.get(f"/api/v1/request-queues/{q['id']}").json()
    assert q2["items"][0]["state"] == "HELD" and q2["state_revision"] == 7
    assert q2["items"][0]["hold_reason"] == "책임자 보류"
    interpreted(admin, q, 1)


def test_external_confirmation_requires_recalculation_and_new_human_review_invalidates_old_draft(admin, real):
    from tests.test_main_flow import _confirmable_plan
    real(response(intent(0)), response(intent(0)))
    q = create(admin)
    req = reviewed(admin, interpreted(admin, q, 0), 0)
    p = plan(admin, q, req)
    # A legacy single request can legitimately be confirmed in another browser.
    external, rev = _confirmable_plan(admin)
    assert admin.post(f"/api/v1/plans/{external['id']}/confirm", json={
        "expected_plan_revision": 1, "base_state_revision": rev}).status_code == 200
    before = snapshot()
    code(admin.post(f"/api/v1/plans/{p['id']}/confirm", json={
        "expected_plan_revision": 1, "base_state_revision": p["base_state_revision"]}), "STALE_PLAN")
    assert snapshot() == before
    fresh = plan(admin, q, req)
    assert fresh["base_state_revision"] == 8 and fresh["base_plan_id"] == external["id"]
    reviewed(admin, req, 0)
    code(admin.post(f"/api/v1/plans/{fresh['id']}/confirm", json={
        "expected_plan_revision": 1, "base_state_revision": 8}), "STALE_INTERPRETATION")
    assert snapshot() == before


def test_all_held_queue_is_done_and_new_batch_can_start(admin):
    q = create(admin)
    before = snapshot()
    for item in q["items"]:
        r = admin.post(f"/api/v1/request-queues/{q['id']}/hold", json={
            "request_id": item["request"]["id"], "reason": "고객 확인 필요"})
        assert r.status_code == 200
    assert r.json()["status"] == "DONE"
    assert snapshot() == before
    new = create(admin)
    assert new["id"] != q["id"]


def test_backup_restore_reset_and_v1_schema_upgrade(admin):
    from rentwise import backup
    from rentwise.db import database, tables as T
    q = create(admin)
    with database.get_db_engine().connect() as c:
        data = backup.export_data(c)
    assert admin.post("/api/v1/admin/reset").status_code == 200
    assert admin.get("/api/v1/request-queues/latest").json()["queue"] is None
    with database.get_db_engine().begin() as c:
        backup.restore_data(c, data)
    assert admin.get("/api/v1/request-queues/latest").json()["queue"] == q
    # Simulate an old app DB without queue tables; startup adds them without resetting data.
    with database.get_db_engine().begin() as c:
        c.execute(delete(T.request_queue_items))
        c.execute(delete(T.request_queues))
        c.execute(delete(T.schema_version).where(T.schema_version.c.version == 2))
    T.request_queue_items.drop(database.get_db_engine())
    T.request_queues.drop(database.get_db_engine())
    before = snapshot()
    database.init_schema()
    assert snapshot() == before
    assert admin.get("/api/v1/health/ready").json()["schema_version"] == 2
    old = copy.deepcopy(data)
    old["schema_version"] = 1
    old["tables"]["rw_schema_version"] = [r for r in old["tables"]["rw_schema_version"] if r["version"] == 1]
    old["tables"].pop("rw_request_queue_items")
    old["tables"].pop("rw_request_queues")
    with database.get_db_engine().begin() as c:
        backup.restore_data(c, old)
    assert admin.get("/api/v1/health/ready").json()["schema_version"] == 2
    assert admin.get("/api/v1/request-queues/latest").json()["queue"] is None


def test_queue_requires_admin(client):
    assert client.get("/api/v1/request-queues/latest").status_code == 401
    from rentwise.api.auth import ACCOUNTS
    staff = next(k for k, u in ACCOUNTS.items() if u[0].role == "STAFF")
    assert client.post("/api/v1/sessions", json={"username": staff, "password": "rentwise2026"}).status_code == 200
    assert client.get("/api/v1/request-queues/latest").status_code == 403
    assert client.post("/api/v1/request-queues", json=bodies()).status_code == 403


def test_confirm_then_unsupported_new_deliveries_hold_without_network_or_schedule_loss(admin, real):
    """Reproduce reported 1-confirm/2-hold/3-review-blocked flow without paid AI."""
    batch = bodies()
    payloads = [intent(0)]
    for index, (customer, item, name) in enumerate((("C-B", "WP-A", "정수기"), ("C-D", "PR-A", "프린터")), 1):
        text = f"오늘 오후 4시~5시 사이에 {name} 1대 추가 설치해주세요. 반납일 미정입니다."
        batch["items"][index] = {"source_customer_id": customer, "text": text}
        payload = delay_intent()
        op = payload["operations"][0]
        op.update(operation="CREATE", kind="DELIVERY", target_job_id=None, item_id=item, asset_ids=[],
                  quantity=1, source_customer_id=None, destination_customer_id=customer,
                  window_start="2026-10-16T16:00:00+09:00", window_end="2026-10-16T17:00:00+09:00",
                  due_at=None, rental_end_at=None, evidence=[
                      {"path": "kind", "quote": "설치"}, {"path": "operation", "quote": "추가"},
                      {"path": "item_id", "quote": name}, {"path": "quantity", "quote": "1대"},
                      {"path": "window_start", "quote": "오늘 오후 4시~5시"},
                      {"path": "window_end", "quote": "오늘 오후 4시~5시"}])
        payload["needs_confirmation"] = []
        payloads.append(payload)
    provider = real(*(response(p) for p in payloads))
    made = admin.post("/api/v1/request-queues", json=batch)
    assert made.status_code == 201, made.text
    q = made.json()
    first = plan(admin, q, reviewed(admin, interpreted(admin, q, 0), 0))
    confirmed = admin.post(f"/api/v1/plans/{first['id']}/confirm", json={
        "expected_plan_revision": 1, "base_state_revision": 7})
    assert confirmed.status_code == 200
    protected = snapshot()
    for index in (1, 2):
        rid = q["items"][index]["request"]["id"]
        failed = admin.post(f"/api/v1/request-queues/{q['id']}/interpret", json={
            "request_id": rid, "expected_request_revision": 1})
        code(failed, "AI_REVIEW_UNSUPPORTED", 422)
        assert failed.json()["error"]["details"]["paths"] == ["operations.0.rental_end_at"]
        assert not failed.json()["error"]["retryable"] and failed.json()["trace_id"]
        restored = admin.get(f"/api/v1/request-queues/{q['id']}").json()
        assert restored["current_request_id"] == rid and restored["state_revision"] == 8
        request = restored["items"][index]["request"]
        assert request["interpretation"] is None and request["plans"] == []
        assert provider.calls == index + 1
        assert snapshot() == protected
        if index == 1:
            held = admin.post(f"/api/v1/request-queues/{q['id']}/hold", json={
                "request_id": rid, "reason": "반납일·신규 설치 별도 검토"})
            assert held.status_code == 200
    assert restored["items"][0]["state"] == "CONFIRMED"
    assert restored["items"][1]["state"] == "HELD"
