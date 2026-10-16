# rentwise

장비 렌탈 업체의 **요청 변경 후 재확정 병목**을 줄이는 운영 보드. Oracle TELOS Challenge 2026.

고객이 "회수를 오후 2시로 미뤄 주세요"라고 보내면, 원문에서 조건을 뽑아 사람이 확인하고, 장비·직원 일정에 미치는 연쇄 영향을 계산해 변경안을 보여주고, 책임자가 확정하면 Oracle DB 에 저장합니다.

- 서비스: https://rentwise.ccmall.shop (배포 후)
- 구성: Vue 3 · FastAPI · Oracle Database Free · Docker Compose · Cloudflare Tunnel · OCI 서울(aarch64)

## 문서

| 문서 | 내용 |
|---|---|
| [docs/DEPLOY_GUIDE.md](docs/DEPLOY_GUIDE.md) | 서버 배포·점검·롤백 |
| [docs/CICD.md](docs/CICD.md) | main 병합 시 자동 배포, Secrets 설정 |
| [docs/DB_SPLIT.md](docs/DB_SPLIT.md) | DB 를 team-4-2 로 분리, 되돌리기 |
| [docs/AI_REAL_MODE.md](docs/AI_REAL_MODE.md) | real 모드(GPT 해석 + A 엔진) 켜기·확인·AI 호출 기록·비용 |
| [docs/CLOUDFLARE_TUNNEL.md](docs/CLOUDFLARE_TUNNEL.md) | 도메인 연결 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 구조, API, A·C 연동 지점, 명세와 다른 부분 |
| [docs/LOCAL_DEV.md](docs/LOCAL_DEV.md) | 로컬 실행 |
| [docs/OWNERSHIP.md](docs/OWNERSHIP.md) | 역할별 소유 경로 |
| [docs/BRANCH_STRATEGY.md](docs/BRANCH_STRATEGY.md) · [docs/COMMIT_CONVENTION.md](docs/COMMIT_CONVENTION.md) | 협업 규칙 |
| [docs/handoffs/](docs/handoffs/) | 역할별 진행·인수인계 |

## 빠른 시작

```bash
# 로컬
cd app/backend && pip install -r requirements-dev.txt && uvicorn rentwise.main:app --port 8000
cd app/frontend && npm install && npm run dev      # http://localhost:5173  (admin / rentwise2026)

# 서버 (team-4-1)
cd infra && cp .env.example .env && vi .env && ./scripts/deploy.sh && ./scripts/check.sh
```

## A 엔진 연결 상태

`ENGINE_MODE=real` 이면 GPT 해석(A) → 사람 확인 → 배정 계산(A) → 확정(B)으로 동작한다. 회수 지연은 A v2 core 를 B 가 직접 연결해 반납·준비·다음 납품(같은 모델 대체)까지 저장하고, 그 밖의 기존 작업 변경은 A v1 호환 엔진을 쓴다. 비용 장부·호출 기록·켜는 방법: [docs/AI_REAL_MODE.md](docs/AI_REAL_MODE.md), A 상세: [A 인수인계](docs/handoffs/A.md).
