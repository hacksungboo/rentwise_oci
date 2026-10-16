#!/usr/bin/env bash
# team-4-2 에서 한 번: 모니터링 포트를 앱 서버(team-4-1) 사설 IP 에서만 허용
#   3100 Loki push, 9090 Prometheus remote write  ← team-4-1 Alloy
#   3000 Grafana                                   ← team-4-1 cloudflared (터널)
set -euo pipefail
cd "$(dirname "$0")"
APP_IP="$( { grep -E '^APP_SERVER_IP=' .env 2>/dev/null || true; } | cut -d= -f2 | sed 's/[[:space:]]*#.*$//; s/[[:space:]]*$//')"; APP_IP="${APP_IP:-10.0.0.198}"
for p in 3000 3100 9090; do
  sudo firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=${APP_IP}/32 port port=${p} protocol=tcp accept"
done
sudo firewall-cmd --reload
echo "✓ 3000·3100·9090 허용: ${APP_IP} 만"
sudo firewall-cmd --list-rich-rules
