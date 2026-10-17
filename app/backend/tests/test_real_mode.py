"""real 모드 통합: AI 해석(모델 대역) → 비용 장부 → 사람 확인 → A v2 core 회수 지연 → 확정 → DB 재조회.

유료 호출 없음. 모델 응답은 대역(FakeClient), 비용 장부·DB·엔진은 실제 코드.
"""
import json
from dataclasses import replace

import pytest

TEXT = "안녕하세요 한빛상사입니다. 오늘 프린터 회수를 오후 2시로 미뤄 주실 수 있을까요?"


def delay_intent():
    q = TEXT
    op = dict(operation="RESCHEDULE", kind="PICKUP", target_job_id="J-PICK1", item_id="PR-A", asset_ids=["P01"],
              quantity=None, source_customer_id="C-H", destination_customer_id=None,
              window_start="2026-10-16T14:00:00+09:00", window_end=None, due_at=None, rental_end_at=None,
              priority_hint="UNKNOWN",
              evidence=[{"path": "kind", "quote": "회수"}, {"path": "operation", "quote": "미뤄"},
                        {"path": "window_start", "quote": "오늘 프린터 회수를 오후 2시로"}])
    return dict(schema_version="rental.intent.v1", operations=[op], needs_confirmation=[
        {"path": "operations.0.window_end", "reason": "MISSING", "question": "방문 종료 시각이 원문에 없습니다. 언제까지 방문 가능한가요?"},
        {"path": "operations.0.due_at", "reason": "MISSING", "question": "완료 기한이 원문에 없습니다. 언제까지 회수해야 하나요?"}])


def response(payload, **usage):
    u = dict(input_tokens=900, output_tokens=300, input_tokens_details={"cached_tokens": 0},
             output_tokens_details={"reasoning_tokens": 0})
    u.update(usage)
    return dict(id="resp-test", status="completed", usage=u, output=[{"type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": json.dumps(payload, ensure_ascii=False)}]}])


class FakeClient:
    def __init__(self, *outs):
        self.outs, self.calls = list(outs), 0

    def create(self, body, *, timeout):
        self.calls += 1
        o = self.outs.pop(0)
        if isinstance(o, Exception):
            raise o
        return o


@pytest.fixture()
def real(admin, monkeypatch):
    from rentwise.engine import RealEngine
    from rentwise.engine.interpret import OpenAIInterpreter
    from rentwise.services import ai_ledger, plans, requests

    def make(*outs, budget="1"):
        monkeypatch.setattr(ai_ledger, "settings", replace(ai_ledger.settings, ai_budget_usd=budget))
        ai_ledger.sync_limit()
        client = FakeClient(*outs)
        eng = RealEngine(interpreter=OpenAIInterpreter(client=client, budget=ai_ledger.LedgerBudget()))
        monkeypatch.setattr(plans, "get_engine", lambda: eng)
        monkeypatch.setattr(requests, "get_engine", lambda: eng)
        return client
    return make


