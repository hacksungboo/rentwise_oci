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

기존 `ENGINE_MODE=real` 설정으로 `rentwise.engine.RealEngine()`을 사용한다. B 코드/DTO/DB 변경이나 추가 인자는 필요 없다. 기본 데모 시각은 기존 seed manifest의 clock_anchor다.

현재 v1 자동 적용 범위는 기존 업무의 직원 변경과 기존 방문창 안 A/S 시간 조정이다. 회수 지연·장비 대체·신규 작업은 B 저장 범위를 넘어 NEEDS_REVIEW로 반환한다. 직접 호출용 v2 core의 정상/지연 기능은 별도로 유지한다. 자연어 모델은 아직 연결되지 않아 interpret는 AI_NOT_CONFIGURED 오류를 반환하며, 자동 mock 대체는 하지 않는다. 사람 확인 입력 경로로 계산·확정 시험을 완료했다. 상세: [A 인수인계](docs/handoffs/A.md).
