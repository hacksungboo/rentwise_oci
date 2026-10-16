#!/usr/bin/env bash
# [비상용] team-4-1 에서 실행: 최신 main 을 받아 서버에서 직접(arm64 네이티브) 빌드하고 재기동한다.
# 평소에는 main 병합 시 CD(.github/workflows/cd.yml)가 GHCR 이미지로 자동 배포한다.
#   ./scripts/deploy.sh            # origin/main 최신
#   ./scripts/deploy.sh <commit>   # 특정 커밋으로 고정/롤백
set -euo pipefail
cd "$(dirname "$0")/.."              # infra/
REPO_ROOT="$(git rev-parse --show-toplevel)"
REF="${1:-origin/main}"

[ -f .env ] || { echo "infra/.env 가 없습니다. cp .env.example .env 후 값을 채우세요."; exit 1; }

echo "▶ 코드 갱신: $REF"
git -C "$REPO_ROOT" fetch --quiet origin
git -C "$REPO_ROOT" checkout --quiet --detach "$REF"
SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
export BUILD_SHA="$SHA" IMAGE_TAG="$SHA"

echo "▶ 이미지 빌드 (BUILD_SHA=$SHA)"
docker compose build --pull api web

echo "▶ 기동"
docker compose up -d
# 이후 직접 compose 를 실행해도 이 빌드로 뜨도록 기록 (로컬 빌드 이미지)
for kv in "IMAGE_TAG=$SHA" "BUILD_SHA=$SHA" "API_IMAGE=rentwise-api" "WEB_IMAGE=rentwise-web"; do
  k="${kv%%=*}"; v="${kv#*=}"
  if grep -q "^${k}=" .env; then sed -i "s|^${k}=.*|${k}=${v}|" .env; else echo "${k}=${v}" >> .env; fi
done

echo "▶ API 준비 대기 (첫 DB 기동은 3~5분 걸릴 수 있음)"
for i in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8080/api/v1/health/ready >/dev/null 2>&1; then
    echo "✓ 준비 완료"; curl -fsS http://127.0.0.1:8080/api/v1/version; echo
    echo "$(date -Is) $SHA local" >> .deploy-history
    exit 0
  fi
  sleep 5
done
echo "✗ 7분 안에 준비되지 않았습니다. ./scripts/check.sh 와 docker compose logs api db 를 확인하세요."
exit 1
