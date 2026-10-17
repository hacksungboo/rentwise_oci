# 아키텍처와 연동 지점

기준 문서: 노션 **일반 렌탈 운영 플랫폼 — MVP 실행 명세**, **공통 개발 계약**, 역할별 A·B·C 지시문.

## 구성

```
app/
├── backend/            FastAPI (Python 3.12)
│   └── rentwise/
│       ├── contracts/  공용 계약 v1 (B 소유, A·C 검토)  ← A·C도 여기서 import
│       ├── engine/     A 실제 엔진 (RealEngine)        ← A 소유
│       ├── dev_fakes/  mock EnginePort (B, 개발 전용)
│       ├── api/        HTTP 라우트, 세션, 오류 형식
│       ├── services/   요청·해석, 계획 생성·비교·확정, 운영 현황
│       └── db/         스키마(SQLAlchemy Core), seed 적재, snapshot 조회
├── frontend/           Vue 3 + TypeScript + Vite, nginx 로 서빙
└── fixtures/v1/        seed.json (지금은 B 임시본 → C 정식본으로 교체)
infra/                  docker-compose, .env.example, deploy/check/smoke/backup 스크립트
docs/                   협업·배포·아키텍처 문서
```

## 메인 시연 동선

| 화면 | 동작 | API |
|---|---|---|
| 로그인 | 데모 계정 (admin / e1~e3) | `POST /api/v1/sessions` |
| S1 운영 현황 | 직원별 타임라인, 창고 준비, 장비 재고(물리/가용 분리) | `GET /operations?date=`, `GET /reference` |
| S2 요청 해석 | 원문 입력 → 해석 → 근거 표시 → 확인 필요 항목 체크·수정 | `POST /requests`, `POST /requests/{id}/interpret`, `PUT /requests/{id}/interpretation` |
| S3 변경안 | 보드에 변경 전(점선)·후 표시, 연쇄 영향·이유, 확정/보류 | `POST /plans`, `GET /plans/{id}`, `POST /plans/{id}/confirm`, `POST /plans/{id}/hold` |
| 확정 후 | DB 재조회, 상태 버전 +1 | `GET /operations` |
| 시연 초기화 | seed 로 되돌림 (C 측정용) | `POST /admin/reset` |

공통: 오류 형식 `{error:{code,message,details,retryable},trace_id}`, 변경 요청은 `Idempotency-Key` 지원, 확정·해석은 기준 revision 필수. API 문서: 배포 후 `/api/docs`.

## A 엔진 연동 방법 (mock → real)

1. `app/backend/rentwise/engine/` 에 `RealEngine` 클래스를 만들고 `engine/__init__.py` 에서 export 합니다.
2. `rentwise.contracts.EnginePort` 의 4개 메서드를 같은 서명으로 구현합니다: `interpret`, `availability`, `solve`, `validate`.
3. 서버 `.env` 에서 `ENGINE_MODE=real` → `./scripts/deploy.sh`. API·화면 코드는 바꿀 필요 없습니다.
4. 테스트: `app/backend/tests/engine/` (A 소유). 메인 흐름 테스트는 `ENGINE_MODE=real pytest` 로도 돌릴 수 있게 유지해 주세요.

B가 엔진에 넘기는 값:
- `interpret`: 원문, 수신시각, 출처 거래처, 후보 거래처/품목, 해당 거래처의 기존 작업 요약(최대 15건, `customer_id` 포함)
- `solve`: 사람이 확인한 operations(RESCHEDULE 이면 기존 작업의 item/from/to/due/asset 을 명시적으로 상속), 전체 snapshot(현행 계획의 plan_items 포함), `input_hash`
- `validate`: 확정 트랜잭션 안에서 최신 snapshot + 변경안 전체

## C 데이터 연동 방법

- 지금 `fixtures/v1/seed.json` 은 B 가 `fixtures/dev/build_dev_seed.py` 로 만든 **임시 개발 seed** 입니다(명세 §8.2 회수 지연 산술 반영).
- C 가 정식 seed 를 만들면 같은 `seed.json` 형식(엔티티별 배열 + manifest)으로 교체하거나, CSV 묶음으로 낸 뒤 B 에게 변환을 요청해 주세요.
- 정답(gold)은 루트 `eval/` 에 둡니다. 서비스 이미지와 seed 에 들어가지 않습니다.

## 명세와 다르게 구현한 부분 (B 결정, 재검토 가능)

