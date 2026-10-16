#!/usr/bin/env bash
# 앱 스키마 논리 백업 (Data Pump). 배포 전·리허설 후 실행. 같은 서버 백업은 DR 이 아님.
set -euo pipefail
cd "$(dirname "$0")/.."
source .env
TS="$(date +%Y%m%d-%H%M%S)"
docker exec rentwise-db bash -lc "mkdir -p /opt/oracle/oradata/backup && \
  expdp ${DB_USER:-rentwise}/${DB_PASSWORD}@FREEPDB1 schemas=${DB_USER:-rentwise} \
  directory=DATA_PUMP_DIR dumpfile=rentwise-$TS.dmp logfile=rentwise-$TS.log" \
  && echo "✓ 백업: rentwise-$TS.dmp (컨테이너 DATA_PUMP_DIR)"
