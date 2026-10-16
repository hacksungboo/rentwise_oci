# A 인수인계 — TEL-050: B 화면 호환 / OpenAI 해석

2026-10-16 · A/Codex · codex/a-ai-intent · TEL-049/050 Review · TEL-051 PR 제출
B v1을 기본 연결 계약으로 사용한다. 독립 v2 core의 최초 커밋은 fa2cdeb이며 최신 동작은 PR #2 head를 기준으로 검토한다.

## 연결 방법: B 코드 변경 없음

```python
from rentwise.engine import RealEngine
engine = RealEngine()
# B의 기존 서명 그대로
engine.interpret(interpretation_input)
engine.availability(availability_input)
engine.solve(solver_input)
engine.validate(snapshot, complete_plan_items)
```

기존 registry/ENGINE_MODE=real을 그대로 사용할 수 있다. 계산 함수에는 추가 context/결과 DTO/DB 컬럼이 없다.
TEL-049부터 OpenAI 해석에는 서버 비용원장 주입 `RealEngine(budget=budget_adapter)`가 필요하다(아래 참조).
기존 B Pydantic DTO만 반환하며 `segments`, `sha256:` hash, solve 이후 계획/행 ID 발급도 유지한다.
result_json에 숨은 후보·확인 토큰을 넣거나 캐시/DB 조회로 context를 복구하지 않는다.
서로 다른 RealEngine 인스턴스·JSON 왕복·프로세스 재생성에도 동일한 v1 입력으로 검증한다.
B services/DB/DTO/registry/mock/프런트/seed/infra/.github는 수정하지 않았다.

설정 시각: 기존 B settings.auto_seed=true이고 seed가 있으면 manifest.clock_anchor를 읽는다.
그 외에는 서버 UTC 시각을 사용한다. 잘못된 manifest 시각은 DATA_MISSING이다.
생성자에서 설정만 읽으며 계산/검증 함수의 DB·HTTP·상태 쓰기는 없다. 시험에서는 as_of를 명시 주입할 수 있다.

## 자동 적용 가능한 범위

- 기존 업무의 직원 변경. 업무 종류/장비/현장/실행 구간은 보존한다.
- 기존 방문창과 기한 안에서 기존 AS 시간 조정. B가 저장하는 window_start/end/due_at만 변경한다.
- 최대 영향3개·1000선택·2000ms cooperative 탐색. 반환 전체 일정에 v1 독립 검증을 적용한다.
- 늦은 회수/납품/TRANSFER/PREP 시간 변경, 장비 대체, 신규 Job/Rental, 조건 확대는 NEEDS_REVIEW.
  실패/미지원 결과에는 candidate_items/reservation_changes=[]로 적용할 부분안을 남기지 않는다.
- 새 자산 준비/예약/Rental/Dependency 변경을 요구하는 결과는 내보내지 않는다.
  따라서 기존 B 확정 트랜잭션이 저장하지 않는 값이 남는 문제를 피한다.

**회수 지연→대체 장비로 정오 납품 유지 시연은 B v1 자동 적용 범위에서 제외된다.**
직접 `rentwise.engine.solve/validate/availability` 함수로 호출하는 원래 v2 core는 그대로 유지한다.
v2는 B의 기본 EnginePort가 아니며 별도 계약이다. 제한을 풀려면 B의 저장 기능 확장이 필요하다.

## v1 검증의 책임과 한계

직원 자격/근무/휴식/중복/이동/복귀, 수량/품목/위치/준비, 방문창/기한,
작업 누락·고정 작업 변경, 기존 예약 중복·명시 준비 release, 의존 순서/순환을 검사한다.
B v1의 null rental_id를 허용하고 없는 Rental/후속 점유를 생성하지 않는다.
TRANSFER는 B의 기존 단일 서비스 시간을 양쪽 stop 각각에, 방문창을 양쪽에 적용하며 그 실행 구간은 변경하지 않는다.

