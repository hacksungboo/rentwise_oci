#!/usr/bin/env bash
# team-4-2 에서 한 번 실행: 1521 을 앱 서버(team-4-1) 사설 IP 에서만 허용
set -euo pipefail
cd "$(dirname "$0")"
APP_IP="$(grep -E '^APP_SERVER_IP=' .env 2>/dev/null | cut -d= -f2)"; APP_IP="${APP_IP:-10.0.0.198}"
sudo firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=${APP_IP}/32 port port=1521 protocol=tcp accept"
sudo firewall-cmd --reload
echo "✓ 1521 허용: ${APP_IP} 만"
sudo firewall-cmd --list-rich-rules
