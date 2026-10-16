# 작업 현황

| ID | 담당 | 브랜치 | 상태 | 소유 경로 | 수용 기준 |
|---|---|---|---|---|---|
| TEL-046 | A / Codex | codex/a-engine | Review | app/backend/rentwise/engine/, app/backend/tests/engine/, docs/handoffs/A.md | 독립 v2 core 및 최초 PR 제출 |
| TEL-048 | A / Codex | codex/a-engine | Review | engine/, tests/engine/, A 인수인계·작업 기록 | B v1 변경 없이 계산·확정·재조회, 지원 밖 작업 무저장 차단 |
| TEL-049 | A / Codex | codex/a-ai-intent | Review | engine/, tests/engine/, A 인수인계·작업 기록 | OpenAI→intent v1, 근거/ID/날짜·모호함 검증, 예산/모델 오류, B 사람 확인 후 계산 |
| TEL-050 | A / Codex | codex/a-ai-intent | Review | engine/, tests/engine/, docs/handoffs/A*.md, 작업 기록 | B 변경 없이 AS 기존 기한 확인·입력 불가 확인항목 명시 오류, B 연결 인계 |
| TEL-051 | A / Codex | codex/a-ai-intent | Review | A 변경 11파일·작업/인수인계 | 최신 main 기준 선별 commit/push 및 새 AI PR 제출 |

## TEL-051 — AI 변경 PR 제출

사용자가 TEL-049/050 결과의 PR 제출을 승인했다. 기존 PR #2는 이미 병합됐으므로 최신 main1cd1186에서 새 codex/a-ai-intent를 만들었다. 작업 11파일의 checksum이 전환 전후 동일함을 확인했고 B 코드/설정과 C 데이터는 보존했다. 계획: 최종 backend/typecheck/build·비밀값/범위 검사 → 선별 커밋·push → main 대상 새 PR → CI 상태 확인. main 병합·배포는 하지 않는다. B 영속 비용원장·registry 주입이 필수 후속이며 실제 모델 증거/대역 회귀/운영 인수를 구분해 PR에 기록한다.

제출 전 PASS: main1cd1186 기반 backend186개, frontend vue-tsc --noEmit / vite build36modules, diff 공백·문서 링크·11파일 소유 범위·실제 키 불포함. 배포/Oracle/브라우저/운영 원장 인수 및 새 유료 호출은 SKIPPED. PR head의 CI는 GitHub Checks에서 별도 확인한다.

## TEL-050 — 최신 B 화면에 맞춘 A 확인 초안

사용자 결정: B 수정은 최소화하고 A에서 흡수 가능한 부분부터 수정한다. 기존 A 로컬 AI 구현을 보존한다.
계획: B 기존 AS의 누락 기한을 원문 추출 이후 결정적으로 제안하고 사람 확인 질문 유지 → B가 입력할 수 없는 확인 항목은 원자적으로 AI_REVIEW_UNSUPPORTED 반환 → B 원장/주입/수동 경로·확장 UI 연결 문서 별도 작성 → 최신 main+A 복사본에서 API/DB 및 UI 스크립트 회귀.
수용: 명시 기한/모호함/대상 선택은 덮어쓰지 않음, 제안은 유일한 기존 AS·원래 창 안 요청에만 적용, 근거 조작 없음, 사람 확인 전 계산422/확인 후 기존 확정 경로, 부분 operation 제거·확인 질문 삭제·미지원 자동 배정 없음. B 코드/공유 DTO/DB/UI/infra/C 데이터 무변경.
위험: 원장 미연결은 A가 해결할 운영 소유 범위가 아니다. 현재 B 화면의 고객/대여기간/operations 확인 편집 한계를 오류로 알리며 모든 네 업무 화면 지원 완료로 주장하지 않는다. 실제 모델 재호출은 필요하지 않은 후처리 변경이므로 기본 시험은 provider 대역과 저장된 합성 응답을 사용한다.

결과: A의 B 연결부에 `b_review.py`를 추가했다. 검증된 해석 이후에만 기존 AS 기한을 확인용 제안하고, 기존 품목 참조를 B의 소요시간 추천에 표시한다. 명시값/모호함/대상 불명/원래 창 밖에는 제안을 하지 않는다. 입력 불가능한 질문은 삭제하지 않고 AI_REVIEW_UNSUPPORTED와 전체 payload=null로 차단한다. 독립 OpenAIInterpreter의 네 업무 추출은 그대로다. B 필수 원장·registry 주입·환경과 후속 수동/확장 화면·seed 검수는 docs/handoffs/A_AI_CONNECTION.md로 분리했다.
PASS canonical 및 최신 main9f27e56+A 임시 결합 backend pytest186개(기존160+새26), B 무수정 RequestPanel 반응형 함수에서 17시 추천 미노출/40분 종료/기한 체크 전false·후true, 기존 API 미확인422→확인→READY→confirm→DB 기한11시 유지. PASS 최신 B typecheck/build(Vite36 modules), diff/소유 범위 검사. NOT CONFIGURED 원격 scripts/check.sh(없음). SKIPPED 실제 브라우저/Oracle/배포/운영 비용원장/추가 유료 모델 호출. B/C 파일·공유 계약 변경 및 commit/push/배포 없음.

