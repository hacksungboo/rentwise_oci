#!/usr/bin/env bash
# 시연 전 점검. 모두 ✓ 이면 끝.
set -uo pipefail
cd "$(dirname "$0")/.."
ok() { echo "✓ $1"; }; ng() { echo "✗ $1"; FAIL=1; }; FAIL=0
HOST="$(grep -E '^PUBLIC_HOSTNAME=' .env 2>/dev/null | cut -d= -f2)"; HOST="${HOST:-rentwise.ccmall.shop}"

echo "== 1. 컨테이너"; docker compose ps --format 'table {{.Name}}\t{{.State}}\t{{.Health}}'
SERVICES="api web cloudflared"
grep -qE '^COMPOSE_PROFILES=.*localdb' .env 2>/dev/null && SERVICES="db $SERVICES"
DBH="$(grep -E '^DB_HOST=' .env 2>/dev/null | cut -d= -f2)"; DBH="${DBH:-db}"
for s in $SERVICES; do
  st="$(docker compose ps --format '{{.State}}' "$s" 2>/dev/null)"; [ "$st" = "running" ] && ok "$s running" || ng "$s ($st)"
done
if [ "$DBH" != "db" ]; then
  echo "== 1-1. DB 서버 연결 ($DBH:1521)"
  timeout 3 bash -c "</dev/tcp/$DBH/1521" 2>/dev/null && ok "DB 서버 1521 연결" || ng "DB 서버 $DBH:1521 연결 실패"
fi
echo "== 2. 내부 경로 (web → api → db)"
curl -fsS http://127.0.0.1:8080/healthz >/dev/null && ok "web /healthz" || ng "web /healthz"
R="$(curl -fsS http://127.0.0.1:8080/api/v1/health/ready 2>/dev/null)" && ok "api ready: $R" || ng "api ready"
echo "== 3. 버전"; curl -fsS http://127.0.0.1:8080/api/v1/version; echo
echo "== 4. 터널"
docker compose logs cloudflared 2>/dev/null | grep -q "Registered tunnel connection" && ok "터널 연결됨" || ng "터널 연결 로그 없음"
echo "== 5. 공개 주소"
curl -fsS "https://$HOST/healthz" >/dev/null && ok "https://$HOST" || ng "https://$HOST 접속 실패"
echo "== 6. 외부 노출 확인 (1521/8000 이 0.0.0.0 에 열려 있으면 안 됨)"
ss -ltn | grep -E ':(1521|8000)\s' | grep -v 127.0.0.1 && ng "DB/API 포트 외부 노출" || ok "DB/API 포트 비공개"
exit $FAIL
