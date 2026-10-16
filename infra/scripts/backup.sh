#!/usr/bin/env bash
# 앱 데이터 논리 백업 → infra/backups/ (+ 도쿄 Object Storage 업로드)
#   ./scripts/backup.sh              # 앱 서버(team-4-1)에서. api 컨테이너가 DB 를 읽어 JSON 으로 내보냄
# .env 의 BACKUP_UPLOAD_URL(쓰기 전용 사전 인증 URL, .../o/ 로 끝남)이 있으면 업로드한다.
# 매시간 실행은 ./scripts/install-backup-cron.sh
set -euo pipefail
cd "$(dirname "$0")/.."                       # infra/
envval() { { grep -E "^$1=" .env 2>/dev/null || true; } | tail -n1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//; s/[[:space:]]*$//'; }

KEEP="${BACKUP_KEEP:-48}"
LABEL="$(envval BACKUP_LABEL)"; LABEL="${LABEL:-seoul}"
URL="$(envval BACKUP_UPLOAD_URL)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p backups
F="backups/rentwise-$TS.json.gz"

docker compose exec -T api python -m rentwise.backup export | gzip -9 > "$F.part"
gzip -t "$F.part"
mv "$F.part" "$F"
SIZE="$(wc -c < "$F" | tr -d ' ')"
SUM="$(sha256sum "$F" | cut -c1-16)"
REV="$(gunzip -c "$F" | docker compose exec -T api python -m rentwise.backup summary | grep -E '"state_revision"' | tr -dc '0-9')"

UP="skip"
if [ -n "$URL" ]; then
  OBJ="rentwise/$LABEL/rentwise-$TS.json.gz"
  if curl -fsS --retry 3 --max-time 60 -T "$F" -H "Content-Type: application/gzip" "${URL}${OBJ}" -o /dev/null; then
    UP="ok:$OBJ"
  else
    UP="FAIL"
  fi
fi

# 로컬 보관: 최근 KEEP 개
ls -1t backups/rentwise-*.json.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
echo "$(date -Is) backup file=$F bytes=$SIZE sha256=$SUM state_revision=${REV:-?} upload=$UP"
[ "$UP" != "FAIL" ]
