# A 인수인계 — TEL-052~056 통합

최신 요약: [2026-10-17 A 작업 완료 내역](../A_WORK_SUMMARY_2026-10-17.md). PR #13/#14 main 병합 확인. 사용자 범위 변경으로 직원 시작·완료 및 실시간 자원 갱신(TEL-058)은 보류하고 일정 생성·최적화에 집중한다. 아래 실행 이벤트 연결 항목은 향후 참고이며 현재 개발 완료를 뜻하지 않는다. 신규 납품 B 연결은 미완료다.

2026-10-17 · A/Codex · feat/a-engine-updates · 기준 main9666202.

## 현재 동작과 B 후속

| 항목 | 현재 상태 | B 후속 |
|---|---|---|
| GPT 해석/영속 비용원장 | 기존 B 연결 유지; 전체 bytes+256 ≤16000, 예약 $0.0064/시도 | 후보 거래처 축소는 후속 검토 |
| 웹 회수 지연 | 기존 B v2 bridge/core/확정 경로 유지 | 운영 시계·실행 상태/revision 연결 |
| native B v1 회수 adapter | 선택적 recovery_enabled, 순수 prepare_confirmation 제공 | 선택 시 별도 원자 저장 훅. 기존 웹에는 활성화 불필요 |
| 신규 단일 납품 | 선택적 delivery_enabled, 신규 Job/Rental/예약/의존 생성분 준비 | 서버 ID/반납정책·화면 표시·원자 생성 연결 |
| 당일 추가 요청 | 완료/진행/실패 고정, 지난 미시작 확인, 진행 직원/장비 보호, 확정 fresh clock | 직원/PREP 이벤트·실제 자원·revision 원자 갱신과 양 경로 실제 clock |

연결 문서: [회수 native](A_RECOVERY_CONNECTION.md), [신규 납품](A_DELIVERY_CONNECTION.md), [당일 실행](A_INTRADAY_CONNECTION.md), [AI 입력/예약](../AI_REAL_MODE.md).
현재 B 비용원장/v2 회수·개발 seed 수정은 이미 main에 있다. 아래 과거 '미연결/AS2 충돌/미커밋' 기록은 당시 상태이며 현재 통합 상태로 읽지 않는다.

## TEL-056 통합 검증과 제출

원본 dirty checkout3곳을 보존하고 최신 main에서 A 변경 전체를 통합했다. 회수/납품 Facade 및 내부 v1 검증 옵션을 결합했고 native 회수 prepare에도 fresh clock을 적용했다. 기본 flag는 false이며 B 서비스/DB/contracts/프런트/infra/C seed/gold를 수정하지 않았다. 현재 웹 회수 성공 경로와 native adapter 시험을 분리했다.

PASS backend362개(190+56+66+37+13), C busy seed FakeClient 해석200→사람확인→계획READY→확정200, 실제 B LedgerBudget 최대 usage 예약=정산0.0064. 앞서 명시한 seed fingerprint/byte8272 동일. PASS frontend vue-tsc --noEmit / vite build36modules(기존 의존성/번들 Node 직접 실행; npm PATH 부재를 해결). 실행/배포/유료 API는 추가하지 않았다.

재현: `cd app/backend && RENTWISE_BUSY_SEED=/absolute/path/to/seed_busy.json python -m pytest -q`. C 운영seed 미지정 CI에서는 busy 통합1개만 SKIPPED이며 나머지 회귀는 실행된다. 원격 scripts/check.sh는 없음, root bootstrap/69개 시험은 통합 앱362개와 별도다. Oracle/브라우저/직원 이벤트·동시성/배포는 SKIPPED.

사용자가 밀린 변경 전체의 commit/push/PR을 승인했다. 코드 커밋7f8dcf0, 입력 한도 커밋b4145dd와 연결 문서를 feat/a-engine-updates로 제출한다. PR URL·CI 최종 상태는 이 채팅의 제출 결과와 GitHub Checks를 따른다. main 병합/배포는 하지 않는다.

## 이전 작업 기록

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
cache-write 1.25배를 고려해 입력16000/출력2000 기준 **시도당 $0.0064 상한**(TEL-055 갱신)을 먼저 예약한다.
공용 Usage에는 cache_write_tokens가 없으므로 B 정산도 미캐시 입력을 1.25배로 잡으면 보수적 상한을 유지한다.
원문2000자, JSON/스키마/프롬프트 전체 UTF-8 bytes+256 ≤16000의 보수적 입력 제한, 출력2000 tokens.
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


## TEL-052 — A 구현 완료 / B 연결 대기

2026-10-17 · Review · `/private/tmp/rentwise-a-engine-20261016`의 `codex/a-pickup-recovery`.
기준 main9ab0c25에서 작업했으며 commit/push/새 PR/배포는 실행하지 않았다.

추가: engine/recovery.py (B v1 복구/순수 확정 변경분), compat.py opt-in, v1.py 제한된 내부 검증 옵션 및 SUPERSEDED 예약 이력 보존, tests/engine/test_recovery.py56개. 기본 facade와 독립 v2 core는 유지한다. README/ARCHITECTURE의 A 연결 설명과 TASKS를 갱신했다. B 서비스/공유 계약/schema/UI/registry/mock/infra/C 데이터는 변경하지 않았다.

- PASS `cd app/backend && .venv/bin/python -m pytest -q`: **242개**, 기존186+신규56, 외부 anyio deprecation1.
- PASS 실제 B HTTP 초안/비교 호환·기존 confirm422/운영 무저장, 참고 SQLite 저장 adapter로 전 변경분 커밋 후 새 엔진 VALID·가용 재조회, 예외 전체 롤백.
- PASS JSON 왕복/새 인스턴스/B 발급 ID, 원래 장비 재사용 우선·대체 납품 시간 유지·미래 예약 차단·검토 예약/실행 작업/준비·이동·직원·고객 창·기한, 위조/범위 밖 시간·장비·예약 변경 차단, 시간/후보 상한 및 불완전 탐색 상태, 누락/중복 기반 계획·잘못된 실제 대여시각 차단.
- NOT CONFIGURED remote `sh scripts/check.sh`: 파일 없음(exit127). 원본 작업공간 명령은 bootstrap/이전 A69개 PASS(원격242개와 별도).
- SKIPPED frontend/infra 재빌드(변경 없음), 실제 브라우저·운영 Oracle/잠금·동시성·배포·새 유료 모델 호출. B 실제 confirm200 인수는 미완료.