B가 사람 확인/권한/해석 revision/workspace 잠금/state revision/멱등을 관리하는 기존 경계를 따른다.
v1 validate에는 승인 이력/변경 operation/전체 Rental·Dependency 후보가 전달되지 않으므로,
**v2 전체 후보의 승인·확정 상태 검사와 동일하다고 주장하지 않는다.**
일정 제약은 기존 snapshot 조건으로 다시 검사하고, 변경 가능한 종류 자체를 B 저장 범위로 제한한다.

## 가용성과 실제 B seed

무인자 availability는 기존 AvailabilityInput만 받는다. 물리 합계와 기간별 ready/conditional/unavailable을 분리한다.
예약 경계로 기간을 분할하고, 유효한 회수→준비 release에만 조건부 가용을 부여한다.
오늘 자정 요청은 clock_anchor부터 계산하며 과거 하루 전체는 DATA_MISSING이다.
기존 계획 제약 위반은 관련 장비를 가용 후보에서 제외한다. 구조 결손은 DATA_MISSING이다.

현재 B seed에서 J-AS2/E1의14시 AS는13:35 이동이13~14시 휴식과 겹친다.
기존 mock은 놓쳤지만 v1 실제 검증은 EMPLOYEE_BREAK/EMPLOYEE_TRAVEL_GAP을 보고한다.
이 직원을 E2로 바꾸는 후보는 실제 계산·확정 가능하다. seed를 고쳐 통과시키지 않았다.
기존 납품 예약3건의 rental_id=null은 B 계약대로 허용한다.
기존 TRANSFER의 목적지 대여/예약이 없다는 점은 그대로 남는 v1 모델 한계이며 전체 대여 인수 완료를 뜻하지 않는다.

## AI 상태

TEL-048 당시의 미연결 상태는 아래 TEL-049로 갱신한다. interpret의 B v1 서명과 결과는 유지한다.

## 검증 결과

- PASS `cd app/backend && .venv/bin/python -m pytest -q`: **107 tests**(기존 v2 67 + v1 33 + B7), 외부 anyio deprecation warning1.
- PASS B 원본 seed 그대로 물리12대 가용성 조회, E1 휴식 충돌 감지, E2 담당자 변경 후보.
- PASS B 실제 API/격리 SQLite: 사람 확인 → 직원 변경 및 AS 시간 변경(2사례) → READY 초안 →
  초안 시 운영 상태 불변 → 기존 두 인자 validate → 기존 B confirm200 → 재전송 멱등 →
  재조회 state_revision8/직원·AS창 일치 → 새 엔진으로 VALID → 중복 확정409.
  Rental/Reservation/Dependency/Asset은 전후 동일함을 확인했다.
- PASS exact B SolverResult JSON 재파싱(추가 필드 없음), 무인자 registry 실제 주입, 변조/창 확대/미지원 작업·해시·이동 결손 차단.
- PASS `git diff --check`, 문서 링크, B 소유 코드/DTO/seed 무변경 확인.
- NOT CONFIGURED `sh scripts/check.sh`: 원격 main에 파일 없음(실행 exit127).
- SKIPPED 프런트·infra 재빌드(해당 코드 변경 없음), 실제 화면/Oracle/클라우드/모델/C 독립 gold.
- 최신 main79faa96의 smoke 수정도 반영했다. main 병합·배포는 하지 않는다.

파일: `engine/compat.py` 무인자 진입점, `engine/v1.py` B native 계산/검증/가용성,
`tests/engine/test_compat.py` 경계·실제 B API 회귀. 별도 v2 core/계약은 기존 경로에 남긴다.

추가 PASS: B 실제 API에서 원문 회수 지연을 사람 확인 후 전달해 UNRESOLVED/NEEDS_REVIEW 초안, confirm422 PLAN_NOT_READY 및 운영 snapshot 전후 불변을 확인했다.

커밋 전 최종 검사: PASS backend pytest107개, PASS frontend npm run build(Vite30 modules, 로컬 Node24.19.0/npm10.9.2). B 코드/DTO/DB/seed/프런트/infra는 변경하지 않았다. GitHub CI 결과는 PR 최신 head에서 별도로 확인한다.

## TEL-049 — 자연어 → OpenAI → B intent v1

