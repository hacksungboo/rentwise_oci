"""서버에서 실제 DB(Oracle)로 메인 시연 동선 전체를 시험한다.

  ./scripts/smoke.sh            # api 컨테이너 안에서 실행됨
주의: 시작할 때 시연 데이터를 초기화한다(/admin/reset). 측정 원자료가 있으면 먼저 백업.
표준 라이브러리만 사용 (api 이미지에 추가 설치 불필요).
"""
import json
import os
import sys
import urllib.request

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:8000/api/v1")
USER = os.environ["SMOKE_USER"]
PW = os.environ["SMOKE_PASSWORD"]
# 운영 쿠키는 Secure(HTTPS 전용)라 http://127.0.0.1 에서는 cookiejar 가 다시 보내지 않는다.
# 서버 내부 시험이므로 Set-Cookie 값을 직접 Cookie 헤더로 넘긴다.
COOKIE = {"value": ""}
LAST = {"status": None, "body": None}


def call(method, path, body=None, headers=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    if COOKIE["value"]:
        h["Cookie"] = COOKIE["value"]
    req = urllib.request.Request(BASE + path, method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            sc = r.headers.get("Set-Cookie")
            if sc:
                COOKIE["value"] = sc.split(";", 1)[0]
            status, data = r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        status, data = e.code, json.loads(e.read() or b"null")
    LAST.update(status=status, body=data)
    return status, data


def step(name, cond, detail=""):
    print(("✓ " if cond else "✗ ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        print(f"  └ 마지막 응답 HTTP {LAST['status']}: {json.dumps(LAST['body'], ensure_ascii=False)[:500]}")
        sys.exit(1)


s, v = call("GET", "/version")
step("버전", s == 200, f"db={v.get('db')} engine={v.get('engine_mode')} banner={v.get('db_banner')}")
s, _ = call("POST", "/sessions", {"username": USER, "password": PW})
step("로그인", s == 200)
s, _ = call("POST", "/admin/reset")
step("시연 데이터 초기화", s == 200)
s, ops = call("GET", "/operations")
rev = ops["workspace"]["state_revision"]
step("운영 현황 / 물리 합계 12", s == 200 and ops["total_assets"] == 12, f"r{rev}")

text = "안녕하세요 한빛상사입니다. 오늘 프린터 회수를 오후 2시로 미뤄 주실 수 있을까요?"
s, req = call("POST", "/requests", {"source_customer_id": "C-H", "text": text}, {"Idempotency-Key": "smoke-req"})
step("요청 저장 (한글 원문)", s in (200, 201) and req["text"] == text, req.get("id", ""))
if os.environ.get("SMOKE_AI", "1") == "0":
    # 유료 AI 호출 없이: 사람이 직접 입력한 해석으로 계산·확정 경로만 시험
    payload = {"schema_version": "rental.intent.v1", "needs_confirmation": [], "operations": [dict(
        operation="RESCHEDULE", kind="PICKUP", target_job_id="J-PICK1", item_id=None, asset_ids=[], quantity=None,
        source_customer_id="C-H", destination_customer_id=None, window_start="2026-10-16T14:00:00+09:00",
        window_end=None, due_at=None, rental_end_at=None, priority_hint="UNKNOWN", evidence=[])]}
    step("해석 건너뜀 (SMOKE_AI=0, 직접 입력)", True)
else:
    s, r = call("POST", f"/requests/{req['id']}/interpret", {"expected_request_revision": req["revision"]})
    step("해석", s == 200, r.get("interpretation", {}).get("origin", r))
    payload = r["interpretation"]["payload"]
    o = payload["operations"][0]
    step("해석 결과: J-PICK1 회수 14:00", o.get("target_job_id") == "J-PICK1" and o.get("kind") == "PICKUP"
         and o.get("window_start") == "2026-10-16T14:00:00+09:00", json.dumps(o, ensure_ascii=False)[:300])
op = payload["operations"][0]
op["window_end"], op["due_at"] = "2026-10-16T14:10:00+09:00", "2026-10-16T17:00:00+09:00"
s, r = call("PUT", f"/requests/{req['id']}/interpretation", {
    "expected_request_revision": req["revision"], "payload": payload,
    "acknowledged_paths": [n["path"] for n in payload["needs_confirmation"]]})
step("사람 확인 저장", s == 200 and r["status"] == "READY")
s, plan = call("POST", "/plans", {"request_id": req["id"], "interpretation_revision": r["interpretation"]["revision"],
                                  "base_state_revision": rev})
step("변경안 계산", s == 201 and plan["status"] == "READY", plan.get("id", plan))
diff = {d["job_id"]: d for d in plan["diff"]}
step("회수 E2 14:00 / 납품 P02 대체", diff["J-PICK1"]["after"]["employee_id"] == "E2"
     and diff["J-DEL1"]["after"]["asset_ids"] == ["P02"])
s, c = call("POST", f"/plans/{plan['id']}/confirm", {"expected_plan_revision": 1, "base_state_revision": rev},
            {"Idempotency-Key": "smoke-confirm"})
step("확정 (트랜잭션)", s == 200, json.dumps(c, ensure_ascii=False))
s, c2 = call("POST", f"/plans/{plan['id']}/confirm", {"expected_plan_revision": 1, "base_state_revision": rev})
step("중복 확정 차단 409", s == 409)
s, ops2 = call("GET", "/operations")
step("DB 재조회: 현행 계획·revision", ops2["workspace"]["current_plan_id"] == plan["id"]
     and ops2["workspace"]["state_revision"] == rev + 1, f"r{ops2['workspace']['state_revision']}")
assets = {a["id"]: a for a in ops2["assets"]}
step("실제 장비 상태 불변 (event 전)", assets["P01"]["physical_state"] == "AT_CUSTOMER")
s, ai = call("GET", "/admin/ai")
if s == 200:
    print(f"  AI: mode={ai['engine_mode']} model={ai['model_id']} 호출 성공 {ai['calls']['ok']} / 실패 {ai['calls']['error']}"
          f" · 사용 ${ai['settled_usd']:.4f} (예약 포함 ${ai['committed_usd']:.4f} / 한도 ${ai['limit_usd']:.2f})")
s, _ = call("POST", "/admin/reset")
step("시연 데이터 원복", s == 200)
print("\n모든 단계 통과")
