#!/usr/bin/env bash
# 매시간 17분에 backup.sh 실행 (중복 등록 안 함). 기록: infra/backups/backup.log
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="$(pwd)"
command -v crontab >/dev/null || { echo "crontab 없음: sudo dnf install -y cronie && sudo systemctl enable --now crond"; exit 1; }
mkdir -p backups
LINE="17 * * * * cd $DIR && ./scripts/backup.sh >> $DIR/backups/backup.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'scripts/backup.sh' ; echo "$LINE" ) | crontab -
echo "✓ 등록: $LINE"
crontab -l | grep backup.sh