사용자 승인: OpenAI 사용, 이번 실제 검증은 gpt-5.6-luna / 총 $0.05 이내.
API 키는 작업 루트의 외부 `.env`에서 **검증 프로세스만** 읽었다. 저장소에 복사하거나 출력하지 않았다.
새 SDK/의존성, B 코드/DTO/DB/UI/infra, C fixture/gold 변경은 없다. 작업 위치는
`/private/tmp/rentwise-a-engine-20261016`, 기존 PR에 올라간 기능과 이번 미커밋 변경을 구분한다.

### 실제 동작

1. B의 InterpretationInput에서 원문·접수시각·고객/품목 후보·관련 업무 최대15개만 전달한다.
   existing_jobs는 허용한 요약 필드만 사용한다. 연락처·전체 snapshot·gold는 보내지 않는다.
2. Responses API `text.format=json_schema`, strict=true에 **B의 기존 JSON Schema 파일**을 사용한다.
   모델 gpt-5.6-luna, reasoning=none, prompt `rental-extract-v1.1`, store=false, 외부 도구 없음.
3. 반환값을 같은 공용 Pydantic 타입으로 파싱하고 필수 nullable 키/여분 키/중복 JSON 키를 검사한다.
   후보에 없는 ID, 기존 업무와 다른 품목/장비/고객, 원문에 없는 근거, offset 없는 날짜,
   상대 날짜 불일치·역전된 방문창을 차단한다. 근거의 의미 전체를 코드로 증명한다는 뜻은 아니다.
4. 누락은 null/UNKNOWN과 확인 질문으로 남긴다. 동명이인·여러 기존 업무·오전/오후 없는 시각은
   선택을 유보한다. 상대 날짜는 received_at을 KST로 변환한 날짜 기준이며 서버 오늘과 독립이다.
5. `origin=AI`로 저장된 조건은 B의 기존 사람 확인 PUT 이전에는 계산할 수 없다.
   사람 확인을 거친 조건을 기존 solver가 사용한다. AI가 직원/장비 배정·약속 승인·운영 저장을 수행하지 않는다.

예: `오늘 J-AS1 정수기 AS를 오전 10시 15분부터 오전 10시 55분까지로 변경하고 오전 11시까지 완료해 주세요.`
→ RESCHEDULE/AS/J-AS1, window_start=2026-10-16T10:15:00+09:00,
window_end=10:55, due_at=11:00, quantity=null, priority_hint=UNKNOWN + 원문 근거.
RESCHEDULE 수량·대여종료 null은 미언급으로 보고 기존 값을 보존하도록 **A v1 solver만** 보완했다.
명시적인 수량/대여조건 변경은 여전히 자동 적용하지 않는다. solver version `rental-solver-b-v1-2`.
납품/회수/AS/TRANSFER 해석은 같은 형식이지만 자동 일정 적용 범위는 기존 TEL-048과 같다.

### B 연결: 비용원장 필수

```python
from rentwise.engine import RealEngine

# 기존 B 단일 주입 지점에서, 서버의 영속·원자적 비용 adapter를 주입
engine = RealEngine(budget=budget_adapter)
# 기존 engine.interpret(inp), solve/validate/availability 서명 유지
```

환경변수는 서버의 `OPENAI_API_KEY`, 선택 `OPENAI_MODEL=gpt-5.6-luna`다.
상위 폴더를 탐색하거나 `.env`를 import 시 자동 로드하지 않는다. uvicorn 실행 환경/컨테이너에 전달해야 한다.
기존 compose는 OPENAI_API_KEY 전달이 이미 있다. 기본 모델은 luna이며 임의 모델 fallback은 없다.
다른 모델은 가격/상한 정책 검토 후 PRICES에 등록해야 한다. 런타임 의존성 추가는 없다.

기존 팀 계약의 `BudgetPort`는 `engine/interpret.py`의 구조적 Protocol이다(도메인 DTO 복제 아님).
- `reserve(attempt_key, max_cost_usd: Decimal) -> reservation_id`, 부족 시 BudgetExceeded 또는 BUDGET_EXCEEDED.
- `settle(reservation_id, usage: contracts.Usage, price_version)`.
- `mark_unknown(reservation_id, reason)`; usage 없는 오류/시간초과는 예약을 해제하지 않는다.