## TEL-049 — OpenAI 자연어 해석

사용자 요청: 자연어 요청을 기존 B v1 형식으로 변환한다. 실제 검증은 gpt-5.6-luna, 이번 총 $0.05 이내로 승인(2026-10-16). 키는 저장소 외부 환경변수로만 사용한다.
계획: 기존 공용 JSON Schema로 Responses Structured Outputs 호출 → 타입·참조·원문 근거·KST 상대 날짜 검사 → 누락 확인 질문 → B 기존 해석/사람 확인/solver 경로 시험. 모델 호출과 비용 예약은 주입 경계로 두고 순수 계산은 보존한다. SDK/런타임 의존성·B DTO/service/DB/UI는 추가·변경하지 않는다.
수용 기준: 네 업무/모호함/누락/상대 날짜, 잘못된 JSON·근거·ID·거부·시간초과·429/5xx·예산 차단, 전체 회귀, 실제 최소 모델 응답과 B API→사람 확인→계산 증거. C gold/eval은 사용하지 않는다.
위험: 기존 비용 계약의 영속 BudgetPort는 B 책임이며 현재 원격에는 없다. A가 임의 메모리 원장을 운영용으로 대신하지 않는다. 운영 무인자 연결은 비용 adapter 미설정 시 명시 오류로 차단하며 실제 검증의 제한 예산 대역과 구분한다. 키/모델만 설정하고 운영 AI 연결 완료로 주장하지 않는다. 신규 업무 등 solver 기존 제한은 유지한다.

TEL-049 결과: Responses strict Structured Outputs + 공유 intent 스키마, 결정적 후검증·확인 질문, 모델/usage/attempt metadata, 프로세스 동시1·토큰/예산 예약·제한 재시도를 구현했다. B API에서 원문→실제 모델→사람 확인→solver→confirm→격리 SQLite 재조회로 AS10:15 변경을 확인했다. final prompt v1.1 상대 날짜·모호한2시까지 실제3사례 PASS. 개발 총7호출의 누적 최악 예약 $0.0308로 승인 $0.05 이내이며 청구 확정액은 아니다. B 서비스/DTO/DB/UI/infra 및 C 데이터 무변경, 새 의존성 없음. 운영은 B 영속 BudgetPort 주입이 남아 있다.

검증: PASS `cd app/backend && .venv/bin/python -m pytest -q` 160개(기존107 + 해석53), 외부 anyio deprecation1. PASS `git diff --check`, 변경 범위·비밀값 검사. NOT CONFIGURED 원격 `sh scripts/check.sh`(없음, exit127); SKIPPED infra/scripts/check.sh(배포 환경/Docker 필요), frontend 재빌드(변경 없음), Oracle/브라우저/클라우드/C 독립 인수. 실제 API 프로브는 합성 요청·격리 DB·시험 비용 adapter이며 운영 비용원장 인수는 아니다. 아직 commit/push/배포하지 않았다. 세부 재현/연결은 docs/handoffs/A.md.

## TEL-046 이식 계획 및 위험

1. origin/main의 경로와 pytest 구조에 A 엔진을 이식한다.
2. B v1 계약을 유지하고 공용 contracts/v2에 v2 스키마·DTO·정규화·hash를 추가한다. 공용 경로는 B 소유자 리뷰 후 병합한다.
3. A 행동 회귀와 기존 B pytest, frontend typecheck/build를 실행하고 결과를 인수인계에 기록한다.
4. 최신 main에 맞춘 codex/a-engine을 push하고 PR을 연다.

위험: B 서비스의 v1 snapshot/확정 저장 경로는 v2 전체 후보와 호환되지 않는다. RealEngine/AI 해석·서비스 연결과 C 독립 인수는 이 PR에서 완료했다고 주장하지 않는다. C 정답·eval·기존 미커밋 작업은 옮기지 않는다.

## TEL-046 검증 결과 (2026-10-16)

PASS: backend pytest 74개(A 67 + B 7), 정상/지연 직접 호출 + 독립 VALID, frontend typecheck/build.
프런트 로컬 런타임은 Node24.19.0/npm10.9.2이며 CI Node22 실행은 별도 확인 필요.
NOT CONFIGURED: scripts/check.sh(원격 저장소에 없음). SKIPPED: compose 검사(Docker CLI 없음), 화면/서버/실제 모델/C 독립 인수.
B 소유 contracts/v2 추가 리뷰 및 실제 API/DB 연결은 미완료다. 상세: docs/handoffs/A.md.

