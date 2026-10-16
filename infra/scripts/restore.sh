#!/usr/bin/env bash
# 논리 백업 복원 (현재 DB 의 앱 데이터를 백업 내용으로 통째로 교체)
#   ./scripts/restore.sh backups/rentwise-20261017T010000Z.json.gz   # 로컬 파일
#   ./scripts/restore.sh latest                                      # 도쿄 버킷의 최신 (BACKUP_READ_URL 필요)
#   ./scripts/restore.sh latest --yes                                # 확인 없이
# 복원 직전 현재 상태를 backups/pre-restore-*.json.gz 로 남긴다.
set -euo pipefail
cd "$(dirname "$0")/.."
envval() { { grep -E "^$1=" .env 2>/dev/null || true; } | tail -n1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//; s/[[:space:]]*$//'; }
SRC="${1:?복원할 파일 경로 또는 latest}"; YES="${2:-}"
mkdir -p backups
T0="$(date +%s)"

if [ "$SRC" = "latest" ]; then
  URL="$(envval BACKUP_READ_URL)"; LABEL="$(envval BACKUP_SOURCE_LABEL)"; LABEL="${LABEL:-seoul}"
  [ -n "$URL" ] || { echo "BACKUP_READ_URL 이 .env 에 없습니다"; exit 1; }
  OBJ="$(curl -fsS --max-time 30 "${URL}?prefix=rentwise/$LABEL/&limit=1000" \
        | docker compose exec -T api python -c 'import json,sys; o=[x["name"] for x in json.load(sys.stdin).get("objects",[]) if x["name"].endswith((".json.gz", ".json.gz.enc"))]; print(max(o, key=lambda n: n.rsplit("/",1)[-1].split(".")[0]) if o else "")')"
  [ -n "$OBJ" ] || { echo "버킷에 백업이 없습니다 (prefix rentwise/$LABEL/)"; exit 1; }
  SRC="backups/$(basename "$OBJ")"
  curl -fsS --retry 3 --max-time 120 "${URL}${OBJ}" -o "$SRC.part" && mv "$SRC.part" "$SRC"
  echo "▼ 내려받음: $OBJ"
fi

# 암호화 파일이면 위변조 검사 후 복호화
if [ "${SRC%.enc}" != "$SRC" ]; then
  KEY="$(envval BACKUP_ENCRYPT_KEY)"
  [ -n "$KEY" ] || { echo "BACKUP_ENCRYPT_KEY 가 .env 에 없습니다 (서울 서버와 같은 값)"; exit 1; }
  read -r MAGIC MAC < <(head -n1 "$SRC")
  [ "$MAGIC" = "rwenc1" ] || { echo "암호화 형식이 아닙니다: $SRC"; exit 1; }
  C="$(mktemp)"; trap 'rm -f "$C"' EXIT
  tail -n +2 "$SRC" > "$C"
  GOT="$(openssl dgst -sha256 -hmac "$KEY:mac" -r < "$C" | cut -d' ' -f1)"
  [ "$GOT" = "$MAC" ] || { echo "✗ 위변조 검사 실패 (키가 다르거나 파일이 손상됨)"; exit 1; }
  BK="$KEY" openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BK -in "$C" -out "${SRC%.enc}"
  gzip -t "${SRC%.enc}"
  echo "✓ 위변조 검사·복호화 완료"
  SRC="${SRC%.enc}"
fi
gzip -t "$SRC"
[ -f "$SRC" ] || { echo "파일이 없습니다: $SRC"; exit 1; }

echo "▶ 복원할 백업:"
gunzip -c "$SRC" | docker compose exec -T api python -m rentwise.backup summary
if [ "$YES" != "--yes" ]; then
  read -r -p "현재 DB 의 앱 데이터를 이 백업으로 교체합니다. 계속할까요? [y/N] " a
  [ "$a" = "y" ] || { echo "취소"; exit 1; }
fi
docker compose exec -T api python -m rentwise.backup export | gzip -9 > "backups/pre-restore-$(date -u +%Y%m%dT%H%M%SZ).json.gz"
gunzip -c "$SRC" | docker compose exec -T api python -m rentwise.backup import | tail -n 3
echo "✓ 복원 완료 ($(( $(date +%s) - T0 ))초). 확인: curl -s http://127.0.0.1:8080/api/v1/version"