| 항목 | 명세 | 구현 | 이유 |
|---|---|---|---|
| 시각 저장 | `TIMESTAMP WITH TIME ZONE` | UTC 기준 `TIMESTAMP` + API 에서 +09:00 표시 | Oracle 드라이버별 시간대 바인딩 차이를 피하려고 |
| 마이그레이션 | 순번 SQL + schema_version | 기동 시 `create_all` + `rw_schema_version` | 해커톤 일정. 스키마 변경 시 추가형으로만 |
| seed 형식 | CSV/JSON 파일 묶음 | 단일 `seed.json` | 적재 단순화. C 정식 데이터 받으면 조정 |
| DB 배치 | 단일 서버 | 같음 (team-4-1) | |
| 이미지 | Actions → GHCR → SSH 배포 | 같음 (ARM 러너 네이티브 빌드, 실패 시 자동 롤백). 비상용으로 서버 직접 빌드(`deploy.sh`) 유지 | |

## 아직 안 한 것 (우선순위 낮음)

- S4 장비 상세 화면(API 는 `GET /assets/{id}` 있음), S5 직원 현장 완료 기록(ExecutionEvent)
- 영속 비용원장·BudgetPort는 현재 B에 구현되어 있음. 운영 Oracle/동시성 인수는 별도
- 계획 수정(PATCH)·재계산, 동시 확정 부하 시험, 백업 복구 리허설

## 당일 실행 상태 보호 — TEL-054

A `engine/execution.py`를 native v1/신규 납품과 B가 호출하는 v2 core의 검증에 공통 적용한다. 실행된 작업 불변, 과거 미시작 상태 확인, 신규·변경 출발의 현재시각/직원 이동, 진행 직원·장비 재사용 금지를 검사한다. `RealEngine.validate`도 매번 clock을 읽으며 공개 DTO/서명은 유지한다. B 이벤트 저장/UI는 미구현이고 실행 상태·물리 상태·revision의 원자 갱신, 일반/v2 양쪽 실제 clock 연결이 필요하다. 상세 정책·보수적 한계·인수 절차: [A_INTRADAY_CONNECTION.md](handoffs/A_INTRADAY_CONNECTION.md).

### 신규 납품 — B v1 opt-in (TEL-053)

`engine/delivery.py`는 기존 CREATE DELIVERY1건/장비1대를 제한 탐색한다. 기존 v1 NormalizedOperation의 extra 필드에 B가 allocation(Job/Rental/Reservation/Dependency ID)과 확인한 return_policy를 넣고 hash를 계산해야 한다. RealEngine의 `delivery_enabled=True`에서 기존 SolverResult로 전체 후보와 예약 CREATE를 반환한다. 기본 동작은 그대로다.

서버 내부 `prepare_delivery_confirmation(snapshot, operations, candidate_items, reservation_changes, *, request_id, input_hash)`는 최신 상태와 승인 조건으로 생성분을 다시 계산·검증한다. B는 초안에 신규 Job 표시 메타데이터만 저장하고 운영 생성은 하지 않으며, 기존 잠금/revision/멱등 confirm에서 Job/Rental/예약/필요 의존과 계획 교체를 원자 저장한다. 이 연결은 아직 B production에 적용되지 않았다. 기본 2인자 validate는 신규 작업을 계속 거부한다. [연결과 인수 명세](handoffs/A_DELIVERY_CONNECTION.md).

최신 main03e7913의 B 비용원장·회수 v2 bridge는 별도 경로로 유지한다. 신규 납품을 기존 `_apply_v2`로 보내지 않는다. 새로운 공용 타입/DB 스키마/외부 HTTP 필드/의존성은 없다.


