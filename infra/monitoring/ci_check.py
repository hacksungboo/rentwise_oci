"""모니터링 스택 기동 시험 (CI·서버 공용). 표준 라이브러리만.
  python3 ci_check.py [host 라벨]   # 기본 ci
- Prometheus·Loki·Grafana 준비, 데이터 유입(호스트·컨테이너·프로브 메트릭, 컨테이너 로그, ai_status 라벨)
- 대시보드의 모든 쿼리가 문법 오류 없이 실행되는지
"""
import base64, json, os, sys, time, urllib.parse, urllib.request

HOST = sys.argv[1] if len(sys.argv) > 1 else "ci"
PW = os.environ.get("GRAFANA_ADMIN_PASSWORD", "ci-test-pass")
ok = True


def get(url, auth=None):
    req = urllib.request.Request(url)
    if auth:
        req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read()
    try:
        return json.loads(body)
    except ValueError:
        return body.decode()


def check(name, cond, detail=""):
    global ok
    print(("✓ " if cond else "✗ ") + name + (f"  {detail}" if detail else ""))
    ok &= bool(cond)


def prom(q):
    return get("http://127.0.0.1:9090/api/v1/query?" + urllib.parse.urlencode({"query": q}))


def loki(q, instant=True):
    now = int(time.time() * 1e9)
    if instant:
        return get("http://127.0.0.1:3100/loki/api/v1/query?" + urllib.parse.urlencode({"query": q, "time": now}))
    return get("http://127.0.0.1:3100/loki/api/v1/query_range?" + urllib.parse.urlencode(
        {"query": q, "start": now - 3600 * 10**9, "end": now, "limit": 10}))


def value(res):
    r = res["data"]["result"]
    return float(r[0]["value"][1]) if r and "value" in r[0] else (len(r) if r else 0)


check("Prometheus 준비", "Ready" in str(get("http://127.0.0.1:9090/-/ready")))
check("Loki 준비", "ready" in str(get("http://127.0.0.1:3100/ready")))
check("Grafana 준비", get("http://127.0.0.1:3000/api/health").get("database") == "ok")

check("호스트 메트릭", value(prom(f'count(node_cpu_seconds_total{{host="{HOST}"}})')) > 0)
check("메모리 메트릭", value(prom(f'count(node_memory_MemAvailable_bytes{{host="{HOST}"}})')) > 0)
check("디스크 메트릭 (/)", value(prom(f'count(node_filesystem_size_bytes{{host="{HOST}",mountpoint="/"}})')) > 0)
check("컨테이너 메트릭", value(prom(f'count(container_last_seen{{host="{HOST}",name=~".+"}})')) > 0)
check("서비스 프로브", value(prom(f'count(probe_success{{host="{HOST}"}})')) > 0)
check("컨테이너 로그 유입", value(loki(f'sum(count_over_time({{host="{HOST}"}} [10m]))')) > 0)
check("AI 해석 라벨(ai_status)", value(loki('sum(count_over_time({container="rentwise-api", ai_status=~".+"} [10m]))')) > 0)

ds = get("http://127.0.0.1:3000/api/datasources", f"admin:{PW}")
check("Grafana 데이터소스 2개", {d["uid"] for d in ds} >= {"prometheus", "loki"})
dash = get("http://127.0.0.1:3000/api/dashboards/uid/rentwise-ops", f"admin:{PW}")
check("대시보드 등록", dash.get("dashboard", {}).get("title") == "rentwise 운영")

for p in dash.get("dashboard", {}).get("panels", []):
    for t in p.get("targets", []):
        q = t["expr"].replace("$container", ".+")
        try:
            if t["datasource"]["uid"] == "prometheus":
                r = prom(q)
            else:
                r = loki(q, instant=t.get("queryType") == "instant")
            check(f"쿼리: {p['title']}", r.get("status") == "success")
        except Exception as exc:  # 문법 오류는 HTTP 400
            check(f"쿼리: {p['title']}", False, str(exc)[:200])

print("\n모든 확인 통과" if ok else "\n실패 항목이 있습니다")
sys.exit(0 if ok else 1)
