#!/usr/bin/env bash
# CD(GitHub Actions)가 SSH 로 호출: GHCR 의 커밋 SHA 이미지로 api/web 를 교체한다.
# 새 버전이 준비되지 않으면 직전 버전 이미지로 자동 롤백한다. DB 컨테이너·볼륨은 건드리지 않는다.
#   ./scripts/deploy-image.sh <커밋 SHA>
# 수동으로도 실행 가능 (사전에 docker login ghcr.io 필요할 수 있음)
set -euo pipefail
cd "$(dirname "$0")/.."              # infra/
TAG="${1:?커밋 SHA 를 인자로 넣으세요}"
[ -f .env ] || { echo "infra/.env 가 없습니다"; exit 1; }

export API_IMAGE="ghcr.io/hacksungboo/rentwise-api"
export WEB_IMAGE="ghcr.io/hacksungboo/rentwise-web"
PREV="$(grep ' ghcr$' .deploy-history 2>/dev/null | tail -n1 | awk '{print $2}' || true)"

switch_to() {
  IMAGE_TAG="$1" BUILD_SHA="$1" docker compose pull --quiet api web
  IMAGE_TAG="$1" BUILD_SHA="$1" docker compose up -d --no-build
}

wait_ready() {  # API 가 해당 SHA 로 응답하고 DB 까지 ready 인지
  for _ in $(seq 1 36); do
    if curl -fsS http://127.0.0.1:8080/api/v1/version 2>/dev/null | grep -q "\"build_sha\":\"$1\"" \
       && curl -fsS http://127.0.0.1:8080/api/v1/health/ready >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  return 1
}

echo "▶ 배포: $TAG (직전: ${PREV:-없음})"
switch_to "$TAG"
if wait_ready "$TAG"; then
  echo "$(date -Is) $TAG ghcr" >> .deploy-history
  echo "✓ 배포 완료"; curl -fsS http://127.0.0.1:8080/api/v1/version; echo
  docker image prune -f >/dev/null 2>&1 || true
  exit 0
fi

echo "✗ 새 버전이 3분 안에 준비되지 않았습니다"
docker compose logs --tail 40 api || true
if [ -n "$PREV" ] && [ "$PREV" != "$TAG" ]; then
  echo "↩ 직전 버전으로 롤백: $PREV"
  switch_to "$PREV"
  wait_ready "$PREV" && echo "✓ 롤백 완료 ($PREV)" || echo "✗ 롤백 후에도 준비되지 않음. 수동 확인 필요"
  echo "$(date -Is) $PREV ghcr rollback-from-$TAG" >> .deploy-history
fi
exit 1