## TEL-047 — B 호환 경계 검토 (TEL-048로 대체)

B v1과 A v2의 입출력·확정 경계를 검토했다. 최종 구현은 아래 TEL-048을 따른다.
B 서비스에 context/DTO/저장 훅 추가를 요청하던 로컬 초안은 채택하지 않았다.

## TEL-048 — B 수정 없는 v1 EnginePort 채택 (TEL-047 대체)

- Owner A/Codex, codex/a-engine, Review. 소유: engine/, tests/engine/, docs/handoffs/A.md 및 이 작업 기록.
- 사용자 결정: B v1에 맞춘다. B DTO/service/DB/seed/프런트/registry 변경 없이 RealEngine()의 네 v1 서명으로 동작해야 한다. 추가 context·추가 결과 DTO·metadata 주입 요구는 제거한다.
- 범위: B native 필드/nullable rental_id/TRANSFER semantics 그대로 검사, B 설정의 demo clock 사용(없으면 서버 시각), 물리/기간 재고 및 제한 탐색. B가 저장할 수 있는 기존 업무 직원 변경·기존 창 내 AS 시간 변경만 자동 확정 후보로 제공. 신규 작업·개체 대체·회수/납품/TRANSFER/PREP 실행시각 변경·조건 확대는 NEEDS_REVIEW. 직접 v2 core의 원래 지원은 유지한다.
- 신뢰 경계: B의 사람 확인/revision/잠금 guard를 계속 사용한다. v1 validate는 전달된 전체 일정·기존 조건·자원·예약 검사를 수행하며 v2 전체 후보/확인 이력 검증을 주장하지 않는다. 모델은 별도, 미설정은 명시 오류.
- 계획: native v1 검사/가용성 → 제한 solver → 무인자 facade → B 실제 seed/API/DB confirm 및 재시작 후 검증 → 전체 회귀/문서.
- 수용 기준: exact B DTO JSON 왕복, 실제 B seed availability, 두 인자 validate, B 코드 불변 API create/confirm/requery 성공(지원 범위), 회수 지연/장비 대체 무저장 차단, malformed/time/skill/break/travel/booking/frozen 회귀.

TEL-048 결과: 기존 DTO와 두 인자 validate만 사용하는 native v1 RealEngine으로 전환했다. 추가 결과 DTO/context/metadata 주입·B 저장 훅 요구는 제거했다. 직접 v2 core와67개 시험은 유지한다. B 원본 seed의 nullable 대여 연결은 v1대로 허용하고 레코드를 생성하지 않는다. 원본 J-AS2/E1의 휴식 침범은 감지하며 직원 E2 변경으로 실제 B API/SQLite create→confirm→requery를 통과했다. 기존 창 안 AS 시각 조정도 동일 경로로 통과했다. 초안 무변경·멱등/중복409·새 엔진 재검증·Rental/Reservation/Dependency/Asset 불변 확인.

PASS `cd app/backend && .venv/bin/python -m pytest -q`:107 tests(v2 67+v1 33+B7), 외부 anyio deprecation1. PASS diff 공백/문서 링크, B 소유 코드/DTO/seed 무변경 검사. NOT CONFIGURED scripts/check.sh(없음). SKIPPED 프런트/infra 재빌드(변경 없음), 화면/Oracle/모델/C gold. Review 상태이며 codex/a-engine / PR #2에서 검토한다. 배포는 미실행이다.

커밋 전 최종 검사: PASS backend pytest107개, PASS frontend npm run build(Vite30 modules, 로컬 Node24.19.0/npm10.9.2). B 코드/DTO/DB/seed/프런트/infra는 변경하지 않았다. GitHub CI 결과는 PR 최신 head에서 별도로 확인한다.

## TEL-056 — 밀린 A 변경 통합·commit/push/PR (In Progress)

Owner A/Codex, branch feat/a-engine-updates, latest main9666202. 사용자 요청으로 TEL-052 회수 native adapter·TEL-053 신규 납품·TEL-054 당일 실행 보호·TEL-055 AI 입력 한도를 새 integration checkout에 통합한다. 원본 dirty checkout 세 곳은 checksum으로 보존한다. 소유 engine/, tests/engine/, A 인계/README/ARCHITECTURE/AI_REAL_MODE와 작업 기록; B services/DB/contracts/프런트/infra·C seed/gold는 제외한다.
순서: native recovery와 delivery의 공용 v1/Facade를 결합하고 회수 prepare에도 현재시각 보호 적용 → 전체 backend/B HTTP/C busy FakeClient 및 frontend checks → 기능/AI입력/연결문서 범위별 커밋 → remote push/main PR/CI 확인. B의 기존 v2 회수 bridge는 그대로 유지하고 native adapter를 자동 활성화하지 않는다. PR·push는 승인됐고 main 병합/배포/유료 호출은 범위 밖이다.


