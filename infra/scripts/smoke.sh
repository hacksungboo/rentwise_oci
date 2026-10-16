#!/usr/bin/env bash
# 실제 Oracle 로 메인 시연 동선 시험 (시작·끝에 시연 데이터 초기화)
#   SMOKE_USER=admin SMOKE_PASSWORD=... ./scripts/smoke.sh          # real 모드면 AI 1회 호출(약 $0.001)
#   SMOKE_AI=0 SMOKE_PASSWORD=... ./scripts/smoke.sh                 # AI 호출 없이 계산·확정만
set -euo pipefail
cd "$(dirname "$0")/.."
: "${SMOKE_USER:=admin}"
: "${SMOKE_PASSWORD:?SMOKE_PASSWORD 에 admin 비밀번호를 넣으세요}"
docker compose exec -T -e SMOKE_USER="$SMOKE_USER" -e SMOKE_PASSWORD="$SMOKE_PASSWORD" -e SMOKE_AI="${SMOKE_AI:-1}" api python - < scripts/smoke.py
