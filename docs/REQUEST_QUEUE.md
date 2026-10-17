# 3건 접수·순차 처리 대기열 — TEL-062

2026-10-17 · base main58b7eb5 · 사용자 화면/API 구현 승인. 전체 최적화를 묶어서 수행하는 기능이 아니라 **함께 접수하고 접수 순서대로 검토·확정하는 기능**이다. B의 단일 요청/계획/확정 경로와 같은 엔진·비용원장·운영 표를 쓴다.

## 사용 방법

1. ADMIN 운영 보드의 **3건 순차 처리**에서 거래처/원문 3개를 입력하고 함께 접수한다. 배열 순서가 FIFO 순서다. 한 HTTP 트랜잭션에서 전부 저장하거나 전부 롤백한다. 별도 외부 메시지 수신기는 추가하지 않았다.
2. 첫 요청만 AI 해석한다. 조건을 사람이 확인·보정한 뒤 변경안을 계산한다. 초안은 운영 일정을 바꾸지 않는다.
3. **이 변경안으로 확정**하면 기존 B의 독립 검증/원자 저장으로 운영 revision이 1 증가하고 다음 요청 해석을 시작한다. 다음 변경안은 서버가 잠금 안에서 최신 current_plan_id/state_revision/snapshot을 읽어 계산한다. 묶음 접수 당시 revision으로 되돌리지 않는다.
4. 해석 오류는 해당 순서에서 멈춘다. 같은 접수 원문으로 명시적 재시도 또는 기존 작업을 골라 직접 조건 입력이 가능하다. 해결할 수 없으면 사유를 적고 보류한다. 변경안의 기존 보류 버튼도 다음 순서로 이동한다. 보류 자체는 운영 revision을 바꾸지 않는다.
5. 새로고침/재접속은 DB에 있는 현재 요청·사람 확인본·최신 초안을 복원한다. 페이지 열기/대기열 새로고침은 AI를 호출하지 않는다. 3건이 모두 확정·보류되면 완료이며, 각 결과는 구분해서 표시한다. 새 묶음 접수가 가능하다.

실시간 작업 시작/완료는 이번 범위 밖이다. 신규 납품·지원 업무 종류·탐색 한도는 기존 엔진의 범위를 그대로 따른다. 순서에 따라 결과가 달라질 수 있으며, 뒤 요청 때문에 이미 저장한 고객 조건을 자동 취소하지 않는다. 뒤 요청이 같은 작업을 명시적으로 다시 변경하면 새 사람 검토와 확정이 필요하다. 기존 직원/장비를 전체적으로 영구 고정하는 정책은 아니다.

## API (ADMIN 전용)

기존 `/api/v1` prefix. 공용 rental.intent/solver 계약은 변경하지 않았다.

| Method / 경로 | 입력 / 동작 |
|---|---|
| POST `/request-queues` | `{items:[{source_customer_id,text},...]}` 1~3건. UI는 3건. 선택적 `Idempotency-Key` 동일 body 재전송은 같은 접수 결과, 다른 body는409. 접수 순서 고정, 활성 묶음은 workspace당1개 |
| GET `/request-queues/latest` | `{queue:null 또는 대기열}`. 현재 또는 가장 최근 완료 묶음 복원 |
| GET `/request-queues/{id}` | `id,status,created_at,current_request_id,state_revision,items[]`. items에는 `position,state,request,hold_reason` |
| POST `/request-queues/{id}/interpret` | `{request_id,expected_request_revision}`. 선두만 해석. 이미 해석이 저장되었으면 기존 결과 반환(중복 유료 호출 방지) |
| POST `/request-queues/{id}/plan` | `{request_id,interpretation_revision}`. 사람 확인 필수. 클라이언트의 과거 state_revision 대신 서버의 최신 일정 사용 |
| POST `/request-queues/{id}/hold` | `{request_id,reason}`. 선두만 보류, 공백 사유 금지, 최대200자. 초안이 없어도 가능 |

사람 보정은 기존 PUT `/requests/{id}/interpretation`, 확정·변경안 보류는 기존 POST `/plans/{id}/confirm`·`hold` 사용. 해당 경로와 기존 POST `/plans`에도 FIFO/닫힌 요청/해석 진행 검사를 적용해 순서를 우회하지 못한다. 대기열 요청을 기존 `/requests/{id}/interpret`로 해석하면409 `QUEUE_ENDPOINT_REQUIRED`다. 비대기열 요청은 기존 경로를 유지한다.

