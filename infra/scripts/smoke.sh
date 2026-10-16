#!/usr/bin/env bash
# 실제 Oracle 로 메인 시연 동선 시험 (시작·끝에 시연 데이터 초기화)
#   SMOKE_USER=admin SMOKE_PASSWORD=... ./scripts/smoke.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${SMOKE_USER:=admin}"
: "${SMOKE_PASSWORD:?SMOKE_PASSWORD 에 admin 비밀번호를 넣으세요}"
docker compose exec -T -e SMOKE_USER="$SMOKE_USER" -e SMOKE_PASSWORD="$SMOKE_PASSWORD" api python - < scripts/smoke.py
