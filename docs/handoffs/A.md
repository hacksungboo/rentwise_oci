# A 인수인계 — TEL-048: B v1 채택

2026-10-16 · A/Codex · codex/a-engine · Review / codex/a-engine / PR #2
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

기존 registry/ENGINE_MODE=real을 그대로 사용할 수 있다. 추가 생성자 인자/context/결과 DTO/DB 컬럼은 없다.
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

interpret 서명/결과는 B v1이다. 모델 adapter가 없으면 AI_NOT_CONFIGURED, attempts=0 오류다.
B mock 해석으로 자동 대체하지 않는다. 명시 주입한 interpreter는 출처를 유지한다.
이번 API 검증은 B의 사람 확인 PUT 경로를 사용했다. 실제 자연어 모델/화면 전체 흐름은 미완료다.

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