409 주요 코드: `QUEUE_ALREADY_ACTIVE`, `QUEUE_OUT_OF_TURN`, `QUEUE_BUSY`, `QUEUE_LEASE_EXPIRED`, 기존 `STALE_PLAN`, `STALE_SNAPSHOT`, `STALE_INTERPRETATION`. 모델 실패는 기존502 오류와 실제 비용 기록을 유지한다. UNRESOLVED 계획은 확정되지 않는다.

## 동시성·복구

- Oracle은 기존 workspace SELECT FOR UPDATE, SQLite는 동일 workspace의 no-op UPDATE로 쓰기 잠금을 먼저 얻는다. 서로 다른 탭의 접수·계산·확정/보류가 순서와 revision을 검사한다.
- AI 해석은 짧은 트랜잭션에서120초 lease를 저장하고 연결을 닫은 뒤 호출한다. 그동안 같은 요청의 재해석/수정/계산/보류는409다. 반환 시 lease·선두·요청 revision을 다시 검사하고 저장한다. 프로세스가 사라지면 lease 만료 후 명시 재시도/수동처리가 가능하다. 오래 걸린 이전 응답은 폐기한다.
- 큐 worker/자동 확정/실패한 요청을 건너뛰는 재시도는 없다. 기존 interpreter의 내부 최대2시도 정책과 전체입력bytes+256≤16000 검사를 따른다. 모델별 예약·정산·공유 예산은 [AI 비용 정책](AI_REAL_MODE.md#4-비용)을 따른다. Terra 기준 시도당$0.064, 3건×2시도 최대예약 합계$0.384이며 실제 비용/사용 가능 잔액은 기존 원장이 결정한다. AI 설명은 기존 선택 버튼에서 별도 호출한다.
- 확정과 queue 진행은 같은 request.status를 기준으로 하므로 확정 트랜잭션이 롤백되면 선두도 이동하지 않는다. 단일 요청 화면 등에서 다른 일정이 확정되면 이전 초안은409로 거절되고 최신 일정으로 재계산해야 한다.
- 화면을 닫아도 저장한 접수/해석은 유지된다. 다음 요청의 자동 해석 시작은 열린 화면에서 확정·보류 성공 후에만 수행한다. 서버 백그라운드 작업은 없다. 실패를 반복 호출하거나 polling으로 과금하지 않는다.

## B 연결·스키마

새 환경변수/패키지/infra 수정은 없다. 화면·API가 함께 구현되어 별도 registry 플래그 연결도 필요 없다. B 소유 api/services/db/frontend 변경이므로 PR에서 B 리뷰가 필요하다.

DB schema_version=2: `rw_request_queues`, `rw_request_queue_items` 두 표만 추가. 기존 컬럼 변경/데이터 재초기화 없음. 기존 `init_schema`의 create_all이 표를 만들고 버전 기록을 추가한다. DB 계정은 기존과 같은 CREATE TABLE 권한이 필요하다. `/health/ready`는 최신 버전을 반환한다. 명시적 demo reset은 대기열도 초기화한다.

논리 백업은 두 표를 포함한다. v1 백업을 새 코드로 복원하면 빈 대기열+schema2로 올린다. v2 백업을 구버전 코드로 복원하는 역방향 호환은 제공하지 않는다. 운영 적용/Oracle 실기동은 이번 로컬 구현에서 하지 않았다.

## 검증·시연 조건과 알려진 한계

- B 개발 seed: FakeClient+실제 A/B API/SQLite로 회수14시 → 기존 AS1 10:15 → 다음날 AS2 14:15 순서로 사람이 검토·확정. r7→8→9→10, 다음 base_plan_id 연쇄, 앞 회수/준비/납품대체 및 AS 배정·시각·segment 보존, 초안 무저장·실제 Asset 불변을 검사한다. 이는 개발용 예시이며 C 평가 정답/일반 성공률이 아니다.
- busy-v1의 기존 `J-TRF1 VISIT_WINDOW` 오판은 TEL-063에서 출발/도착 창을 분리하는 기존 B bridge 계약에 맞춰 교정했다. 동일 무료 회귀는 **3건 확정 r7→10**과 앞선 변경·TRANSFER 시각 보존을 검사한다. 실제 불가능한 요청은 계속 미해결/확정 차단되며 전체 일정을 삭제하는 미리보기를 만들지 않는다. 과거 확정1/보류2 기록은 교정 전 결과다. [원인과 수정](DISPATCH_FALLBACK.md#busy-v1에서-전체-일정이-사라져-보인-원인-tel-063).
- 인수 대상 추가 시험: 후행 모든 쓰기 차단, 동시 접수 멱등/확정1회, lease 중복·만료, 실패/수동대체, 보류/새 묶음, 외부확정 후 stale/사람조건 변경 후 옛 초안 차단, 확정 저장 실패 롤백, reset/backup/schema1 업그레이드, 권한.
- 실제 OpenAI/Oracle/클라우드/모바일/다중 서버 인수는 별도다. FakeClient 시연을 실제 LLM 의미 품질로 확대하지 않는다. 기존 T17 수동 비교 기록은 이 새 기능으로 대체하지 않는다.


## TEL-066 — 해석 거절과 연결 오류 구분·복구

2026-10-17 운영 로그에서 첫 회수는 Terra 해석/확정 성공, 이후 신규 설치 두 건은 `AI_REVIEW_UNSUPPORTED`로 거절됨을 확인했다. 이 코드만으로 어떤 항목인지 알 수 없었지만 동일 조건의 FakeClient 회귀에서 `operations.0.rental_end_at` 질문이 현재 B 확인 화면의 편집 범위 밖이라 거절됨을 재현했다. 반납일 미정을 임의의 날짜나 무기한 승인으로 바꾸지 않는다. 실제 Terra/네트워크 오류가 아니라 유효한 추출 결과를 사람이 검토할 UI가 부족한 경우다. 운영 응답 본문 자체는 수집하지 않았으므로 캡처의 NETWORK로 바뀐 정확한 브라우저 예외까지 재현했다고 주장하지 않는다.

- `AI_REVIEW_UNSUPPORTED`는 HTTP **422**, `retryable=false`, `error.details.paths/review_version`을 반환한다. 기존 모델·통신 장애는502를 유지한다. 질문 삭제/자동승인/불완전 해석 저장 없음.
- 프런트가 실제 fetch 실패(NETWORK), HTTP502/504/524, 응답 수신 중단, 성공 응답의 잘못된 JSON, 클라이언트 예외를 구분한다. HTTP 상태·추적 ID를 보여주며 HTML 오류 본문은 노출하지 않는다.
- 다음 요청 자동 해석의 응답이 실패해도 바로 재호출하지 않는다. GET으로 큐를 다시 읽어 저장된 해석이 있으면 복원하고 오류를 해제한다. 결과가 없으면 검증된 현재 요청에 오류를 전달한다. 기존 업무 변경의 직접 입력·명시적 재시도/보류가 가능하다.
- 동일 화면에서 지원하지 않는 검토 오류가 확인되면 재해석 버튼을 막고 보류·별도 검토를 안내한다. 새로고침 후 실패 이력은 서버에 복원하는 별도 API가 없으므로 이 버튼 제한은 영속 정책이 아니다. 단순 조회 자체는 모델을 호출하지 않는다.
- GET도 실패하면 저장 여부가 불확실하므로 입력/보류를 숨기고 **저장 상태 다시 확인**을 제공한다. 재조회는 GET만 수행한다. 활성 해석 lease가 있으면 계속 대기하며 수동 우회하지 않는다.
- 선행 확정·보류와 최신 일정/revision, FIFO/lease/원자 확정은 그대로다. 신규 설치의 반납일/무기한 입력·확인 UI와 B 신규납품 자동배정 연결은 이번 오류 수정 범위 밖이다. 이 요청은 보류 후 별도로 검토해야 한다.

무료 시험은 실제 Vue 컴포넌트를 메모리 renderer로 실행하며 신규 DOM/브라우저 패키지를 추가하지 않는다. API HTML/JSON/연결8개, 큐 전환/복구6개, 기존 Markdown4개를 CI의 `npm test`로 실행한다. 백엔드에는 첫 요청 확정→둘째 반납일 미정 거절·보류→셋째 거절에도 첫 일정 보존/HTTP422·paths·추가조회 무과금 회귀를 추가했다. 실제 유료 호출·화면 수동 확인·운영 배포는 수행하지 않는다.
