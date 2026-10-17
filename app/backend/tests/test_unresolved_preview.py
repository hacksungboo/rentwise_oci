"""An absent feasible candidate is not a proposal to delete the current schedule."""
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from rentwise.contracts import types as c
from rentwise.engine import RealEngine
from tests.test_request_queue import intent, reviewed, snapshot
from tests.engine.test_compat import request


@pytest.mark.parametrize("status", ["NEEDS_REVIEW", "NO_SOLUTION_FOUND", "DATA_MISSING"])
@pytest.mark.parametrize("partial", [False, True])
def test_unsolved_result_has_no_removal_or_partial_diff(admin, monkeypatch, status, partial):
    from rentwise.services import plans
    before = snapshot()
    result = RealEngine().solve(request(operations=[dict(operation="RESCHEDULE", kind="AS", target_job_id="J-AS1",
        window_start="2026-10-16T10:50:00+09:00", window_end="2026-10-16T10:55:00+09:00", due_at="2026-10-16T11:00:00+09:00")]))
    assert not result.candidate_items
    if partial:
        result = result.model_copy(update={"candidate_items": [c.PlanItem(**before["plan_items"][0])]})
    result = result.model_copy(update={"status": status})
    engine = RealEngine()
    monkeypatch.setattr(engine, "solve", lambda inp: result)
    monkeypatch.setattr(plans, "get_engine", lambda: engine)
    rid = admin.post("/api/v1/requests", json={"source_customer_id": "C-B", "text": "AS 방문 변경"}).json()["id"]
    req = reviewed(admin, {"id": rid, "interpretation": {"payload": intent(1)}}, 1)
    r = admin.post("/api/v1/plans", json={"request_id": rid,
        "interpretation_revision": req["interpretation"]["revision"], "base_state_revision": 7})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["status"] == "UNRESOLVED"
    assert p["diff"] == [], "An unsolved candidate must not remove/replace any existing job in the preview"
    assert p["result"]["unresolved"]
    assert admin.get(f"/api/v1/plans/{p['id']}").json()["diff"] == []
    assert admin.post(f"/api/v1/plans/{p['id']}/confirm", json={
        "expected_plan_revision": 1, "base_state_revision": 7}).status_code == 422
    assert snapshot() == before


def test_busy_impossible_as_keeps_all_169_operating_items_and_no_deletion_preview(admin, monkeypatch):
    path = os.environ.get("RENTWISE_BUSY_SEED")
    if not path:
        pytest.skip("RENTWISE_BUSY_SEED operational fixture not supplied")
    from rentwise.db import database
    from rentwise.services import plans
    monkeypatch.setattr(plans, "settings", replace(plans.settings, seed_path=Path(path)))
    monkeypatch.setattr(plans, "get_engine", lambda: RealEngine(as_of="2026-10-16T09:00:00+09:00"))
    with database.get_db_engine().begin() as conn:
        database.load_seed(conn, json.loads(Path(path).read_text()))
    before = snapshot()
    rid = admin.post("/api/v1/requests", json={"source_customer_id": "C-G", "text": "AS 방문 변경"}).json()["id"]
    payload = intent(1, True)
    op = payload["operations"][0]
    # Five minutes cannot contain the required service; this must remain unsolved.
    op.update(window_start="2026-10-16T11:25:00+09:00", window_end="2026-10-16T11:30:00+09:00",
              due_at="2026-10-16T11:30:00+09:00")
    payload["needs_confirmation"] = []
    saved = admin.put(f"/api/v1/requests/{rid}/interpretation", json={"expected_request_revision": 1,
        "payload": payload, "acknowledged_paths": []})
    assert saved.status_code == 200, saved.text
    p = admin.post("/api/v1/plans", json={"request_id": rid,
        "interpretation_revision": saved.json()["interpretation"]["revision"], "base_state_revision": 7}).json()
    assert p["status"] == "UNRESOLVED" and p["solver_status"] == "NO_SOLUTION_FOUND"
    assert p["diff"] == []
    assert p["result"]["unresolved"][0]["code"] == "NO_VALID_CANDIDATE"
    assert len(before["plan_items"]) == 169
    assert snapshot() == before
