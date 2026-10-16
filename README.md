# rentwise

장비 렌탈 업체의 **요청 변경 후 재확정 병목**을 줄이는 운영 보드. Oracle TELOS Challenge 2026.

고객이 "회수를 오후 2시로 미뤄 주세요"라고 보내면, 원문에서 조건을 뽑아 사람이 확인하고, 장비·직원 일정에 미치는 연쇄 영향을 계산해 변경안을 보여주고, 책임자가 확정하면 Oracle DB 에 저장합니다.

- 서비스: https://rentwise.ccmall.shop (배포 후)
- 구성: Vue 3 · FastAPI · Oracle Database Free · Docker Compose · Cloudflare Tunnel · OCI 서울(aarch64)

## 문서

| 문서 | 내용 |
|---|---|
| [docs/A_WORK_SUMMARY_2026-10-17.md](docs/A_WORK_SUMMARY_2026-10-17.md) | A 작업 완료 내역·현재 연결 상태·일정 생성/최적화 범위 |
| [docs/INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md) | **인프라 전체 설계**: 네트워크·DB 분리·CI/CD·백업 보안·도쿄 DR·모니터링 · [아키텍처 그림](docs/architecture/rentwise-oci.png) |
| [docs/DEPLOY_GUIDE.md](docs/DEPLOY_GUIDE.md) | 서버 배포·점검·롤백 |
| [docs/CICD.md](docs/CICD.md) | main 병합 시 자동 배포, Secrets 설정 |
| [docs/DB_SPLIT.md](docs/DB_SPLIT.md) | DB 를 team-4-2 로 분리, 되돌리기 |
| [docs/TOKYO_DR.md](docs/TOKYO_DR.md) | 도쿄 리전 백업·DR (Terraform, 개인 프리티어) |
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

신규 단일 납품은 A의 `RealEngine(delivery_enabled=True)`에서 기존 B v1 형식으로 계산할 수 있다. 직원·동일 품목 장비를 배정하고 확정 직전에 신규 Job/PLANNED Rental/예약/준비 의존 생성분을 재검증한다. 기본 비활성이며 **B의 서버 ID·반납 정책 주입, 신규 작업 비교 표시, 확정 저장 연결이 필요하다.** [B 연결 문서](docs/handoffs/A_DELIVERY_CONNECTION.md)를 따른다. 기존 GPT 비용원장·회수 v2 경로는 유지한다.

당일 추가 요청의 A 실행 보호(TEL-054): 완료·진행 작업을 고정하고, 지난 미시작 작업은 상태 확인으로 차단합니다. B는 직원 실행 상태/운영 자원/revision 갱신과 v1·회수 v2 양쪽 실제 clock을 연결해야 합니다. [B 연결 안내](docs/handoffs/A_INTRADAY_CONNECTION.md).

선택적 native v1 회수 adapter도 함께 제공하지만, 현재 B 웹의 회수 지연은 기존 v2 bridge를 계속 사용합니다. [native adapter 인계](docs/handoffs/A_RECOVERY_CONNECTION.md). AI 입력 한도는 전체 UTF-8 bytes+256 ≤16000, 예약은 시도당 $0.0064입니다. [한도·예약 정책](docs/AI_REAL_MODE.md#4-비용).

변경안 검토의 **AI 설명 보기**는 변경 시간·담당·장비와 유지되는 약속을 한 번에 정리합니다. 설명 실패 시 계산 결과 요약을 표시하며 기존 확정 흐름을 유지합니다. 기존 모델 키/영속 예산을 사용하고 별도 DB 변경은 없습니다. [설명 동작·비용](docs/AI_REAL_MODE.md#8-변경안-ai-설명-tel-057).