## TEL-052 — B v1 회수 지연 복구

2026-10-17 사용자 요청: 웹에서 회수 지연 복구안을 계산·확정하도록 A 담당부터 구현하고 B 환경을 최대한 유지한다. 기준 main9ab0c25, 새 codex/a-pickup-recovery. B/C/공유 계약·DB 코드는 수정하지 않는다.
계획: native B v1 snapshot/Result로 기존 단일 개체 PICKUP→연결 PREP→기존 DELIVERY 유지/동일 품목 대체를 탐색한다. 기존 실제 상태/다른 고객 약속은 보존하고 직원·이동·휴식·재고·예약을 검증한다. 확정용 순수 prepare_confirmation이 최신 snapshot+저장 operations/후보/예약 delta를 재검증하고 Job/Rental/Dependency 변경분을 만든다. B는 기존 잠금·revision·멱등 안에서 이 변경분을 원자 저장한다. 별도 서버/도메인 DTO/숨은 context/cache는 추가하지 않는다.
수용: 14시 회수→14:30 창고→15시 준비, P02로 기존 정오 납품 유지, 불가 직원/준비전 재사용/예약·기한·고정 작업/부분안 차단, 입력 불변·JSON 왕복·새 엔진 확정 재검증·위조 delta 차단, 실제 B API 초안/기존 confirm 안전 차단 및 격리 DB 저장 delta 재조회. 1000후보/2초, 자동 영향3작업, 명시 직원 override는 별도 적용·재검증한다.
위험: 기존 2인자 validate에는 승인된 변경 조건/예약 delta가 없어 회수 지연을 허용하면 안전 경계가 사라진다. 기본 RealEngine은 현재 제한을 유지하고 B가 recovery_enabled=True와 prepare_confirmation 저장 훅을 연결할 때만 활성화한다. 신규 대여/다개체/TRANSFER/다중 지연은 이번 범위 밖. 기존 seed AS2 휴식 충돌은 원본 그대로 감지하며 시험의 명시 E2 override와 구분한다. LLM/비용원장은 별도 미연결이며 이번 계산에 모델 호출은 없다.

결과: `engine/recovery.py`, RealEngine opt-in/순수 prepare_confirmation, native v1 검증의 제한된 내부 투영 경로를 구현했다. 14시 회수/E2→15시 준비, P02로 기존 정오 납품 유지 및 정확한 Job/Rental/Dependency/예약 교체를 산출한다. 늦은 회수라도 원래 개체 재사용이 가능하면 우선한다. 입력 불변/JSON 왕복/새 엔진·B 부여 ID 허용, 준비·이동·달력·예약·고정 작업/위조 후보·delta·누락 연결/탐색 제한을 검증한다. SUPERSEDED 예약은 옛 개체 이력을 보존하고 ACTIVE 대여/예약 개체 일치는 엄격히 유지한다. 원본 B API 초안 READY·비교 성공, 미수정 confirm422 무저장, 참고 SQLite adapter 저장 후 새 엔진 VALID/availability OK 및 예외 전체 롤백을 확인했다.

검증 PASS: `cd app/backend && .venv/bin/python -m pytest -q` **242개** (기존186+신규56), 외부 anyio deprecation1. PASS diff 공백·A 소유 범위/공용 DTO·B production/C 불변 확인. NOT CONFIGURED `sh scripts/check.sh` (원격 파일 없음, exit127); 원본 작업공간의 동일 명령은 bootstrap/이전 A69개 PASS이며 새 앱242개와 별도다. SKIPPED frontend/infra 재빌드(소스/HTTP DTO/의존성 불변), 실제 브라우저/Oracle/운영 잠금·동시성/배포/새 유료 LLM 호출. B 실제 confirm 성공은 미완료다.

연결 명세: [A_RECOVERY_CONNECTION.md](docs/handoffs/A_RECOVERY_CONNECTION.md). B는 registry 플래그와 기존 confirm의 A prepare+Job/Rental/Dependency/예약 원자 저장을 연결해야 한다. AS2 seed 휴식 충돌/현재 UI override 미전달과 AI 영속 비용원장은 별도 미완료다. B 코드·공용 계약·DB schema·UI·infra/C seed 변경, commit/push/PR/배포/다른 채팅 전송 없음.


## TEL-053 — B v1 신규 납품 자동 배정