필수 B 연결은 [별도 문서](A_RECOVERY_CONNECTION.md)의 두 지점이다. 기존 AS/직원 경로·잠금/revision/감사/멱등 가드를 유지하고 복구 결과의 대여·예약·작업·의존 변경을 같은 confirm 트랜잭션에 저장한다. 생성 플래그만 켜면 기존 confirm422로 막히며, 기본 설정에서는 NEEDS_REVIEW로 안전하게 유지한다. 원본 AS2/E1 휴식 충돌은 시험에서 명시 E2 override로 분리했다. C seed 검수/화면 override 동선과 AI 비용원장 연결은 B/C 후속이다.

## TEL-053 — 신규 단일 납품 자동 배정

작업 위치 `/private/tmp/rentwise-a-delivery-20261017`, 별도 Git worktree. 원래 `/private/tmp/rentwise-a-engine-20261016`의 TEL-052 미커밋 회수 복구 파일은 보존했다. 이 브랜치는 최신 B 회수 bridge를 사용하는 기준 위에 신규 납품만 추가한다. 두 checkout의 미커밋 내용이 자동 병합된 것은 아니다.

추가 구현: engine/delivery.py, compat.py opt-in/prepare_delivery_confirmation, v1.py의 제한된 내부 new_jobs 검증 옵션, tests/engine/test_delivery.py66개. README/ARCHITECTURE의 A 설명·TASKS와 별도 [B 연결 문서](A_DELIVERY_CONNECTION.md)를 갱신했다. B production/공유 계약/DB schema/프런트/infra/C 데이터는 변경하지 않았다. 의존성 추가·새 유료 호출·commit/push/PR/배포·다른 채팅 전송 없음.

정상 예: PR-A1대/C-S15:00~15:15/기한17:00 → P02/E1, 14:40 창고 출발~15:35 복귀. 기존 약속·실제 물리/대여 상태는 보존하고, B 발급 ID로 Job·PLANNED Rental·무기한 예약을 생성한다. 기존 PICKUP/PREP/release 연결이 있으면 조건부 장비도 준비 완료 뒤 사용할 수 있고 PREP→납품 의존을 생성한다. FIXED 대여 종료는 예정 반납값만 설정하며 회수/준비 없는 예약을 그 시각에 닫지 않는다. UNKNOWN 우선순위는 B와 같은 NORMAL 정책이다. B가 확인한 반납 정책/서버 allocation이 없으면 빈 후보로 차단한다.

계산은 최대1000후보/2초 cooperative, 방문5분 격자(명시 고정시각 보존), 신규1건/개체1대, 명시 직원 override≤3이다. 기존 업무 시간·개체는 변경하지 않는다. 새 회수/준비·다개체·복수 요청·직접 현장 간 경로 최적화는 범위 밖이다.

검증:

- PASS 기준 main03e7913 backend190개, 최종 backend **256개**(신규66 포함). 명령: `cd app/backend && /private/tmp/rentwise-a-engine-20261016/app/backend/.venv/bin/python -m pytest -q`. 기존 Python venv만 재사용하며 conftest는 새 worktree 소스를 import한다. 외부 anyio deprecation1.
- PASS 순수 정상·선호 직원 휴식 대체·조건부 준비/반납·미래 예약·고객창·자격·FIXED/OPEN_ENDED·인도 시각, hash/버전/상한·고정/격자 시각·부분안 차단·직원 override, 위조 후보/delta/ID 충돌·상태/예약 변경 재검증.
- PASS JSON 왕복/다른 엔진/B 발급 plan/행 ID, 기존 조건·입력 불변. 기본 생성자/2인자 validate는 신규 납품을 차단한다.
- PASS 기존 B HTTP 초안201 READY·저장/조회(시험용 서버 ID/정책 binding 주입). 신규 kind/site가 아직null인 표시 한계와 미수정 confirm422/운영 무저장을 명시 검증했다. B 실제 연결 성공이 아니다.
- PASS 참고 SQLite 저장 adapter(READY/조건부 각각): 전 생성분+기존 `_finish_confirm` 커밋→새 엔진 VALID/가용 재조회, Job 생성 직후 또는 finish 후 예외→전체 snapshot/workspace/request/audit 롤백. FK 검사 활성 상태에서 실행했다.
- NOT CONFIGURED remote `sh scripts/check.sh`: 파일 없음(exit127). PASS 원본 root 같은 명령의 bootstrap/이전 A69개(새 앱256개와 별도).
- SKIPPED frontend/infra 재빌드(해당 코드/외부 DTO/의존성 불변), 실제 브라우저/Oracle·운영 동시성·배포/새 유료 LLM 호출. 실제 B 웹 confirm200 및 C 독립 인수는 미완료다.

B 후속: ①canonical hash 이전 allocation/확인 반납정책 주입+flag ②초안 prepare/표시용 Job 메타데이터·plan_view overlay ③최신 HUMAN 해석 일치 검사+기존 confirm 안의 순수 prepare/전 생성분 원자 저장. 구체적 SQL 변환·현재 UI의 반납 미정 한계·인수 시나리오는 연결 문서 참조. 기존 B의 GPT 비용원장과 회수 v2 경로는 그대로 두며 이 신규 기능을 `_apply_v2`로 보내면 안 된다.

## TEL-054 — 당일 추가 요청의 실행 보호 (2026-10-17, Review)

