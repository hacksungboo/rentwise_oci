#!/usr/bin/env bash
# team-4-2 에서 실행: 앱 스키마 논리 백업 (Data Pump) → /opt/oracle/oradata/backup (볼륨 안)
set -euo pipefail
cd "$(dirname "$0")"
source .env
TS="$(date +%Y%m%d-%H%M%S)"
docker exec rentwise-db bash -lc "expdp ${DB_USER:-rentwise}/${DB_PASSWORD}@localhost:1521/FREEPDB1 schemas=${DB_USER:-rentwise} \
  directory=DATA_PUMP_DIR dumpfile=rentwise-$TS.dmp logfile=rentwise-$TS.log" \
  && echo "✓ 백업: rentwise-$TS.dmp (컨테이너 DATA_PUMP_DIR)"
