"""메인 시연 동선: 요청 → 해석(mock) → 사람 확인 → 변경안 → 확정 → DB 재조회.

명세 §8.2 회수 지연 사례. mock 엔진 기준이며 A 실제 엔진 인수시험(T04)을 대신하지 않는다.
"""
DELAY_TEXT = "안녕하세요 한빛상사입니다. 오늘 프린터 회수를 오후 2시로 미뤄 주실 수 있을까요?"


def _confirmable_plan(c):
    ops = c.get("/api/v1/operations").json()
    rev = ops["workspace"]["state_revision"]
    r = c.post("/api/v1/requests", json={"source_customer_id": "C-H", "text": DELAY_TEXT},
               headers={"Idempotency-Key": "req-1"})
    assert r.status_code == 201, r.text
    req = r.json()
    r = c.post(f"/api/v1/requests/{req['id']}/interpret", json={"expected_request_revision": 1})
    assert r.status_code == 200, r.text
    interp = r.json()["interpretation"]
    payload = interp["payload"]
    op = payload["operations"][0]
    assert op["operation"] == "RESCHEDULE" and op["target_job_id"] == "J-PICK1"
    assert op["window_start"] == "2026-10-16T14:00:00+09:00"
    # 사람이 확인: 14:00~14:10, 기한 17:00
    op["window_end"] = "2026-10-16T14:10:00+09:00"
    op["due_at"] = "2026-10-16T17:00:00+09:00"
    paths = [n["path"] for n in payload["needs_confirmation"]]
    r = c.put(f"/api/v1/requests/{req['id']}/interpretation",
              json={"expected_request_revision": 1, "payload": payload, "acknowledged_paths": paths})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "READY"
    irev = r.json()["interpretation"]["revision"]
    r = c.post("/api/v1/plans", json={"request_id": req["id"], "interpretation_revision": irev,
                                      "base_state_revision": rev})
    assert r.status_code == 201, r.text
    return r.json(), rev


def test_health(client):
    assert client.get("/api/v1/health/ready").json()["status"] == "ready"


def test_operations_counts(admin):
    ops = admin.get("/api/v1/operations").json()
    assert ops["total_assets"] == 12  # AC01 물리 합계
    assert ops["workspace"]["state_revision"] == 7
    e1 = next(e for e in ops["employees"] if e["id"] == "E1")
    assert [i["job_id"] for i in e1["items"]] == ["J-PICK1", "J-DEL1"]


def test_delay_flow_confirm_and_requery(admin):
    plan, rev = _confirmable_plan(admin)
    assert plan["status"] == "READY" and plan["is_mock"]
    diff = {d["job_id"]: d for d in plan["diff"]}
    # 회수 14:00, E1 휴식 충돌로 E2
    assert diff["J-PICK1"]["after"]["service_start_at"].startswith("2026-10-16T14:00")
    assert diff["J-PICK1"]["after"]["employee_id"] == "E2"
    assert "PREFERRED_EMPLOYEE_CONFLICT" in diff["J-PICK1"]["reason_codes"]
    # 새봄 납품은 같은 모델 P02로 대체, 시각 유지
    assert diff["J-DEL1"]["after"]["asset_ids"] == ["P02"]
    assert diff["J-DEL1"]["after"]["start_at"] == diff["J-DEL1"]["before"]["start_at"]

    # 초안은 운영 상태를 바꾸지 않음 (AC04)
    ops = admin.get("/api/v1/operations").json()
    assert ops["workspace"]["state_revision"] == rev

    r = admin.post(f"/api/v1/plans/{plan['id']}/confirm",
                   json={"expected_plan_revision": 1, "base_state_revision": rev},
                   headers={"Idempotency-Key": "cf-1"})
    assert r.status_code == 200, r.text
    assert r.json()["new_state_revision"] == rev + 1
    # 같은 키 재전송 → 같은 결과
    r2 = admin.post(f"/api/v1/plans/{plan['id']}/confirm",
                    json={"expected_plan_revision": 1, "base_state_revision": rev},
                    headers={"Idempotency-Key": "cf-1"})
    assert r2.json() == r.json()

    # DB 재조회: 현행 계획 교체, 실제 장비 상태는 그대로 (event 전)
    ops = admin.get("/api/v1/operations").json()
    assert ops["workspace"]["current_plan_id"] == plan["id"]
    e2 = next(e for e in ops["employees"] if e["id"] == "E2")
    assert "J-PICK1" in [i["job_id"] for i in e2["items"]]
    assets = {a["id"]: a for a in ops["assets"]}
    assert assets["P01"]["physical_state"] == "AT_CUSTOMER"
    assert assets["P02"]["physical_state"] == "READY_WAREHOUSE"


def test_stale_confirm_conflict(admin):
    plan, rev = _confirmable_plan(admin)
    r = admin.post(f"/api/v1/plans/{plan['id']}/confirm",
                   json={"expected_plan_revision": 1, "base_state_revision": rev})
    assert r.status_code == 200
    r = admin.post(f"/api/v1/plans/{plan['id']}/confirm",
                   json={"expected_plan_revision": 1, "base_state_revision": rev})
    assert r.status_code == 409


def test_unconfirmed_fields_block_plan(admin):
    r = admin.post("/api/v1/requests", json={"source_customer_id": "C-H", "text": DELAY_TEXT})
    req = r.json()
    admin.post(f"/api/v1/requests/{req['id']}/interpret", json={"expected_request_revision": 1})
    r = admin.post("/api/v1/plans", json={"request_id": req["id"], "interpretation_revision": 1,
                                          "base_state_revision": 7})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNCONFIRMED_FIELDS"


def test_staff_cannot_confirm(client):
    client.post("/api/v1/sessions", json={"username": "e1", "password": "rentwise2026"})
    r = client.post("/api/v1/requests", json={"text": "test"})
    assert r.status_code == 403


def test_reset(admin):
    _confirmable_plan(admin)
    assert admin.post("/api/v1/admin/reset").status_code == 200
    assert admin.get("/api/v1/operations").json()["workspace"]["state_revision"] == 7
