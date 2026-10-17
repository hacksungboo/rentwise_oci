#!/usr/bin/env bash
# 앱 데이터 논리 백업 → infra/backups/ (+ 도쿄 Object Storage 업로드)
#   ./scripts/backup.sh              # 앱 서버(team-4-1)에서. api 컨테이너가 DB 를 읽어 JSON 으로 내보냄
# .env 의 BACKUP_UPLOAD_URL(쓰기 전용 사전 인증 URL, .../o/ 로 끝남)이 있으면 업로드한다.
# 업로드 파일은 BACKUP_ENCRYPT_KEY 로 암호화(AES-256-CBC, PBKDF2) + 위변조 검사(HMAC-SHA256)한다. 키가 없으면 업로드하지 않는다.
#   파일 형식: 첫 줄 "rwenc1 <hmac 64자>" + 암호문.  로컬 backups/ 에는 평문 gzip 을 둔다(서버 디스크).
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

# 배포(CD)로 api 가 교체되는 중이면 최대 3분 기다린다 (매시간 실행이 배포 시각과 겹칠 수 있음)
for i in $(seq 1 36); do
  docker compose ps --status running --services 2>/dev/null | grep -qx api && break
  [ "$i" = 1 ] && echo "$(date -Is) api 가 실행 중이 아님 → 대기"
  sleep 5
done
docker compose exec -T api python -m rentwise.backup export | gzip -9 > "$F.part"
gzip -t "$F.part"
mv "$F.part" "$F"
SIZE="$(wc -c < "$F" | tr -d ' ')"
SUM="$(sha256sum "$F" | cut -c1-16)"
REV="$(gunzip -c "$F" | docker compose exec -T api python -m rentwise.backup summary | grep -E '"state_revision"' | tr -dc '0-9')"

UP="skip"
if [ -n "$URL" ]; then
  KEY="$(envval BACKUP_ENCRYPT_KEY)"
  if [ -z "$KEY" ]; then
    echo "BACKUP_ENCRYPT_KEY 가 없어 업로드하지 않습니다 (openssl rand -base64 32 로 만들어 .env 에 추가)" >&2
    UP="FAIL"
  else
    E="$(mktemp)"; trap 'rm -f "$E" "$E.c"' EXIT
    BK="$KEY" openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:BK -in "$F" -out "$E.c"
    MAC="$(openssl dgst -sha256 -hmac "$KEY:mac" -r < "$E.c" | cut -d' ' -f1)"
    { printf 'rwenc1 %s\n' "$MAC"; cat "$E.c"; } > "$E"
    OBJ="rentwise/$LABEL/rentwise-$TS.json.gz.enc"
    if curl -fsS --retry 3 --max-time 60 -T "$E" -H "Content-Type: application/octet-stream" "${URL}${OBJ}" -o /dev/null; then
      UP="ok:$OBJ"
    else
      UP="FAIL"
    fi
  fi
fi

# 로컬 보관: 최근 KEEP 개
ls -1t backups/rentwise-*.json.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
echo "$(date -Is) backup file=$F bytes=$SIZE sha256=$SUM state_revision=${REV:-?} upload=$UP"
[ "$UP" != "FAIL" ]