- 사용자: 직원별 실행 상태 갱신을 B가 추가한다고 가정하고, A에서 완료/진행 이력을 유지한 잔여 일정 계산을 보완. 실제 checkout `/private/tmp/rentwise-a-delivery-20261017`, `codex/a-new-delivery`, 기존 미커밋 TEL-053 보존. 별도 TEL-052 checkout 불변.
- 새 `engine/execution.py`: 과거 ASSIGNED/UNASSIGNED 작업 확인, 고정 실행행 변경 금지, 새/변경 출발이 현재시각 이전이면 거부, 진행 직원 재배정 금지, 현재시각 이후 보수적 이동 검사. v1 RealEngine.validate도 매 호출 clock을 읽고 신규 납품 prepare와 B v2 core에 동일 보호를 적용. v1/v2 availability에서 진행 장비는 불가용으로 유지.
- 공개 DTO/서명/스키마/B production/DB/UI/infra/C 데이터 변경 없음. 완료는 복귀 포함 전체 PlanItem 완료라는 전제다. 실제 완료 순서를 추측하지 않으며 실패 위치/미시작 확인 계약이 없는 경우 보수적 보류. 상세 요구/한계와 B 작업은 [A_INTRADAY_CONNECTION.md](A_INTRADAY_CONNECTION.md).
- PASS 최종 backend `cd app/backend && /private/tmp/rentwise-a-engine-20261016/app/backend/.venv/bin/python -m pytest -q`: **290개**(기존256+신규34), 외부 anyio warning1. 새 test_execution은 frozen3상태×직원/시각/장비/누락, 오후 신규 배정과 이력/원본 불변, stale ASSIGNED/UTC/경계, 미래 AS 변경, 상태·clock 재검증, 진행 직원/장비 차단, 현재 이동/완료 순서, v2 신규·지연/확정/가용성을 검증한다.
- PASS 기존 B AS(v1)·회수(v2) HTTP 초안 READY 후 SQLite Job을 IN_PROGRESS로 갱신하면 confirm422, 운영 snapshot/workspace/audit/초안 READY 보존. workspace revision을 의도적으로 증가시키지 않은 시험으로 A의 추가 방어를 확인했다. 실제 B 이벤트 API/현장 버튼 구현을 시험한 것은 아니다. 실제 B 연결에서는 이벤트도 revision 증가/동일 잠금이 필수다.
- PASS root `sh scripts/check.sh` 구성·문서·셸+이전 A69개(앱290과 별도), diff 공백/변경17파일 소유·문서 링크·비밀값 패턴. NOT CONFIGURED 원격 동명 명령(파일 없음 exit127), backend lint/type/build 별도 명령. SKIPPED FE/infra 재빌드(소스 불변), 직원 이벤트 API/UI/Oracle 잠금·동시성/배포/유료 API 호출. 초기 기대값/fixture 실패를 수정했고 최종 전체 통과했다.
- 최신 원격 main은 `96662027a45aa860542617e49cec6c35a3bb3d99`. 03e7913 이후 DR Terraform/CI/문서 추가만 있고 app은 동일하다. 기준 branch와 미커밋 파일을 보존했으며 main merge/commit/push/PR/메신저 전송은 하지 않았다.
- 다음 B 작업: 작업 단위 출발/전체 완료/실패 및 PREP 실행 이벤트, 실제 Asset/Rental/예약 갱신과 revision의 원자 저장, registry와 회수 bridge의 단일 실제 clock, 확정 시 최신 대상 상태 확인. 신규 납품은 TEL-053의 생성/prepare 저장 연결도 별도로 필요하다. 남은 운영 인수는 B/C가 수행한다.

## TEL-055 — busy-v1 AI 입력 한도·예약 정합성 (2026-10-17, Review)