B는 총잔액·카테고리 한도·동일 키 멱등·정산 원자성을 영속 저장소로 보장해야 한다.
동일 request/revision 재호출도 별도 실제 시도이므로 별도 invocation 키로 예약한다. 앱 응답 캐시는 없다.
현재 원격에는 이 B adapter가 없으므로 **키와 ENGINE_MODE만 설정해 운영 AI가 바로 활성화되지는 않는다.**
무인자 엔진은 키 없음 AI_NOT_CONFIGURED, 키 있고 비용원장 없음 AI_BUDGET_NOT_CONFIGURED로 호출 전에 차단한다.
테스트의 FakeBudget과 실제 검증의 제한된 ProbeBudget은 운영 원장이 아니며 서버에 사용하면 안 된다.
이 경계를 없애기 위해 B 서비스/DB를 임의 수정하거나 메모리 원장을 운영용으로 대체하지 않았다.

가격 버전 `openai-standard-2026-10-16`: Luna 1M tokens당 input $0.20 / cached $0.02 / output $1.20.
cache-write 1.25배를 고려해 입력8000/출력2000 기준 **시도당 $0.0044 상한**을 먼저 예약한다.
공용 Usage에는 cache_write_tokens가 없으므로 B 정산도 미캐시 입력을 1.25배로 잡으면 보수적 상한을 유지한다.
원문2000자, JSON/스키마/프롬프트 전체 UTF-8 bytes+256 ≤8000의 보수적 입력 제한, 출력2000 tokens.
이 byte 제한은 실제 tokenizer보다 먼저 거절할 수 있다. 동시 AI1은 프로세스 단위이며 다중 worker 전체 제한은 B 필요.
HTTP timeout20초, 전체45초 내 재시도 판단, 일시429/5xx만 최대1회. 시간초과/스키마/거부/incomplete 자동 재시도 없음.
usage 없는 시도가 있으면 최종 call.usage를 부분 합계로 꾸미지 않고 null로 둔다. 각 시도 정산은 원장에 남긴다.
API 원문 오류/키/stack trace를 결과에 싣지 않는다. B는 기존대로 해석 오류를 HTTP502로 내보낸다.

### TEL-049 검증

- PASS 실제 OpenAI 최종 prompt v1.1 3사례: 위 AS 조건 추출, KST 접수일 기준 내일14시,
  `2시`의 오전/오후·날짜 확인 질문. 각각 모델 usage 및 provider_call_id를 수신했다.
- PASS **실제 모델 + B HTTP + 격리 SQLite**: interpret200 → 사람 확인200 → plan201 READY → confirm200 →
  DB의 J-AS1 시작10:15 일치. 기존 seed AS2 휴식 충돌 해결은 사람이 명시한 E2 override를 사용했다.
  AI가 E2를 배정했다고 주장하지 않는다. 테스트 프로세스의 주입이며 운영 registry/비용원장 검증은 아니다.
- 초기 prompt v1.0 정상 AS 2건은 후검증에서 차단됐고 확보한 합성 응답에서 원문 근거 말줄임표/근거 없는 기본 우선순위를 확인했다.
  프롬프트를 v1.1로 수정했으며 후검증을 느슨하게 만들어 통과시키지 않았다.
- 실제 개발 호출 총7회(최종3 + 초기4), 자동 재시도0, usage7건 수신 및 시험 adapter의 settle7회.
  누적 최악 예약 **$0.0308** < 승인 $0.05. 청구 확정액으로 표현하지 않는다.
  로컬 합성 시험 기록 `/private/tmp/rentwise-openai-probe-report.json`; 키/헤더 없음.
- PASS `cd app/backend && .venv/bin/python -m pytest -q`:160개(기존107 + 해석53), anyio deprecation1.
  PASS diff 공백/소유 범위/비밀값 검사. NOT CONFIGURED `sh scripts/check.sh`(원격 파일 없음, exit127).
  SKIPPED 배포용 infra/scripts/check.sh 및 frontend 재빌드(변경 없음).
