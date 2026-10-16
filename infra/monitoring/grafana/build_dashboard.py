"""Grafana 대시보드(rentwise.json) 생성. python3 build_dashboard.py"""
import json
from pathlib import Path

P = {"type": "prometheus", "uid": "prometheus"}
L = {"type": "loki", "uid": "loki"}
panels = []


def add(kind, title, x, y, w, h, targets, unit=None, ds=P, **extra):
    p = {"id": len(panels) + 1, "type": kind, "title": title, "datasource": ds,
         "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "targets": [{"refId": chr(65 + i), "datasource": ds, **t} for i, t in enumerate(targets)],
         "fieldConfig": {"defaults": {}, "overrides": []}, "options": {}}
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    for k, v in extra.items():
        if k == "defaults":
            p["fieldConfig"]["defaults"].update(v)
        else:
            p[k] = v
    panels.append(p)


def row(title, y):
    panels.append({"id": len(panels) + 1, "type": "row", "title": title, "collapsed": False,
                   "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []})


STAT = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "colorMode": "background", "graphMode": "none", "textMode": "value", "justifyMode": "center"}

row("서비스", 0)
add("stat", "서비스 상태 (공개 주소)", 0, 1, 4, 4, [{"expr": "min(probe_success)", "instant": True}], options=STAT,
    defaults={"mappings": [{"type": "value", "options": {"1": {"text": "UP", "color": "green"}, "0": {"text": "DOWN", "color": "red"}}}],
              "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "green", "value": 1}]}})
add("stat", "응답 시간", 4, 1, 4, 4, [{"expr": "max(probe_duration_seconds)", "instant": True}], unit="s",
    options={**STAT, "colorMode": "value"})
add("stat", "AI 해석 성공 (24h)", 8, 1, 4, 4,
    [{"expr": 'sum(count_over_time({container="rentwise-api", ai_status="OK"} [24h]))', "queryType": "instant"}],
    ds=L, options={**STAT, "colorMode": "value"}, defaults={"color": {"mode": "fixed", "fixedColor": "green"}, "noValue": "0"})
add("stat", "AI 해석 실패 (24h)", 12, 1, 4, 4,
    [{"expr": 'sum(count_over_time({container="rentwise-api", ai_status="ERROR"} [24h]))', "queryType": "instant"}],
    ds=L, options={**STAT, "colorMode": "value"}, defaults={"color": {"mode": "fixed", "fixedColor": "orange"}, "noValue": "0"})
add("stat", "API 오류 로그 (1h)", 16, 1, 4, 4,
    [{"expr": 'sum(count_over_time({container="rentwise-api"} |~ "ERROR|Traceback" [1h]))', "queryType": "instant"}],
    ds=L, options={**STAT, "colorMode": "value"}, defaults={"noValue": "0"})
add("stat", "실행 중 컨테이너", 20, 1, 4, 4,
    [{"expr": 'count(container_last_seen{name=~".+"} > (time() - 60))', "instant": True}], options={**STAT, "colorMode": "value"})

add("timeseries", "HTTP 요청 (web, 상태 코드별 / 5분)", 0, 5, 12, 8,
    [{"expr": 'sum by (status) (count_over_time({container="rentwise-web"} | regexp "\\" (?P<status>[0-9]{3}) " [5m]))',
      "legendFormat": "{{status}}", "queryType": "range"}], ds=L)
add("timeseries", "AI 해석 지연 (ms)", 12, 5, 6, 8,
    [{"expr": 'avg_over_time({container="rentwise-api"} |= "ai.interpret" | regexp "latency_ms=(?P<lat>[0-9]+)" | unwrap lat | __error__="" [5m])',
      "legendFormat": "평균 지연", "queryType": "range"}], ds=L, unit="ms")
add("timeseries", "AI 토큰 (입력/출력, 1시간 합)", 18, 5, 6, 8,
    [{"expr": 'sum(sum_over_time({container="rentwise-api"} |= "ai.interpret" | regexp "tokens_in=(?P<tin>[0-9]+)" | unwrap tin | __error__="" [1h]))',
      "legendFormat": "입력", "queryType": "range"},
     {"expr": 'sum(sum_over_time({container="rentwise-api"} |= "ai.interpret" | regexp "tokens_out=(?P<tout>[0-9]+)" | unwrap tout | __error__="" [1h]))',
      "legendFormat": "출력", "queryType": "range"}], ds=L)

row("서버", 13)
add("timeseries", "CPU 사용률", 0, 14, 8, 7,
    [{"expr": '100 * (1 - avg by (host) (rate(node_cpu_seconds_total{mode="idle"}[2m])))', "legendFormat": "{{host}}"}],
    unit="percent", defaults={"min": 0, "max": 100})
add("timeseries", "메모리 사용률", 8, 14, 8, 7,
    [{"expr": '100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)', "legendFormat": "{{host}}"}],
    unit="percent", defaults={"min": 0, "max": 100})
add("timeseries", "디스크 사용률 (/)", 16, 14, 8, 7,
    [{"expr": '100 * (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})', "legendFormat": "{{host}}"}],
    unit="percent", defaults={"min": 0, "max": 100})

row("컨테이너", 21)
add("timeseries", "컨테이너 CPU (코어)", 0, 22, 12, 8,
    [{"expr": 'sum by (host, name) (rate(container_cpu_usage_seconds_total{name=~".+"}[2m]))', "legendFormat": "{{host}} · {{name}}"}])
add("timeseries", "컨테이너 메모리", 12, 22, 12, 8,
    [{"expr": 'sum by (host, name) (container_memory_working_set_bytes{name=~".+"})', "legendFormat": "{{host}} · {{name}}"}], unit="bytes")

row("로그", 30)
add("logs", "AI 해석 기록 (ai.interpret)", 0, 31, 24, 8,
    [{"expr": '{container="rentwise-api"} |= "ai."', "queryType": "range"}], ds=L,
    options={"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending"})
add("logs", "컨테이너 로그 ($container)", 0, 39, 24, 12,
    [{"expr": '{container=~"$container"}', "queryType": "range"}], ds=L,
    options={"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending"})

dash = {
    "uid": "rentwise-ops", "title": "rentwise 운영", "tags": ["rentwise"], "timezone": "Asia/Seoul",
    "schemaVersion": 39, "version": 1, "editable": False, "refresh": "30s",
    "time": {"from": "now-6h", "to": "now"},
    "templating": {"list": [{
        "name": "container", "label": "컨테이너", "type": "query", "datasource": L,
        "query": {"label": "container", "stream": "", "type": 1}, "definition": "label_values(container)",
        "includeAll": True, "multi": True, "allValue": ".+",
        "current": {"text": "All", "value": "$__all"}, "refresh": 2}]},
    "panels": panels,
}
out = Path(__file__).parent / "dashboards" / "rentwise.json"
out.write_text(json.dumps(dash, ensure_ascii=False, indent=1), encoding="utf-8")
print("wrote", out, len(panels), "panels")
