"""논리 백업 왕복: 확정 후 상태를 백업 → 초기화 → 복원하면 같은 snapshot·revision 으로 돌아온다."""
import json


def test_backup_roundtrip_restores_confirmed_state(admin):
    from tests.test_main_flow import _confirmable_plan
    from rentwise import backup
    from rentwise.db import database

    plan, rev = _confirmable_plan(admin)
    r = admin.post(f"/api/v1/plans/{plan['id']}/confirm", json={"expected_plan_revision": 1, "base_state_revision": rev})
    assert r.status_code == 200, r.text
    eng = database.get_db_engine()
    with eng.connect() as c:
        before = database.read_snapshot(c)
        data = json.loads(json.dumps(backup.export_data(c)))       # 실제 파일처럼 직렬화
    assert data["state_revision"] == rev + 1 and data["current_plan_id"] == plan["id"]

    assert admin.post("/api/v1/admin/reset").status_code == 200    # 다른 상태로 바꿔 놓고
    with eng.connect() as c:
        assert database.read_snapshot(c) != before

    with eng.begin() as c:
        counts = backup.restore_data(c, data)
    assert counts["rw_jobs"] == len(before["jobs"])
    with eng.connect() as c:
        assert database.read_snapshot(c) == before
    ops = admin.get("/api/v1/operations").json()
    assert ops["workspace"]["state_revision"] == rev + 1 and ops["workspace"]["current_plan_id"] == plan["id"]
    assert backup.summary(data)["rows"]["rw_plans"] >= 2