- SKIPPED 운영 Oracle/배포/브라우저, C 독립 gold/평가. 자연어 의미 정확도 전체 평가를 완료한 것은 아니다.

참고(2026-10-16 확인): [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Luna 모델·단가](https://developers.openai.com/api/docs/models/gpt-5.6-luna).
새 파일: `engine/interpret.py` 모델/비용 경계, `engine/intent_checks.py` 결정적 후검증,
`tests/engine/test_interpret.py` 대역·오류·B 통합 시험. 이번 구현은 commit/push/배포하지 않았다.

## TEL-050 — B 변경 최소화

사용자 지시: A에서 흡수할 부분을 수정하고 B 연결 작업을 별도로 정리한다.
최신 main `9f27e56`(DB 분리 PR #7 병합 포함)의 계약/화면을 기준으로 했다.
현재 작업 branch HEAD는 e0e8c9a이며 main을 작업 파일 위에 덮어쓰지 않았다. 최신 main archive와 A 파일을 결합한 임시 트리에서 별도 검증했다.

### 변경

- `engine/b_review.py` / `compat.py`: RealEngine.interpret가 검증된 해석을 B 기존 확인 폼에 맞춰 준비한다.
  독립 OpenAIInterpreter의 원문 추출 결과는 변경하지 않는다. 입출력은 기존 B v1 타입 그대로다.
- 원문에 새 완료 기한이 없는 기존 AS 요청은 기존 기한을 **확인 초안**에 제시한다.
  유일한 대상 업무/고객이 맞고, 새 시작·명시 종료가 원래 방문창/기한 안에 들어올 때만 적용한다.
  명시 기한·모호한 기한·기한 근거가 있으나 미해결인 경우·대상 불명·원래 창 밖 요청은 덮어쓰지 않는다.
  질문에는 "원문에 새 완료 기한이 없습니다. 기존 작업의 완료 기한 …을 유지합니까?"라고 표시한다.
  원문 evidence를 만들지 않으며 기한 체크를 없애거나 승인하지 않는다.
- 기존 품목을 모델이 생략한 경우, 알려진 동일 업무의 품목 참조를 확인 폼에 표시한다.
  B가 기존 정수기 AS40분을 사용하므로 종료 추천10:55가 되고, 품목 없음의 기본10분을 쓰지 않는다.
  품목 모호함 질문이 있으면 이 제안을 하지 않는다. 새 품목/장비/운영 레코드는 생성하지 않는다.
- 현 B 폼이 편집할 수 없는 질문은 `AI_REVIEW_UNSUPPORTED`, retryable=false, payload=null로 반환한다.
  내부 details.paths와 사용자용 한국어 오류가 있다. 고객·대여 종료일·숨겨진 RESCHEDULE 수량·빈 operations 등에서 끝없이 비활성화되는 확인 폼으로 넘기지 않는다.
  질문을 삭제하거나 여러 operation 중 지원 부분만 내보내지 않는다. 이 오류는 모델 실패/재시도 사유가 아니다.
  모델 origin/usage/attempts/provider ID는 보존하며 추가 모델 호출·비용 예약이 없다.
- B 서비스/DTO/DB/UI/infra·C seed/gold와 solver 지원 범위는 바꾸지 않았다.

**B 담당 전달 문서: [A AI 최소 연결](A_AI_CONNECTION.md).**
필수는 영속 비용원장과 real registry 주입, 서버 설정이다. 기존 AS 경로의 기한/종료 추천 때문에 B UI를 고칠 필요는 없다.
현재 오류 배너는 그대로 쓸 수 있고, 실제 수동 입력 전환·고객/대여 종료일 편집·전체 업무 저장 확장은 후속이다.
원장 구현은 API 오류 트랜잭션과 독립해서 비용 예약/정산이 살아남도록 해야 한다.
기존 seed의 AS2/E1 휴식 충돌 및 현재 UI의 override 미전달은 B/C 운영 시연 검수 대상으로 명시했다.

### 검증

- PASS canonical `cd app/backend && .venv/bin/python -m pytest -q`:186개(기존160 + B 폼 호환26), anyio deprecation1.
- PASS 최신 B main9f27e56 archive + A 소스/시험만 overlay한
  `/private/tmp/rentwise-b-adjust-5lj2oosf/app/backend`에서
  `/private/tmp/rentwise-a-engine-20261016/app/backend/.venv/bin/python -m pytest -q`:동일186개.
- PASS 기존 B API/격리 SQLite: 누락 기한의 기존11시 제시 → 종료10:55 확인 → 기한 미확인 계산422
  → 기한 확인 → READY → confirm200 → AS10:15·기한11시 재조회, Rental/Reservation/Asset/Dependency 불변.
  AS2 충돌은 사람이 제공한 E2 override로 분리했다. 원래 seed가 전부 유효하다거나 UI 전체 시연 PASS라는 뜻은 아니다.
- PASS B 원본 RequestPanel.vue의 실제 script를 Vue/TypeScript로 실행한 일회성 반응형 검증:
  `/private/tmp/rentwise-b-adjust-ui.cjs`. 기존 기한값이 있어 17시 추천 미노출, 품목 WP-A→40분,
  초기 ready=false, 종료 추천 후에도false, 기한 체크 후true, 최종 종료10:55/기한11시. 브라우저 렌더 검증은 아니다.
- PASS 동일 최신 B frontend의 `vue-tsc --noEmit`, `vite build`(36 modules). 기존 node_modules 재사용, 새 의존성 없음.
- PASS 잘못된/모호한 값 덮어쓰기 금지, 입력·원래 추출 결과 불변, 복수 operation 전체 오류,
  실패 시 해석·계획·운영 snapshot 미저장, B 공용 DTO JSON 왕복/출처·정산 보존.
- NOT CONFIGURED remote `sh scripts/check.sh`(파일 없음). SKIPPED 배포용 infra 체크/Docker·Oracle/실제 브라우저/운영 원장·추가 유료 모델 호출.
  모델 프롬프트/HTTP/가격은 이번에 바꾸지 않아 새 유료 검증이 필요하지 않았다. 이전 TEL-049 실호출 증거와 구분한다.

작업은 로컬 Review이며 TEL-049/050 미커밋을 포함한다. commit/push/배포·B 담당 채팅 전송은 하지 않았다.

최종 추가 확인: PASS 원본 작업공간 `sh scripts/check.sh`(문서/구성/셸 + 기존 A69개; 위 원격 앱186개와 별도), A 변경/추가11파일 소유 범위·실제 API 키 불포함·문서 로컬 링크/공백 검사. 원본 C/VOC/rental 코드는 변경하지 않았다.

## TEL-051 — 새 AI PR 제출

위 TEL-049/050의 미커밋 기록 이후 사용자가 commit/push/PR을 승인했다.
기존 PR #2는 main에 병합됐고, 이번 AI 변경은 최신 main1cd1186을 기준으로 새 codex/a-ai-intent에서 제출한다.
브랜치 전환 전후 작업11파일의 SHA256이 동일함을 확인했다. 새로운 B/C 변경을 되돌리거나 기존 A 작업을 버리지 않았다.
필수 B 연결은 [A AI 최소 연결](A_AI_CONNECTION.md)에 정리했다. 기능·회귀는 Review 상태이며 운영 AI/비용원장/Oracle/브라우저 인수는 미완료다.
이전 실제 모델 검증은 TEL-049의7회/최대 예약$0.0308로 한정한다. PR 제출 과정에서 추가 유료 호출은 하지 않는다.
최신 main 기준 최종 검사와 CI 결과는 PR의 확인 방법/최신 Checks를 기준으로 확인한다. main 병합·배포는 요청하지 않았다.

제출 전 최종 PASS: main1cd1186 기반 backend186개, frontend typecheck/build36modules, diff 공백/문서 링크/11파일 소유 범위 및 실제 API 키 불포함. 운영 연결 인수·실제 브라우저·Oracle와 추가 유료 호출은 실행하지 않았다.