2026-10-17 사용자 요청. 최신 main03e7913 (B real AI/회수 v2 연결 PR #11 포함) 기준 별도 worktree `/private/tmp/rentwise-a-delivery-20261017`에서 구현한다. 기존 `/private/tmp/rentwise-a-engine-20261016`의 미커밋 TEL-052 회수 복구 작업은 보존한다. 기준 backend190개 PASS. B의 영속 비용원장/회수 bridge와 검수 seed를 사용하며 이 경로를 교체하지 않는다.

계획: 기존 B v1 NormalizedOperation의 CREATE DELIVERY 1건/장비1대를 처리한다. B가 신규 Job/Rental/Reservation/조건부 준비 의존 ID와 FIXED 또는 OPEN_ENDED 정책을 서버 내부 allocation/return_policy로 주입한 뒤 canonical hash를 계산한다. 공용 DTO/schema/HTTP 변경 없음. 원문·AI에서 ID나 확인 상태를 신뢰하지 않는다. opt-in `delivery_enabled=True`에서 직원/동일 품목 장비/5분 방문 후보를 탐색하고 기존 약속·실제 상태를 보존하며 전체 계획을 검사한다. 준비에 의존한 재사용은 기존 회수·준비 및 예약 release가 명시된 경우만 허용한다. 최대1000후보/2초, 명시 직원 override≤3. 준비·회수 작업 신설/다개체/다중 요청/직접 현장 간 경로 최적화는 범위 밖이다.

순수 prepare_delivery_confirmation은 최신 snapshot+저장 operations+전체 후보/예약 delta+request_id/input_hash에서 Job/Rental/Reservation/Dependency 생성분과 기존 직원 변경용 Job revision 변경분을 재계산한다. 기본 2인자 validate는 신규 작업을 계속 거부한다. B의 잠금/revision/멱등 가드는 유지하고 모든 생성분을 같은 confirm 트랜잭션에서 저장한다. FIXED 대여 종료도 회수/준비 release가 없으므로 예약은 무기한 보수 점유한다. PLANNED 대여만 생성하고 Asset 물리/실제 대여 시각은 변경하지 않는다.

수용: 실제 B seed의 준비 완료 장비/자격 직원 배정, 선호 직원 불가 시 대체, 조건부 준비 후 재사용/준비전·미래 예약·휴식·근무·방문창·기한 차단, 빈 후보 실패와 정확한 상한 보고. JSON 왕복/다른 엔진/B 발급 plan ID/입력 불변, 신규 생성 데이터와 delta 위조·ID 충돌·기존 약속 변경 차단. 기존 B 초안 저장·조회 한계/미수정 confirm 안전 차단과 참고 격리 DB 원자 저장·재조회·롤백 시험. 전체 backend 회귀와 root check를 실행하고 브라우저/Oracle/B 실제 연결 미완료는 구분한다.

위험/인계: B plan_view는 아직 운영 jobs 테이블에 없는 신규 후보의 업무종류·현장을 알 수 없어 A가 재계산한 job_creates를 초안 메타데이터로 저장·표시해야 한다. 기본 비활성을 유지하고 B 연결 필수 지점을 별도 A_DELIVERY_CONNECTION.md로 문서화한다. B production/공용 타입/DB schema/UI/infra/C 데이터는 수정하지 않는다. 새 유료 호출·commit/push/PR/배포는 이번 요청 범위가 아니다.

결과: `engine/delivery.py`와 RealEngine의 `delivery_enabled`/`prepare_delivery_confirmation`, native v1 내부 `new_jobs` 검사 옵션을 구현했다. 기존 실제 B seed에서 PR-A1대15시 납품→P02/E1, 14:40 출고~15:35 복귀, 기존 약속 보존. 준비 완료 또는 명시된 기존 회수/PREP/release에 의존한 장비를 선택하고 Job/PLANNED Rental/예약/필요 의존 생성분을 순수 재검증한다. 기본 비활성/기존 validate의 신규 작업 차단은 유지한다. 대여 종료일도 회수/준비가 없으면 무기한 예약이다.

PASS 최종 backend `cd app/backend && /private/tmp/rentwise-a-engine-20261016/app/backend/.venv/bin/python -m pytest -q` **256개**(기준190+신규66), 외부 anyio deprecation1. 원래 venv의 Python만 재사용하며 새 worktree의 conftest/소스를 사용한다. PASS JSON/새 엔진/B 발급 행 ID/입력 불변, 정상·조건부·하드 제약/정책·미래 예약·위조/새 충돌·상한. B HTTP 초안은 시험용 정규화 binding으로201 READY/저장·조회되며, 신규 kind/site=null인 현 표시 한계와 미수정 confirm422/무저장을 검증했다. 참고 SQLite 쓰기 adapter로 READY/조건부 각각 전 생성분+기존 finish 커밋→새 엔진 VALID/가용 재조회, Job 생성 직후/finish 후 예외→전 상태 롤백 PASS.

NOT CONFIGURED remote `sh scripts/check.sh` (파일 없음, exit127). PASS root 동명 명령 bootstrap/이전 A69개(새 앱256개와 별도). SKIPPED frontend/infra 재빌드(해당 소스/외부 DTO/의존성 불변), 브라우저/Oracle·운영 동시성/배포/새 유료 호출. B production/공유 계약/DB schema/UI/infra/C 무변경. B 실제 웹 confirm200 및 C 독립 인수는 미완료다.

연결 문서 [A_DELIVERY_CONNECTION.md](docs/handoffs/A_DELIVERY_CONNECTION.md): B 서버 ID/명시 반납 정책 주입+flag, 초안 Job 표시 metadata/plan_view overlay, 최신 HUMAN 해석 검사+기존 confirm의 순수 prepare와 원자 INSERT/finish 연결. 최신 B의 비용원장·회수 bridge는 구현돼 있으므로 이들을 다시 만들 필요 없다. 현재 반납 미정 UI/확인 경로는 별도 후속이다. 이전 TEL-052 작업은 원래 checkout에 보존했고 이번 branch로 복사·합치지 않았다. commit/push/PR/배포/타 채팅 전송 없음.


## TEL-054 — 당일 실행 상태를 보존하는 잔여 일정 계산 (In Progress)

Owner A/Codex, branch codex/a-new-delivery, main03e7913 + 미커밋 TEL-053 보존. 소유 engine/, tests/engine/, A 인계 문서와 본 작업 기록. B service/DB/UI/공용 DTO/seed는 수정하지 않는다.
사용자 전제: B가 직원별 작업 시작·완료 상태를 갱신한다. 수용: 완료/진행/실패 행 불변, 지난 미시작 작업은 상태 확인으로 차단, 미래 변경/신규 배정만 허용, 진행 직원/장비의 종료를 추정하지 않음, 계산 후 시간 경과·실행 상태 변경을 확정 재검증에서 거부, 최신 B v2 회수 경로에도 적용. 기존 약속과 실제 상태 불변 및 전체 회귀.
계획: 공통 순수 실행 보호 → v1 solve/validate/availability 및 delivery prepare 연결 → v2 solve/validator 연결 → 상태·현재시각·직원 이동·확정 경쟁 회귀 → B 이벤트/clock/revision 연결 문서와 검증 기록.
위험/정책: 상태만으로 진행 종료/실패 위치/완료 순서를 알 수 없다. 진행 직원에 신규·변경 업무를 추가하지 않으며 완료는 복귀 포함 전체 PlanItem 종료를 뜻한다. 완료 순서는 추정하지 않고 가능한 완료 지점 모두에서 현재시각 이후 이동 가능한지 보수적으로 확인한다. 실패 직원 위치는 확인 필요로 둔다. 실제 위치 추적/진행 종료 예상/전체 일정 최적화는 범위 밖. seed clock은 호환 보존하고 B가 모든 경로에 실제 서버 clock을 연결해야 한다.
검증 예정: 기존 CI backend pytest 전체 및 새 당일 시나리오/확정 재검증, git diff --check, root sh scripts/check.sh. 원격 scripts/check.sh는 미구성, UI/Oracle/실행 이벤트 운영 인수는 B 연결 전 미완료.

TEL-054 결과 — Review(A 구현/로컬 검증 완료, B 실행 이벤트 연결 대기).
공통 execution 보호를 v1 solve/validate/availability, TEL-053 delivery solve/prepare, v2 solve/validate/availability에 연결했다. 상태 기반 이력 불변·지난 미시작 작업 확인·진행 직원/장비 보호·현재시각 이후 출발/이동·확정 시 fresh clock을 검증한다. 기존 public DTO/B production/DB/UI/C 데이터 불변. 보수적 위치/미시작 지연 한계는 A_INTRADAY_CONNECTION에 기록했다.
PASS 최종 `cd app/backend && /private/tmp/rentwise-a-engine-20261016/app/backend/.venv/bin/python -m pytest -q`: **290개**(기존256+당일34), 외부 anyio deprecation1. 새 시험은 오전 이력 보존/다른 직원 배정/확정 시 상태·시간 변경/과거 ASSIGNED/현재 이동·완료 순서/진행 장비/v2 회귀와 기존 B HTTP AS·회수 confirm422/SQLite 전 상태 무저장을 포함한다. 실행 이벤트 자체는 테스트 snapshot/기존 status 컬럼으로 재현했다. 중간 실패는 바뀐 정책·버전 기대값과 합성 fixture(휴식/DTO copy/대여 enum/스키마)를 수정한 뒤 최종 전체 PASS했다.
PASS root sh scripts/check.sh(bootstrap+기존 A69, 새 앱290과 별도), git diff --check, A 소유17파일/로컬 링크/비밀값 패턴 검사. NOT CONFIGURED 원격 sh scripts/check.sh(없음,exit127), backend lint/type/build 별도 명령. SKIPPED frontend/infra 재빌드(소스 불변), 실제 직원 이벤트 API/UI·Oracle 동시성·배포·유료 호출.
원격 최종 main9666202를 fetch/대조했다. 기준03e7913 이후 추가는 도쿄 DR Terraform/CI/문서뿐이고 app diff는 없다. 브랜치의 기존 TEL-053 작업을 유지했으며 원격 main을 로컬 변경 위에 덮어쓰지 않았다. B 연결: docs/handoffs/A_INTRADAY_CONNECTION.md. commit/push/PR/배포/다른 채팅 전송 없음.


## TEL-055 — AI 해석 입력 한도와 비용 예약 정합성 (In Progress)

Owner A/Codex, branch codex/a-ai-input-limit, base main03e7913, checkout /private/tmp/rentwise-a-input-limit-20261017. 기존 TEL-053/054 미커밋 작업은 다른 checkout에 보존한다. 소유 engine/interpret.py, tests/engine/, docs/handoffs/A.md·A_AI_CONNECTION.md·docs/AI_REAL_MODE.md(사용자 명시 요청), 작업 기록. B services/DB·C gold/분류는 수정하거나 사용하지 않는다.
계획: UTF-8 전체 body+256 한도를16000으로 상향하고 동일 상수를 사용하는 Decimal 예약식(입력1.25배+출력2000)을 검증 → 38/120거래처·정확경계·초과·최대usage/재시도/잔액 시험 → C busy infra seed는 환경변수로만 읽는 opt-in 격리 SQLite 실모드 FakeClient 해석/사람확인/계획/확정 시험 → 전체 회귀와 요청 문서 갱신.
정책: 기존 모델/단가 PRICE_VERSION와 실제 프롬프트 PROMPT_VERSION은 변경하지 않는다. 예약은 $0.0064/시도, 두 시도 $0.0128. 240회×2시도 최대 예약 $3.072(모두 예약 보유 가정)로 계산하며 청구액/운영 승인액으로 표현하지 않는다. 120곳은 대표 크기 시험이며 긴 이름/15개 작업 등 모든 조합 통과를 보장하지 않는다. 토큰 tokenizer/API 호출은 추가하지 않고 기존 byte≥token 보수 정책+framing256을 유지한다. 유료 호출·commit/push 없음.

TEL-055 결과 — Review. INPUT_LIMIT16000/여유256·출력2000, 기존 PRICE/PROMPT 유지. 같은 상수를 쓰는 예약식으로 $0.0064/시도·최대2시도 $0.0128, 240회×2=$3.072 정합성 확인. 요청의 $6.14 산술은 문서에서 정정했다. 신규 tests/engine/test_input_limit.py13개 및 기존 기대값/요청 문서2개와 A_AI_CONNECTION의 예전 예약 수치를 갱신했다.
PASS 최종 backend(명시 C busy seed, FakeClient)203개=기존190+신규13/anyio warning1. C seed 실제 B API 해석200→사람확인→계획201 READY→확정200/재조회, byte 검사8272, 입력/seed/실제 Asset 불변, 실제 B 최대정산=예약0.0064. PASS root sh scripts/check.sh bootstrap+이전 A69, diff공백·B services/DB/contracts/fixtures 무변경. NOT CONFIGURED 원격 scripts/check.sh exit127/backend 별도 lint/type/build. SKIPPED FE/infra(소스 불변), 실제 유료 호출·Oracle·브라우저·T17 실측. 상세 A 인계 TEL-055. commit/push/PR/배포/메시지 전송 없음.

## TEL-056 통합 결과 (최신 상태)

최신 main9666202 위에서 TEL-052/053/054/055 전체를 통합했다. B v2 회수는 그대로이며 native 회수는 opt-in, 신규 납품은 B 생성/표시/확정 연결 대기다. 회수 prepare에도 fresh clock/상태 보호를 적용하고 양 플래그 동시 사용/혼합 요청 차단3개 회귀를 추가했다. 원본 checkout3곳의 파일 checksum을 보존했다. 앞선 task의 미커밋/미병합 기록은 당시 상태이며 이 제출로 대체한다.
PASS 통합 backend362개=기준190+회수56+납품66+당일37+한도13(명시 C busy seed/FakeClient, anyio warning1), 프런트 configured typecheck/build36modules. npm 실행파일은 현재 PATH에 없어 번들 Node로 package.json의 vue-tsc --noEmit / vite build를 직접 실행했다. 의존성은 기존 node_modules를 symlink로 재사용한 뒤 링크를 제거했다. B services/DB/contracts/FE/infra/C 소스 diff0. 실제 유료호출·운영 Oracle·브라우저/실행 이벤트·동시성/배포는 SKIPPED. 원격 scripts/check.sh 없음 NOT CONFIGURED, root check는 별도 증거.
커밋: 7f8dcf0 feat(engine): support intraday rental planning; b4145dd fix(engine): raise AI input bound with safe reserve. 문서 커밋 후 feat/a-engine-updates를 push/main 대상 PR을 생성한다. 사용자 승인 범위는 commit/push/PR이며 main 병합/배포는 하지 않는다.

TEL-056 제출 전 추가 PASS: root sh scripts/check.sh 구성/문서/셸+기존A69(앱362와 별도), C seed 미지정 조건에서 통합1개 SKIPPED 확인, diff/소유25파일·문서 링크·비밀값 패턴·원본 dirty파일checksum 동일. B production/공유 계약/프런트/infra/C diff0. 문서에는 과거 미연결 기록과 현재 B v2 회수/비용원장 연결을 구분했다.

## TEL-057 — 변경안 AI 설명과 화면·API (In Progress)

Owner Codex(A 통합), branch feat/a-plan-explanation, mainaa58564(PR13 병합). 사용자가 화면·API 연결까지 명시 승인하여 이번 task에 한해 engine/tests + B api/services/frontend 연결을 순차 통합한다. 기존 공용 contracts/DB schema/C 데이터/gold는 변경하지 않는다. plan-feature→implement-feature→verify-change.
목표: 변경안 검토 상단에서 한 번 누르면 계산된 변경/이유/유지 약속을 한국어로 보여준다. AI는 서버가 검증·생성한 사실 ID의 중요도/순서만 정리하고 숫자/직원/시각·확정 여부를 지어내지 못하도록 서버가 문장을 렌더한다. 현재 변경안ID/revision/input_hash/state_revision에 묶고 계산/확정 상태를 변경하지 않는다. 준비 시작/완료는 실제 PREP segment에서 구분한다. 입력 원문/전체 고객목록은 보내지 않는다.
순서: 순수 사실/기본 설명→기존 Responses transport/BudgetPort/동시lock를 재사용하는 선택적 AI 정리→DB연결을 닫은 후 호출/호출 후 최신상태 재검사/원장기록 API→버튼·로딩·기본설명/오류·늦은응답 무시 UI→FakeClient/SQLite/회귀·프런트검증/문서. 모델gpt-5.6-luna/기존가격·예산 유지, 출력1000/전체bytes+256≤16000, 1회시도 $0.0052예약. 실제 유료 호출/commit/push는 이번 작업에서 하지 않는다.
수용: 14시회수→14:30준비시작/15시완료→P02정오납품유지를 근거대로 설명, 모델의 미확인ID/누락/중복·다른문장 차단, 실패도 기본설명/확정동선유지, 오래된/보류/확정안·권한검사·AI대기중새상태차단/운영무저장, 기존원장정산/unknown유지, 전체회귀/프런트type/build/화면QA. 실제 AI 의미정확도·Oracle동시성·배포는 미검증으로 구분한다.

TEL-057 결과 — Review/구현·로컬 검증 완료. 사용자 명시 승인으로 engine + B API/services/frontend를 연결했다. 새 ADMIN POST /plans/{id}/explanation은 READY/revision/hash/state/근거를 검사하고 모델 대기 중 DB연결 없이 기존 영속 원장/기록을 사용한다. PlanReview 버튼·로딩·실패 SYSTEM요약·유지 약속·늦은응답 무시, 준비시각 오표시/RETURN_PREP 라벨/배지 줄바꿈을 정리했다. 공용 contracts/DB schema/C/infra 무변경.
PASS 최종 `RENTWISE_BUSY_SEED=/absolute/path/to/seed_busy.json python -m pytest -q app/backend/tests`390개(기존362+새28: 엔진18/API10), 외부anyio경고1. PASS configured frontend vue-tsc --noEmit/vite build36modules(기존의존성/번들Node), git diff --check 및14파일 링크/공백/비밀값 패턴. 실제 B LedgerBudget 최대usage reserved=settled0.0052, 모델 대기 시 pool.checkedout0/운영snapshot·plans·workspace·audit 불변, stale/closed/권한·경쟁409/timeout후확정200 회귀 포함.
PASS 로컬 IAB: 격리SQLite+FakeClient로 로그인→요청해석→사람확인→계산→AI설명보기. 준비14:30~15/대체P02/정오약속·김현우유지 표시, 캡처 /private/tmp/rentwise-plan-explanation.png. 유료 호출 없음. SKIPPED 실제 유료모델/운영Oracle·동시성/모바일viewport/배포. 원격scripts/check.sh 및backend별도lint/type/build는NOT CONFIGURED. commit/push/PR은이번기능에서수행하지않았다. 검증서버/임시의존성symlink는정리한다.

TEL-057 제출: 사용자 commit/push/PR 지시에 따라 최신 origin/main8f22d41 위로 rebase 완료(충돌 없음). main의 백업 기능/시험1개를 포함한 전체 backend391 PASS, frontend typecheck/build36modules PASS. 기존390 시험에서 코드 변경 없이 최신 main 통합을 검증했다. root check PASS와 QA 증거 유지, 임시 의존성 링크 제거. feat/a-plan-explanation을 main 대상 PR로 제출하며 B 소유 API/service/test/frontend 경로의 리뷰 필요 사항을 본문에 명시한다. main 병합/배포/실제 유료 호출은 수행하지 않는다.