선택적 native v1 회수 adapter도 같은 RealEngine에 통합했다. 현재 B의 v2 회수 연결을 대체하거나 자동 활성화하지 않는다. [native 인계](handoffs/A_RECOVERY_CONNECTION.md). AI 한도/예약은 [실행 안내](AI_REAL_MODE.md#4-비용)를 따른다.

## 변경안 AI 설명 — TEL-057

`PlanReview.vue` → `POST /plans/{id}/explanation`(ADMIN, revision/hash/state guard) → `services/explanations.py`가 저장된 plan_view를 읽고 DB 연결을 닫음 → A `OpenAIPlanExplainer`가 사실 ID의 순서만 Structured Outputs로 정리 → 서버가 검증된 한국어 문장 렌더 → 최신 상태/근거 재검사 → 화면 표시. 공용 EnginePort/계산 결과 DTO와 DB 스키마는 변경하지 않았다. AI 비용/기록만 기존 B LedgerBudget/ai_calls에 저장한다. 설명 실패는 SYSTEM 요약이며 기존 계획 생성/확정 흐름을 차단하지 않는다. 준비 시각의 영향 경로에서 시작을 완료로 표기하던 표시를 제거하고 RETURN_PREP를 한국어로 표시한다. 구체적 비용/운영/한계는 [실행 안내](AI_REAL_MODE.md#8-변경안-ai-설명-tel-057) 참조.

### 3건 순차 처리 대기열 (TEL-062)

`RequestQueue.vue` → ADMIN `/request-queues` → `services/request_queue.py` → 기존 requests/사람확인/plans/confirm. schema2의 `rw_request_queues`와 `rw_request_queue_items`가 접수 순서·120초 해석 lease·보류 사유를 저장하고, 기존 request.status로 선두/완료를 결정한다. 모델 대기 중 DB 연결 없음; 완료 시 선두/token/revision 재검사. 모든 기존 관련 쓰기 경로에도 FIFO를 적용하며, 다음 계산은 workspace 잠금 아래 최신 snapshot을 사용한다. 확정 저장이 롤백되면 선두도 유지된다. SQLite는 쓰기잠금 획득, Oracle은 기존 FOR UPDATE. background worker는 없고 사람 확정·보류 후 열린 화면이 다음 해석을 호출한다. 상세: [REQUEST_QUEUE.md](REQUEST_QUEUE.md).

### 인력 부족 대안과 실패 미리보기 (TEL-063/064)

기존 DELIVERY 변경도 v2 bridge로 연결한다. `dispatch_fallback`은 내부 인력 계획 실패와 별도 staff calendar 검사를 함께 확인한 뒤 배송별 전용 퀵 또는 당일 회수의 다음 근무일/PREP 대안을 계산한다. 독립 validator를 통과한 완전 후보만 READY가 된다. PlanView의 선택 필드 fallbacks/preview_employees로 책임자가 실제 호출 필요 여부·회수 날짜·새 기한을 검토한다. 퀵은 확정할 때 기존 employees/shifts 표에 함께 저장하며 원자 롤백/revision 보호를 유지한다. 실제 업체 가용성·호출·요금은 연결하지 않았다. 상세 [DISPATCH_FALLBACK.md](DISPATCH_FALLBACK.md).

미해결 결과는 후보가 없다는 뜻이다. API는 삭제 diff를 만들지 않고 Vue는 현재 계획을 유지한다. busy-v1 TRANSFER 출발·도착 창 검증을 기존 B 변환 규칙과 일치시켰다. DB 스키마와 C 운영 seed는 변경하지 않았다.

### Terra·설명 Markdown·고객 안내 (TEL-065)

`ai_policy.py`가 기본모델Terra/명시Luna 호환 가격과 모델별 정산 버전을 관리한다. 요청 해석·변경안 설명은 같은 모델 설정을 사용하고 B LedgerBudget은 전역 모델 이름 대신 호출 가격 버전으로 정산한다. 총예산/DB 스키마는 그대로다.

설명은 AI의 사실ID정렬→서버 facts 렌더를 유지하면서 presentation_version/markdown을 추가하고 기존 plain 필드를 보존한다. Vue MarkdownText는 제목/목록/강조/인용만 Vue보간으로 렌더해 rawHTML·링크 실행을 하지 않는다. 표시를 위한 추가 모델 호출은 없다.

확정 후 CustomerMessage가 ADMIN GET /plans/{id}/customer-message로 현재 확정 계획과 수신 고객의 직접 대상 작업을 읽는다. 짧은 workspace 잠금 아래 revision·HUMAN해석·수신 범위를 검증하고 고객 방문 SERVICE 시각으로 SYSTEM초안을 생성한다. 복사 직전 재조회하며 메시지 저장·외부발송·모델호출은 없다. 단일/큐 공통으로 최근 확정 ID를 상위 App에 전달하고 화면 수명 안에서 표시한다. 이전 계획/다른 고객 혼합은 차단, 미호출 퀵은 업체확인필요 안내다. [운영·비용](AI_REAL_MODE.md#4-비용-tel-065-terra-기본값).