def _request(c):
    r = c.post("/api/v1/requests", json={"source_customer_id": "C-H", "text": TEXT})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_real_delay_end_to_end(admin, real):
    client = real(response(delay_intent()))
    rid = _request(admin)
    r = admin.post(f"/api/v1/requests/{rid}/interpret", json={"expected_request_revision": 1})
    assert r.status_code == 200, r.text
    interp = r.json()["interpretation"]
    assert interp["origin"] == "AI" and client.calls == 1
    payload = interp["payload"]
    op = payload["operations"][0]
    assert op["target_job_id"] == "J-PICK1" and op["window_start"] == "2026-10-16T14:00:00+09:00"

    # 사람이 종료·기한을 채우고 확인
    op["window_end"], op["due_at"] = "2026-10-16T14:10:00+09:00", "2026-10-16T17:00:00+09:00"
    paths = [n["path"] for n in payload["needs_confirmation"]]
    r = admin.put(f"/api/v1/requests/{rid}/interpretation",
                  json={"expected_request_revision": 1, "payload": payload, "acknowledged_paths": paths})
    assert r.status_code == 200 and r.json()["status"] == "READY", r.text
    irev = r.json()["interpretation"]["revision"]

    plan = admin.post("/api/v1/plans", json={"request_id": rid, "interpretation_revision": irev,
                                             "base_state_revision": 7})
    assert plan.status_code == 201, plan.text
    plan = plan.json()
    assert plan["status"] == "READY" and not plan["is_mock"], plan["result"]
    diff = {d["job_id"]: d for d in plan["diff"]}
    assert diff["J-PICK1"]["after"]["service_start_at"].startswith("2026-10-16T14:00")
    assert diff["J-PICK1"]["after"]["employee_id"] == "E2"           # E1 휴식(13~14) 충돌
    assert diff["J-PREP1"]["after"]["start_at"].startswith("2026-10-16T14:30")
    assert diff["J-DEL1"]["after"]["asset_ids"] == ["P02"]           # 같은 모델 대체, 납품 시각 유지
    assert diff["J-DEL1"]["after"]["start_at"] == diff["J-DEL1"]["before"]["start_at"]
    assert "v2_candidate" not in json.dumps(plan)

    r = admin.post(f"/api/v1/plans/{plan['id']}/confirm", json={"expected_plan_revision": 1, "base_state_revision": 7})
    assert r.status_code == 200, r.text
    ops = admin.get("/api/v1/operations").json()
    assert ops["workspace"]["state_revision"] == 8 and ops["workspace"]["current_plan_id"] == plan["id"]

    from rentwise.db import database
    with database.get_db_engine().connect() as conn:
        s = database.read_snapshot(conn)
    jobs = {j["id"]: j for j in s["jobs"]}
    res = {r["id"]: r for r in s["reservations"]}
    assert jobs["J-PICK1"]["window_start"] == "2026-10-16T14:00:00+09:00"
    assert jobs["J-DEL1"]["asset_ids"] == ["P02"]
    assert res["RS-H"]["status"] == "SUPERSEDED" and res["RS-S2"]["status"] == "SUPERSEDED"
    active = [r for r in s["reservations"] if r["status"] == "ACTIVE" and r["rental_id"] in ("R-H", "R-S2")]
    assert {(r["rental_id"], r["asset_id"], r["end_at"]) for r in active} == {
        ("R-H", "P01", "2026-10-16T15:00:00+09:00"), ("R-S2", "P02", None)}

    # 다음 요청도 확정된 계획 위에서 계산 가능 (v2 로 저장한 상태가 다시 유효)
    from rentwise.services import v2_bridge
    from rentwise.services.plans import _v2_snapshot, _horizon
    ws = type("W", (), {"state_revision": 8, "dataset_version": "rental-dev-v1"})
    v2s = _v2_snapshot(s, ws, {"travel_version": "travel-v1", "policy_version": "policy-v1", **_horizon()})
    cand = {k: v2s[k] for k in ("jobs", "plan_items", "reservations", "rentals", "dependencies")}
    cand.update(schema_version="rental.candidate.v2", bundle_version="rental.bundle.v2", base_state_revision=8,
                plan_id=plan["id"], approved_job_ids=[])
    cand["reservations"] = [r for r in cand["reservations"] if r["status"] == "ACTIVE"]
    assert v2_bridge.validate(v2s, cand).status == "VALID"

    # 비용 장부·호출 기록
    ai = admin.get("/api/v1/admin/ai").json()
    assert ai["calls"] == {"ok": 1, "error": 0}
    assert 0 < ai["settled_usd"] < 0.01 and ai["committed_usd"] == ai["settled_usd"]
    assert ai["recent"][0]["status"] == "OK" and ai["recent"][0]["input_tokens"] == 900


def test_budget_exceeded_blocks_paid_call_and_is_logged(admin, real):
    client = real(response(delay_intent()), budget="0")
    rid = _request(admin)
    r = admin.post(f"/api/v1/requests/{rid}/interpret", json={"expected_request_revision": 1})
    assert r.status_code == 502 and r.json()["error"]["code"] == "BUDGET_EXCEEDED"
    assert client.calls == 0                                          # 모델을 부르지 않음
    ai = admin.get("/api/v1/admin/ai").json()
    assert ai["calls"] == {"ok": 0, "error": 1} and ai["recent"][0]["error_code"] == "BUDGET_EXCEEDED"


def test_timeout_keeps_reservation_after_rollback(admin, real):
    from rentwise.engine.interpret import ProviderFailure
    real(ProviderFailure("AI_TIMEOUT"))
    rid = _request(admin)
    r = admin.post(f"/api/v1/requests/{rid}/interpret", json={"expected_request_revision": 1})
    assert r.status_code == 502 and r.json()["error"]["code"] == "AI_TIMEOUT"
    ai = admin.get("/api/v1/admin/ai").json()
    # 응답이 없어 사용량을 모르므로 예약액을 그대로 잡아 둔다 (0 으로 되돌리지 않음)
    assert ai["settled_usd"] == 0 and ai["committed_usd"] > 0
    assert ai["recent"][0]["error_code"] == "AI_TIMEOUT"


def test_ledger_reserve_is_idempotent_and_settle_once(client):
    from decimal import Decimal
    from rentwise.contracts.types import Usage
    from rentwise.services import ai_ledger
    from dataclasses import replace as rep
    ai_ledger.settings = rep(ai_ledger.settings, ai_budget_usd="0.01")
    try:
        ai_ledger.sync_limit()
        b = ai_ledger.LedgerBudget()
        a1 = b.reserve("k1", Decimal("0.0044"))
        assert b.reserve("k1", Decimal("0.0044")) == a1                   # 같은 키 → 같은 예약
        b.reserve("k2", Decimal("0.0044"))
        from rentwise.engine.interpret import BudgetExceeded
        with pytest.raises(BudgetExceeded):
            b.reserve("k3", Decimal("0.0044"))                           # 0.0132 > 0.01
        u = Usage(input_tokens=1000, cached_input_tokens=0, output_tokens=100, reasoning_tokens=0)
        from rentwise.ai_policy import PRICE_VERSION
        b.settle(a1, u, PRICE_VERSION); b.settle(a1, u, PRICE_VERSION)
        s = ai_ledger.summary()
        assert s["settled_usd"] == pytest.approx((1000 * 2.0 * 1.25 + 100 * 12.0) / 1e6, abs=1e-6)
    finally:
        from rentwise.config import settings
        ai_ledger.settings = settings
