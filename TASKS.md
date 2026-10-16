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