- 사용자 요청/범위: main03e7913 기준 C busy-v1 해석의 AI_INPUT_TOO_LARGE를 해결. 별도 checkout `/private/tmp/rentwise-a-input-limit-20261017`, branch `codex/a-ai-input-limit`; 기존 TEL-053/054와 TEL-052 작업은 각각의 checkout에 그대로 보존. B services/DB/공용 계약·C 데이터/gold/사례 분류를 수정하지 않았다. 이번 수정은 유료 API 호출을 하지 않았다.
- 선택: `INPUT_LIMIT=16000`, `INPUT_FRAMING_HEADROOM=256`, `OUTPUT_LIMIT=2000`. 지시문/schema/후보/기존 작업/원문을 포함한 전체 body의 UTF-8 bytes+256을 검사한다. tokenizer 추정이나 새 API/의존성을 추가하지 않았다. 16000을 실제 입력 토큰 개수로 표현하지 않는다. 문장2000자/기존 작업15개 제한·초과 시 AI_INPUT_TOO_LARGE/모델 호출0·예약0은 유지한다. 거래처120곳은 대표 크기 시험이며 모든 길이·문맥 조합 보장이 아니다.
- 예약: 기존 Decimal 계산식이 INPUT_LIMIT를 직접 사용하므로 상향과 동시에 `$0.0064/시도 = (16000×1.25×0.20 + 2000×1.20)/1,000,000`로 맞춰진다. 최대2시도 $0.0128; 240회×2시도 최대 예약은 **$3.072**, 이전8000 기준은 $2.112다. 요청에 적힌 $6.14/$4.22는 이 조건의 산술보다 두 배다. 이 계산은 기존 가격·byte≥token+framing의 보수 정책에 따른 예약액이며 실청구액/승인 예산의 변경이 아니다. usage 없는 시도는 예약을 유지하고 두 번째 시도도 별도 전액 예약해야 한다.
- 버전: `PRICE_VERSION=openai-standard-2026-10-16`, `PROMPT_VERSION=rental-extract-v1.1` **유지**. 단가·실제 프롬프트·모델·응답 schema가 같으므로 버전을 임의 변경하지 않았다. 최신 실청구 단가를 이번에 재검증했다고 주장하지 않는다. 정확한 토큰 계수와 이 로컬 byte 정책의 차이는 [OpenAI 문서](https://developers.openai.com/api/docs/guides/token-counting) 및 [실행 안내](../AI_REAL_MODE.md)에 기록했다.
- 새 A 시험13개: 합성 거래처38/120곳 입력을 후보 잘림 없이 전달, 전체 bytes 정확16000 허용/16001 차단, 한글 multibyte 초과, 입력16000·출력2000/캐시0·8000·16000의 예약≥정산식, 두 시도 각각6400µUSD·unknown 유지, 첫/둘째 예약 잔액 부족 시 호출 차단. 실제 B LedgerBudget(SQLite)에서도 최대 미캐시 usage의 reserved=settled=$0.0064를 검증했다.
- C 통합은 운영용 `rental/fixtures/infra/seed_busy.json`만 `RENTWISE_BUSY_SEED` 환경변수로 읽었다. SHA256 `dcd72cff4e4f61e945ca632a9c4de8328ee324a296352135301f380d0a1c0817`, dataset rental-synth-busy-v1, 고객38/직원12/장비132. gold/scenarios/분류 파일을 읽거나 예상 출력을 가져오지 않았다. 요청은 사용자 문장을 사용했고 시험용 FakeClient 응답은 A 시험에서 명시 구성했다. 원본 seed의 바이트 불변을 검증했다.
- 실제 B API·격리 SQLite·영속 비용원장: 해석200(AI metadata, 전체38곳, bytes+256=**8272**) → AI 단독 계산422 → 사람 종료/기한 확인 READY → 계획201 READY → 확정200 → 회수 E2/14시, 기존 납품 P02/정오 유지 재조회. 초안 전후 운영 snapshot 동일, 확정 이후 실제 Asset 상태 불변. 모델만 FakeClient이며 실제 OpenAI 의미 정확도·청구·Oracle/브라우저 인수가 아니다.
- **PASS** 최종 `cd app/backend && RENTWISE_BUSY_SEED=/absolute/path/to/seed_busy.json /private/tmp/rentwise-a-engine-20261016/app/backend/.venv/bin/python -m pytest -q -rP`: **203개(기존190+신규13)**, 외부 anyio deprecation1. 새 source 경로의 conftest를 사용하고 과거 venv Python만 재사용했다. C seed를 주지 않는 CI에서는 새 통합1개만 SKIPPED이고 나머지 입력/예약 시험은 항상 실행된다.
- **PASS** root `sh scripts/check.sh`: 구성/문서/셸+기존 A69개(위 앱203과 별도); `git diff --check`, B services/DB/contracts/fixtures diff0. **NOT CONFIGURED** 원격 동명 명령(파일 없음 exit127), backend 별도 lint/type/build. **SKIPPED** FE/infra 재빌드(해당 소스 불변), 실제 OpenAI 호출·운영 Oracle·브라우저·T17 측정. commit/push/PR/배포/다른 채팅 전송 없음.
- B 참고: 발신 거래처+원문 이름/약칭 검색 결과로 후보를 줄이는 정책은 후속으로 검토한다. 출처 누락·동명이인·모호함을 숨기지 않는 검색 계약과 별도 시험이 필요하다. 이번 한도 수정에 B 코드 수정은 필요 없다.

## TEL-057 — 변경안 AI 설명 화면·API

2026-10-17 · feat/a-plan-explanation · base mainaa58564(PR13 병합). 사용자가 이번에는 화면·API까지 명시 승인하여 A engine와 B api/services/frontend를 단일 세션에서 순차 통합했다. 새 public 공용 계약/DB schema/의존성·C 데이터/gold 변경은 없다. commit/push/새 PR/배포는 이번 요청에 없어 하지 않았다.

추가: engine/explain.py(순수 facts·서버 문장/프롬프트·budget), RealEngine.explain_plan, services/explanations.py(연결 없는 AI 대기/재검사/기록), ADMIN 설명 API, frontend api/타입·PlanReview 버튼/로딩/요약/오류/유지 약속. 모델은 기존 transport/공유 _ACTIVE_CALL/PRICES/영속 LedgerBudget을 재사용한다. AI는 확인된 fact ID를 정렬하며 서버가 숫자/시각/담당/장비·불변 notice를 렌더한다. 누락/중복/미확인ID/추가 자유문장 응답은 SYSTEM 요약으로 끝낸다.

설명 입력은 현재안 facts만, 전체bytes+256≤16000/출력1000/1시도20초/예약0.0052, PROMPT=rental-plan-explain-v1.0, PRICE 기존 유지. PREP는실제segment시작14:30/완료15:00 구분, 납품 약속12시/담당 유지. 직원 변경의 구체 원인(예: 휴식)은 단순 reason code로 추론하지 않는다. 실제원장 최대usage 예약=정산0.0052 시험도 포함한다.

API는 plan_id/revision/hash/base/current state와READY를 모델 전후 확인하고, 사실 내용도 fingerprint로 재비교한다. DB 연결/트랜잭션을 모델 대기 중 유지하지 않는다. 이 사이 확정/보류/상태변경은409, 권한없는호출401/403, timeout은200 FALLBACK(원장UNKNOWN유지) 후 기존확정200을 검증했다. 고객/직원 이름은자료이며 UI Vue보간으로 표시한다. 현재페이지 동일안 응답을재사용하고, props변경/늦은응답은버린다. 별도서버캐시없음.

로컬 IAB 브라우저에서 격리 SQLite/FakeClient/실제 B HTTP를 사용해 로그인→원문해석→사람추천확인→변경안→AI설명보기까지 확인했다. 설명은 회수10→14/김현우→이서연, 준비10:30~11→14:30~15, P01준비완료15시로정오납품불가→P02대체, 정오약속/담당김현우유지를 표시했다. UI준비시각영향의잘못된'완료'문구/RETURN_PREP노출·배지줄바꿈도정리했다. 캡처 `/private/tmp/rentwise-plan-explanation.png`는모델대역시연이며실유료AI가아니다.

최종시험결과는TASKS TEL-057을따른다. 실제유료모델응답정확도·운영Oracle·모바일viewport·배포는SKIPPED. API기록확정후 최신안확인과일반확정의기존잠금/검증은유지한다. 프런트는기존의존성/번들Node로configured타입/빌드검증, 검증서버는테스트용이다.

정리 완료: root `sh scripts/check.sh` PASS(기존 A69 포함, 앱390과 별도), 로컬 QA 서버 종료·임시 node_modules 링크 제거 확인. 최종 diff 공백 검사 PASS. feat/a-plan-explanation의 새 기능 변경은 미커밋 상태다.

사용자 제출 승인 후 최신 main8f22d41(백업 기능 추가) 위로 rebase 완료, 충돌 없음. 동일 FakeClient/busy seed 전체 명령 **391 PASS**, frontend configured typecheck/build36modules PASS. 이번 제출은 feat/a-plan-explanation의 TEL-057 14파일만 포함하며 B 소유 경로를 PR에 명시해 리뷰를 요청한다. 기존 '미커밋' 기록은 당시 상태이며 이번 commit/push/PR 제출로 대체한다. main 병합/배포/유료 호출은 별도다.

## TEL-062 — 3건 동시 접수·순차 처리 화면/API (Review)

2026-10-17 · feat/b-request-queue · base main58b7eb5. 사용자 UI/API 전체 구현 승인. 기존 B 단일 요청·사람조건·계획·확정 API와 A 엔진을 재사용했다. 공용 rental 계약/모델·프롬프트/가격/예산/solver/infra/C 데이터 변경 없음. B 소유 api/services/db/frontend를 수정했으므로 PR 제출 시 B 리뷰 대상이다.

- 구현: 최대3건 원자/멱등 접수, workspace 활성 묶음1개, DB 영속 FIFO, 선두만 해석/수정/계산/확정·보류. 기존 경로를 통한 후행 우회도409. 다음 계산은 잠금 안 최신 current_plan_id/revision/snapshot이며 별도 큐 API가 오래된 화면 revision을 받지 않는다. 기존 독립확정 검증/멱등·원자저장 유지. 새 사람조건 확인 후 옛 초안 확정도409.
- 해석 lease120초를 짧게 저장하고 DB 연결을 닫은 뒤 기존 interpreter를 호출한다. 중복 호출은409, 저장된 해석의 재요청은 같은 결과/추가 호출0. 모델 반환 후 token/선두/revision 검사, 프로세스 소실 후 lease 만료 시 복구. 큐 자동재시도/worker 없음(기존 interpreter 내부 최대2시도는 유지). 실패 시 선두 유지, 직접입력/사유보류 가능. 페이지 재접속은 과금 없이 복원, 확정·보류 뒤 열린 화면이 다음 해석을 실행한다.
- DB schema2: rw_request_queues/rw_request_queue_items 추가만, 기존 데이터/컬럼 보존. 기동 create_all+버전기록, reset/논리백업 포함, v1백업→빈큐/schema2 호환. SQLite에서도 workspace 쓰기 잠금을 먼저 획득. 새 env/의존성/배포 설정은 없다. 운영 적용은 별도.
- PASS backend 전체 **415개**(기존391+큐24, FakeClient/격리SQLite, RENTWISE_BUSY_SEED 지정), 외부anyio deprecation1. B 개발seed 회수14시→AS1 10:15→AS2 다음날14:15 세번 확정 r7→8→9→10; 이전 직원/장비/시각/segments와 고객조건 보존, 초안무저장/실제Asset불변. 동시 접수멱등/확정1회, 실패·수동대체·보류·닫힌요청, 저장실패롤백, stale snapshot/사람조건, lease중복/만료·모델중DBconnection0, 권한, reset/backup/schema1upgrade 회귀 포함.
- PASS frontend configured vue-tsc --noEmit / vite build39modules(기존의존성+번들Node), Oracle 새DDL·workspace FOR UPDATE 컴파일(실기동 아님), diff공백. 로컬 IAB/FakeClient에서3건접수→각확정→r10/선행회수·대체유지, 두번째초안중새로고침복원, 최종UI조건수정·재계산/변경안보류/해석단계사유보류→다음조건을 확인했다. 이미지 /private/tmp/rentwise-queue-qa/completed.png는 모델대역 시연이다.
- 발견한 기존 한계: busy-v1의 회수확정은 r8로 유지되지만 뒤 AS 계산은 기존 v1 validator가 J-TRF1 VISIT_WINDOW를 반환하여 UNRESOLVED. 회귀는 이를 확정하지 않고 명시보류한 결과 **확정1/보류2**를 검증한다. seed/solver 의미는 이번 작업에서 수정하지 않았다. [상세 API·B 적용/재현](../REQUEST_QUEUE.md). 신규납품 B 연결도 기존 미완료 범위 그대로다.
- SKIPPED 실제유료모델/Oracle·클라우드·다중서버/모바일 viewport/배포. backend 별도lint/type/build·이 저장소 scripts/check.sh NOT CONFIGURED. root 기존69/bootstrap check는 별도 저장소 검증이다. commit/push/PR/배포 없음. deferred 실행 기능checkout과 다른 작업은 보존했다.

TEL-062 Git 제출 승인: 사용자가 대기열 변경의 commit/push/PR을 요청했다. origin/main58b7eb5 최신 확인(추가 변경/충돌 없음), 제출 전 backend415 PASS·frontend typecheck/build39 PASS·root69/bootstrap PASS 재실행. 대기열18파일만 제출하며 deferred 실행 기능/C자료/한도 측정 보고서·캡처는 이 commit에 포함하지 않는다. B 소유 API/services/DB/FE 및 schema2/기존busy AS 한계를 PR에 명시한다. 실제유료호출/Oracle 실기동/운영배포/병합은 별도다.

## TEL-063/064 — busy 미리보기 교정·인력 부족 대안 (2026-10-17, Review)

사용자 확정 정책: 실제 퀵 호출 없이 배정 변경안→책임자 확인·확정, 회수는 다음 근무일 고객 방문 가능 시간. maina4081bb+미커밋TEL063을 보존한 feat/b-dispatch-fallback에서 A engine과 B services/Vue까지 연결했다. [전체 계약·무료 재현](../DISPATCH_FALLBACK.md).

- v1 TRANSFER의 두 번째 SERVICE를 출발창으로 검사하던 오판을 기존 B bridge/R3 도착창 규칙으로 교정. 미해결/부분 후보의 diff를 없애고 현재 계획을 유지한다. 같은 busy AS는 기존169삭제diff→변경1/삭제0, 불가능 요청은 계속 미해결/확정 비활성이다. 이전 TEL062의 busy AS 보류 한계는 이 수정으로 대체한다.
- 기존 DELIVERY RESCHEDULE의 PLANNED 대여/예약을 정확히 연결해 v2 계산·검증·저장. 인력 부족이 별도로 확인될 때만 전용 퀵 자원을 제안. 당일 PICKUP은 다음1~6일의 직원 근무표/고객창과 PREP/후속 납품을 함께 검증한다. 고객 약속을 유지할 수 없으면 미해결이다.
- pending 퀵은 초안 메타데이터/별도 미리보기 행에만 존재. 확정에서 최신 HUMAN/revision/독립 검증과 함께 기존 직원/근무표 삽입·예약/대여/작업/의존·계획교체를 원자 저장한다. 퀵의 다른 작업 재사용과 수동 직원 지정 우회 금지, 실제 상태 불변. 큐는 기존 최신 계획 규칙을 사용한다.
- 화면에서 호출 필요/실제 호출 별도, 회수 전후 날짜·새 방문창·기한, 변경 일정 확인 후 확정을 명시한다. 실제 퀵 가용성/가격은 검증하지 않으며 날짜별24시간 전용 자원은 계획 가정이다. 호출 완료 처리·실시간 직원 기록은 범위 밖이다.
- solver 버전 v2 `rental-solver-normal-delay-v2-1`/v1 `rental-solver-b-v1-4`, 내부 정책 `dispatch-fallback-v1`. 단계별2초/1000후보/변경3건, 전체최대14단계로 합산 통계를 반환한다. HTTP 전체2초 보장 없음. AI MODEL/PROMPT/PRICE/한도/예약은 불변이고 추가 모델 호출 없다.

B 후속 구현은 별도 필수가 아니다. 이 브랜치의 services/plans/v2_bridge/dispatch_fallback 및 Vue/API 응답 추가를 함께 리뷰·반영해야 한다. 공용 계약/DB schema/seed/infra는 그대로이며 실제 업체 호출 API·운영 Oracle·다중서버 인수는 후속이다. commit/push/운영배포는 이번 작업에서 수행하지 않는다.

검증 근거(최종): **PASS** backend 전체456개=기존415+TEL06312+TEL06429(명시busy운영seed/FakeClient·격리SQLite,23.61s,외부anyio경고1). **PASS** frontend configured typecheck/build39modules(기존node_modules/번들Node), root `sh scripts/check.sh` bootstrap/기존A69는별도. **PASS** IAB: busy seed 사본의금요일근무종료17:30조건에서배송17:30퀵제안→확정r8→회수다음등록근무일10/17 09:20/PREP09:50→배송17:30/퀵유지·P02대체→확정r9, 운영169건/실제Asset보존. 날짜전환미리보기/확정본조회포함. 배송Fake응답근거오류는AI_SCHEMA_INVALID차단→수동입력으로진행, 회수Fake해석은정상이며실모델호출0이다. 별도회귀에서고객주말휴무→월요일/인력·방문·재고구분/자원재사용금지·초안무변경/최신큐·stale·rollback을검사한다. **SKIPPED** 실제OpenAI·업체호출/가격·운영Oracle/다중서버/모바일/배포, **NOT CONFIGURED** 실제repo rootcheck/backend별도lint/type/build. QA서버/탭/임시의존성링크정리. commit/push/PR없음.

2026-10-17 사용자 로컬 커밋 승인: 앞선 미커밋 기록은 당시 상태다. 동일 구현을 TEL063 오류 수정과 TEL064 대안 기능 두 커밋으로 분리한다. push/PR/배포는 이번 승인 범위에 포함하지 않는다. 최종 통합 코드456/프런트·브라우저 검증 증거는 동일하다.

TEL063은 `0aa4505`로 먼저 커밋했다. 분리한 index 사본의 backend427(16.76s, busy/FakeClient)/frontend typecheck·build39 PASS로 독립 검증했다. TEL064 원본 구현은 변경 없이 보존해 기능·문서 커밋으로 분리하며 이전 통합456 검증 결과를 유지한다.

PR 제출 승인(2026-10-17): 사용자 요청으로 feat/b-dispatch-fallback을 main 대상으로 푸시·PR 제출한다. 최신 fetch maina4081bb/충돌 없음·rebase up to date. 앞선 로컬 커밋만 승인 상태에서 새 지시로 제출 범위가 확장됐으며, 최종 코드/456 시험·프런트·브라우저 증거는 동일하다. B services/frontend 소유자 리뷰 필요, 실제 업체 호출/Oracle·다중서버/배포 인수는 별도다. main 병합·배포는 수행하지 않는다.

## TEL-065 — Terra·Markdown 강조·고객 안내문 (Review 준비)

사용자 요청으로 해석/설명 기본모델을 gpt-5.6-terra로 전환했다. 공식모델/가격 확인2026-10-17, 단가 입력2/캐시.2/출력12USD/1M·캐시쓰기1.25배. 중앙 ai_policy/모델별정산버전은 Terra `openai-standard-2026-10-17-terra`, legacyLuna `openai-standard-2026-10-16`. B원장은전역settings에의존하지않고호출가격버전으로정산해진행중모델혼선을막는다. 입력16k/해석출력2000·설명1000 유지→예약해석.064/시도·설명.052/회,총예산자동증액없음. 기존명시Luna환경은그대로존중하므로운영 `.env OPENAI_MODEL=gpt-5.6-terra`수정/API재기동필요. 이로인한운영배포는수행않음.

AI는계속사실ID순서만정하고서버가문장을구성한다. presentation_version `rental-plan-markdown-v1`/markdown을추가하되plain paragraphs/preserved/notice호환유지. 핵심/이유/유지/확정안내구획과고객·변경후시각/직원/장비bold. 이름문법/개행인용,Vue제목·목록·강조·인용보간만지원·HTML/링크/이미지미실행. AI실패SYSTEM기본설명도동일형식. 모델프롬프트/schema그대로라PROMPT_VERSION기존유지.

추가사용자요청: 확정후고객요청수락/일정배정안내문. GET /plans/{id}/customer-message ADMIN,workspace짧은잠금/현재확정·최신HUMAN/수신고객직접작업범위검사. SYSTEM확정사실문장(추가AI비용0),다른고객/직원/장비ID/창고준비미포함·SERVICE방문시각사용,실제작업/발송완료주장않음. 퀵미호출은업체호출·수락확인후최종안내문구. 단일/큐양쪽확정후화면/최신재조회복사/실패시수동선택복사,오래된계획·미확정·모호수신·다른고객혼합차단. 새DBschema·외부발송없음.

B리뷰대상: config/ledger/routes/customer_messages + frontend컴포넌트/모델env기본값. 실제기능연결은이작업에포함했다. `OPENAI_MODEL`운영값수정·API재기동과실제Terra접근·의미품질/Oracle다중서버는별도인수. Cseed/gold불변, 실제유료호출/commit/push/PR/배포없음. 브랜치는PR20head94b072e기반 feat/a-terra-markdown이며새main759cea4모니터링과통합은아직수행하지않았다.

검증 결과: PASS backend 전체477(27.58s,명시busy/FakeClient) + 이후추가큐고객회귀1(고객시험13개실행3.15s) = 총478개고유회귀검증. Terra/legacy루팅·환경설정혼선정산/모델별최대예약·불명보존·Markdown문법인용/오류SYSTEM·고객별범위/미확정·stale·이미진행/완료/권한·큐수신자전환을포함한다. 기존415/PR20회귀도포함하며Cgold/사례분류는읽지않았다. 외부anyio경고1. PASS configuredfrontend typecheck/build46modules + 새node test4개(추가패키지없음).

PASS IAB/FakeClient·격리busy: 모델두호출Terra assert→조건사람확인→제목/목록/중요값strong→확정r8→한빛상사방문14:00~14:10안내문/타고객·내부정보제외→최신재조회복사완료, QA계획변경후stale안내문차단. 캡처root outputs/01a1452d-b293-76a0-931a-7600de83e74c/terra-markdown.png 및 customer-message.png. 실제유료모델/발송0. 서버/탭/임시의존성링크정리. SKIPPED 실제모델계정접근·의미품질·청구/운영Oracle·다중서버·모바일·배포·발송,compose실행(docker없음),NOT CONFIGURED repo rootcheck/backend독립lint/type/build. 커밋/푸시/PR없음.


## 2026-10-17 — 사용자 지정 검증·제출 정책

사용자 지시: 이후 기본 검증에서 브라우저 수동 화면 확인은 생략한다. 관련 자동 테스트·타입 검사·빌드와 변경 범위/비밀값 검토를 완료하면 별도 확인 질문 없이 작업 브랜치에 커밋·푸시하고 main 대상 PR을 생성한다. 자동 검증 실패나 미검증 항목은 숨기지 않는다. 화면 확인을 별도로 요청하면 해당 요청을 따른다. 이 승인은 main 병합·운영 배포·유료 모델 호출·고객 메시지 발송을 포함하지 않는다.

TEL-065도 이 제출 승인에 포함된다. 최신 main3f988e3에는 PR20과 모니터링이 병합되어 있으므로 작업을 보존한 채 최신 main으로 rebase하고 자동 회귀 검증 후 제출한다. 앞선 “commit/push/PR 없음”은 당시 상태이며 이 지시로 대체된다. B 소유 API/services/frontend/infra 경로는 PR에 명시하고 소유자 리뷰 상태를 구분한다.


TEL-065 제출 전 통합 검증(2026-10-17): 최신 origin/main3f988e3(PR20·모니터링 포함)에 rebase 충돌 없이 완료. 기능 커밋 f36eddd. 최종 통합본 backend 전체 **478 PASS**,28.36s/외부anyio deprecation1(`RENTWISE_BUSY_SEED=/absolute/path/to/seed_busy.json python -m pytest -q`, 실제 운영busy fixture/FakeClient/격리SQLite). frontend configured typecheck·build46modules/node 마크다운4 PASS, 공유root sh scripts/check.sh bootstrap/문서·기존A69 PASS(실제앱과별도), diff공백/31파일비밀값패턴 PASS. 임시 node_modules symlink 제거. 사용자 지정으로 제출 단계 브라우저 수동 확인 생략, 기존 구현 단계 화면 증거는 보존. 유료호출/운영배포/병합 없음. B 경로 소유자 리뷰·실제 모델/Oracle 인수 대기, 기존 운영env Terra 변경/API재기동은후속. 이 검증은 제출 기능 커밋과 동일한 코드에 대한 결과이며 후속 변경은 인계 문서뿐이다.


## TEL-066 — 순차 대기열 오류 구분·복구 (In Progress)

2026-10-17 · Owner Codex B · fix/b-queue-error-recovery · main5624c17. 사용자 캡처: 1확정/2보류/3해석대기에서 NETWORK 및 수동입력 비활성. 운영 근본 원인은 HTTP/서버 로그 미수신으로 미확정. 확정 결함: HTML HTTP 오류와 JSON 파싱·클라이언트 예외를 모두 NETWORK로 오분류; 자동 해석 실패를 자식 입력기에 전달하지 않아 입력 화면에 원인·후속 안내가 없음. 직접입력 버튼은 기존 작업을 선택해야 활성화되는 기존 동작이며, 캡처의 비활성만으로 수동 처리 자체가 막혔다고 단정하지 않음.
소유 frontend api/RequestQueue/RequestPanel·무료 Node/Vue 시험·CI test실행, backend 순차 회귀시험·인계. 계획: HTTP/연결/응답형식 오류 구분·상태/trace 표시→자동해석 실패 후 GET으로 저장결과/선두 복구(추가 모델 재시도 없음)→저장결과 존재시 복원, 결과 없을 때 확인된 현재 요청에 오류 전달·수동 대체, GET도 실패하면 재조회 전 입력 차단→1확정/2보류/3오류·복구시험. 서버원인 추측성 수정/원본확정·FIFO·예산·Cseed/gold 변경 없음.
수용: HTML502/504가 NETWORK로 숨겨지지 않음, 자동실패 뒤 성공결과는 추가POST없이 복원, 미저장오류는 선두 유지·명시재시도/기존작업 수동입력 허용, 조회실패는 복구버튼/상태불확실 표시, 선행확정·보류 보존. 자동검증 후 commit/push/PR은 사용자 기본 승인, 수동 화면·유료 호출/운영변경/병합·배포 미수행. 실제 네트워크 원인은 로그 대기 상태로 남긴다.


TEL-066 결과 — Review(2026-10-17). 운영 제공 로그로 Terra 호출 정상/첫 회수 확정 성공, 이후 두 신규 설치는 AI_REVIEW_UNSUPPORTED임을 확인했다. 정확한 브라우저 NETWORK 예외·응답 본문은 수집하지 않았으므로 프록시 HTML을 실원인으로 단정하지 않는다. 반납 미정 신규 CREATE→현재 폼의 rental_end_at 미지원 거절은 무료 회귀로 재현했다. 지원하지 않는 검토만 HTTP422/retryable=false·paths를 반환, 기존모델오류502유지. 프런트 오류 구분/trace, 자동실패후 GET복원·미저장오류전달·저장불확실 입력차단, 같은화면의unsupported반복해석차단·보류안내. 기존 직접입력은 작업을 먼저 골라야 활성화되며 신규설치를 기존업무변경으로자동변환하지 않는다. 선행확정·FIFO/lease·예산·DBschema/공용계약·Cseed/gold불변.
PASS 최종 backend479(27.51s,명시busy/FakeClient/SQLite,외부anyio경고1): 기존478+신규설치2건거절/보류/첫확정보존1. 관련51개도PASS. frontend configuredtypecheck/build46modules, node --test tests/*.test.mjs18개(기존Markdown4+HTTP8+실제Vue메모리renderer복구6) PASS. CI frontend에 npm test추가/새패키지없음. 공유root sh scripts/check.sh bootstrap·문서·기존A69 PASS(실제앱과별도). 초기시험보조코드/실행경로오류는수정후최종전부통과. SKIPPED 사용자지정 수동화면/실제유료모델·운영Oracle·다중서버·배포, NOT CONFIGURED 실제repo rootcheck/backend별도lint/type/build. 운영원본변경없음, 신규납품반납일/무기한확인UI·자동배정연결은별도미구현범위. 기본승인에따라commit/push/PR예정, 병합·배포없음.

제출 직전 최신main03682c6(PR24)은 monitoring/alloy IPv4 probe만 바뀌었고 검증한 앱 코드와 차이가 없다. 해당 인프라 변경을 보존해 rebase하며 앱 검증 결과는 동일 코드에 적용된다.


## TEL-067 — A/S 오후 변경 추천·확정 조건 교정 (In Progress)

2026-10-17 · Owner Codex A/B · fix/a-as-reschedule-window · maina906caa(PR25병합). 캡처: 오전AS를16시로바꿔도기존11:30기한추천,17:30기한확인시B_V1_PERSISTENCE_UNSUPPORTED. 원인: FE 기존기한무조건추천 + A v1의기존방문창/기한안으로만AS변경허용, Bconfirm도변경전Job조건으로재검증. B저장코드는이미ops의새window/due원자저장가능.
소유 RequestPanel·v1solver·Bplans확정검증·행동시험/문서. 계획: 새방문완료보다이른기한추천제외/방문완료기준추천→AS만명시확인된창/기한확장허용(타종류기존경계유지)→확정잠금안최신HUMAN/동일normalizedops검사후AS3조건만복사한snapshot으로독립검증,DB원자갱신→무료busy/표준seed16시·17:30계산확정/보존·stale/제약/rollback·Vue추천회귀. 실제직원실시간/신규설치/가격·모델·schema/Cgold변경없음.
수용:16시AS에11:30추천안함;기존기한이새완료를수용하면유지추천;새16~16:30/17:30승인시조건가능하면READY→확정/재조회새Job조건저장,초안원본불변;고객창/근무·휴식/고정상태·부정확시간·stale·타작업변경은계속차단. 자동검증후commit/push/PR기본승인,수동화면/유료/운영변경/병합·배포없음.


TEL-067 결과 — Review(2026-10-17). FE는기존완료기한이새방문종료/최소현장소요를수용할때만추천,아니면새완료기준추천(사람클릭필수·소요미상시추정안함·이전날/잘못남은종료방어). A v1-5 AS RESCHEDULE만기존창/기한밖새조건허용,방문창순서·완료기한/타업무저장제한유지. B확정은최신HUMAN/모든확인·동일정규화ops를검사후AS3조건만복사snapshot에서독립검증,기존원자저장/revision사용. 다른고객창/근무·휴식·기술·이동/장비·예약·고정상태는완화않음. B추가연결은포함됐고소유자review대상. 새schema/env/모델·예산/공용계약/Cseed·gold변경없음.
PASS backend전체494(28.44s,기존479+AS15회귀,명시운영busy/FakeClient/SQLite·외부anyio경고1). 실제busy원본사본의가람AS16~16:30/기한17:30→READY→확정r8→고객안내재조회/전체일정169·타작업·예약/대여/장비보존. B개발seed는WP40분이라16~16:40으로별도검증(원본fixture변경없음). 새창독립확정검사/최신HUMAN/storedops불일치/stale/고객창변경/고정상태/시간순서/rollback 포함. 초기시험에서대상선택/seed별소요시간40·30차이를잘못가정한부분은수정후최종통과.
PASS frontendconfiguredtypecheck/build46modules + node25(기존18+AS추천7,실제Vue메모리renderer). 기존기한유지/16시변경·선택종료/이전날·소요미상·stale종료/사람클릭검증. root sh scripts/check.sh bootstrap·문서·기존A69 PASS(별도repo). SKIPPED 사용자지정수동화면/유료실호출/운영Oracle·다중서버/배포, NOT CONFIGURED 실제repo rootcheck/backend독립lint/type/build. 운영원본/고객데이터수정없음. 최신maina906caa불변,기본승인으로commit/push/PR제출예정. 배포후기존실패초안은조건확인/재계산필요,데이터초기화불필요.
