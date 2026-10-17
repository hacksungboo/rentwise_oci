#!/usr/bin/env bash
# 매시간 17분에 backup.sh 실행 (중복 등록 안 함). 기록: infra/backups/backup.log
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="$(pwd)"
command -v crontab >/dev/null || { echo "crontab 없음: sudo dnf install -y cronie && sudo systemctl enable --now crond"; exit 1; }
mkdir -p backups
LINE="17 * * * * cd $DIR && ./scripts/backup.sh >> $DIR/backups/backup.log 2>&1"
# 기존 crontab 이 없으면 crontab -l 이 실패한다(pipefail). 빈 목록으로 보고 계속한다.
CURRENT="$(crontab -l 2>/dev/null || true)"
{ printf '%s\n' "$CURRENT" | grep -v -e 'scripts/backup.sh' -e '^$' || true; echo "$LINE"; } | crontab -
echo "✓ 등록: $LINE"
crontab -l | grep backup.sh
