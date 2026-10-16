# A → B: 당일 추가 요청과 실행 상태 연결 (TEL-054)

기준: main `03e7913`의 B v1 API/DB + 회수 지연 v2 bridge, A TEL-053 신규 납품과 TEL-054 실행 보호. 통합 작업 branch `feat/a-engine-updates`(main9666202). B production 코드는 수정하지 않았다. 직원 실행 기록 API/UI를 B가 추가한다는 사용자 전제이며, 이 문서 자체가 해당 API 구현 완료를 뜻하지 않는다.

## A에서 구현한 동작

- 전체 계획을 반환하되 COMPLETED / IN_PROGRESS / FAILED 작업의 직원·장비·시각·구간을 변경하지 않는다. 새 계획의 행 ID/plan_id/설명 라벨 재발급은 실행 변경이 아니다.
- 예정 **출발**(`plan_items.start_at`, 서비스 시작 아님)이 계산 시각보다 과거인데 UNASSIGNED/ASSIGNED이면 `NEEDS_REVIEW / EXECUTION_STATUS_REQUIRED`. 일부만 새 계획으로 반환하지 않는다. 딱 같은 시각은 허용하고 1초라도 지났으면 상태 확인이 필요하다.
- 기존 미시작 미래 작업만 원래 지원 범위 안에서 변경한다. 일반 v1은 직원 변경/기존 창 안 AS 이동, 신규 납품은 기존 약속 보존, 회수 지연은 기존 v2 영향 그래프 범위를 유지한다. 모든 미래 약속을 임의로 최적화하는 기능은 아니다.
- 진행 중인 직원에게 새 작업 또는 변경 작업을 추가하지 않는다. 예정 종료 시각이 지나도 실제 완료 전에는 풀지 않는다. 진행 장비도 가용성의 READY/조건부 재사용 목록에서 제외한다.
- 신규·변경 작업은 현재 시각 이후에 출발해야 한다. 직원의 첫 추가 이동을 과거의 여유 시간으로 충당하지 않는다. 진행 중인 직원의 남은 시간을 추정하지 않는다.
- 확정 재검증도 현재 시각과 최신 상태를 사용한다. 신규 납품 prepare가 실패하면 생성/수정/예약 변경분은 모두 빈 값이다. v1 두 인자 validate 서명과 v2 공개 계약은 유지한다.

진입점: `engine/execution.py` 공통 보호, `RealEngine.solve/validate/availability`, opt-in `prepare_delivery_confirmation`, v2 `solve/validate/availability`. B가 사용하는 `services/v2_bridge.py`를 수정하지 않고도 새 core 검사가 적용된다. TEL-056에서는 과거 TEL-052 native recovery도 같은 branch로 통합했고 solve/prepare의 동일 보호를 추가했다. B의 기존 v2 회수 경로는 유지한다.

## B 필수 연결 1 — 실행 상태와 스냅샷

기존 `jobs.status`와 현행 `plan_items.employee_id`를 사용한다. A용 새로운 DTO나 DB 컬럼은 필수가 아니다. 실행 이벤트/감사 이력의 저장 구조와 화면은 B 소유다.

1. 배정 직원이 실제 출발/작업 시작할 때 해당 Job을 IN_PROGRESS로 기록한다. 고객 현장 서비스뿐 아니라 이동 중에도 이미 시작한 작업이다. UI에서는 직원별 일정의 **작업 단위**로 갱신한다.
2. COMPLETED는 PlanItem의 **전체 구간(복귀 포함)** 완료를 뜻한다. 현장 인도/서비스 종료 버튼만 눌렀는데 복귀 TRAVEL이 남아 있다면 IN_PROGRESS를 유지한다. 현장 인도 시 Rental/Asset의 실제 상태는 별도 실제 이벤트로 갱신할 수 있다.
3. 직원 작업과 별개인 PREP도 실제 시작/완료 갱신이 필요하다. 준비 예정 시간이 지났다고 자동 완료/장비 READY 처리하지 않는다.
4. 작업 시작/완료/실패 이벤트와 실제 Asset 위치·상태·custody, Rental actual_start/actual_end/status, 예약/준비 해제의 필요한 변경을 **동일 트랜잭션**으로 저장한다. 작업 완료만으로 무조건 모든 예약을 해제하지 않는다(납품 완료 뒤 대여는 계속 점유한다).
5. 실행 이벤트마다 Job revision과 workspace state_revision을 증가시키고 기존 계획 확정과 같은 workspace 잠금을 사용한다. actor의 직원/배정 권한과 멱등 키, 유효한 상태 전이도 검사한다.
6. 엔진 snapshot에는 최신 Job 상태와 운영 Asset/Rental/Reservation을 함께 넣고, 완료·진행 행도 현행 전체 계획에서 제거하지 않는다. A는 snapshot을 바꾸거나 실제 완료를 추정해 기록하지 않는다.

**지난 미시작 작업의 확인:** 예정 시간이 지났지만 정말 아직 시작하지 않은 경우를 B v1 상태만으로는 '상태 전송 지연'과 구별할 수 없다. 현재는 자동 재배정을 보수적으로 중단한다. 통과를 위해 거짓 COMPLETED/IN_PROGRESS를 기록하거나 clock을 되돌리지 않는다. 이러한 지연 작업을 자동 이동하려면 이후 별도의 '현재 시각에 미시작 확인' 계약을 A/B가 추가해야 한다.

## B 필수 연결 2 — 같은 실제 시계

현재 demo seed 시각은 호환을 위해 유지했다. 실제 당일 운영에서는 아래 두 경로를 모두 같은 timezone-aware 서버 시계에 연결해야 한다.

- registry의 `RealEngine(as_of=server_now, budget=기존_LedgerBudget, ...)`: 문자열 생성 당시 시각이 아닌 **호출할 때마다 읽는 함수**를 주입한다. 기존 영속 AI 원장은 그대로 유지한다.
- `services/plans.py::_as_of()` / `_v2_snapshot()` / `_horizon()`: seed 파일이 존재하면 고정 anchor를 읽는 현재 동작을 운영 clock 설정으로 분리한다. 회수 경로는 RealEngine을 우회하므로 첫 항목만 바꾸면 충분하지 않다.

예시 A 생성자용 clock:

```python
from datetime import datetime, timezone

def server_now():
    return datetime.now(timezone.utc).isoformat()
```

데모에서는 양쪽에 같은 명시적 demo clock을 사용한다. 요청이 접수된 과거 시각이나 초안 metadata의 as_of를 확정 시각으로 재사용하지 않는다. 운영 날짜에 맞는 근무표·방문창·travel 데이터를 공급한다(seed 고정 날짜로 실운영을 검증하지 않는다).

## B 필수 연결 3 — 확정 경쟁 방지

기존 confirm의 workspace 잠금 → 최신 revision/현행 계획 확인 → 최신 snapshot 조회 → A 검증 → 원자 저장 흐름을 유지한다. 실행 상태 갱신도 같은 잠금/revision 규칙을 따라야 한다.

- 초안 이후 직원이 출발/완료했다면 기존 revision guard로 409 후 재계산한다. A는 최신 상태와 변경 행을 다시 검사하는 추가 방어를 제공한다.
- revision이 그대로여도 시간이 지나 출발 시각이 과거가 되면 A가 거부한다. `INVALID`/`DATA_MISSING`를 무시하고 저장하면 안 된다.
- v1 `validate(snapshot, candidate_items)`에는 operations가 없다. 따라서 일정 행은 같고 window/due만 바꾸는 요청까지 보호하려면 실행 이벤트 revision 증가가 필수다. B는 확정 시 operations 대상도 이미 IN_PROGRESS/COMPLETED/FAILED인지 확인하여 거부한다. 완료 작업을 수정하려는 최신 사람 해석도 거부한다.
- 신규 납품은 기존 [A_DELIVERY_CONNECTION.md](A_DELIVERY_CONNECTION.md)의 prepare/원자 생성 연결이 먼저 필요하다. prepare와 쓰기는 같은 잠금 안에서 수행한다. 초안은 실제 Job/자산 상태를 변경하지 않는다.

## 화면에서 보여줄 결과

| 코드 | 처리 |
|---|---|
| EXECUTION_STATUS_REQUIRED | 해당 job_ids의 실제 시작/완료 상태 확인 후 재조회. 신규 납품도 violations에 대상 ID 제공 |
| FIXED_JOB_CHANGED / EXECUTION_FIXED_JOB_CHANGED | 이미 실행된/시작된 작업 변경을 차단하고 최신 상태로 재계산 |
| EMPLOYEE_EXECUTION_IN_PROGRESS | 진행 중인 직원에게 추가 배정 불가. 다른 직원·다른 계획 검토 또는 완료 후 재계산 |
| EXECUTION_START_PASSED / DELIVERY_DEPARTURE_PASSED | 초안 유효 시간이 지남. 새 시각으로 다시 계산 |
| EMPLOYEE_CURRENT_TRAVEL_GAP | 현재 시각부터 출발지까지 이동 여유 부족 |
| EMPLOYEE_POSITION_UNCONFIRMED | 실패 작업 이후 직원 위치를 현 계약으로 알 수 없어 추가 배정 보류 |

고정 작업은 비교 화면에서 유지된 이력으로 보여주고 드래그/직원 변경 대상에서 제외한다. `NO_SOLUTION_FOUND`는 현재 지원 범위·탐색 내 후보 없음이며, 전체 일정의 수학적 불가능 증명은 아니다.

## 상태만 사용하는 보수적 한계

실제 완료 순서·현재 GPS·진행 작업의 남은 시간은 입력에 없다. 같은 근무에서 완료된 PlanItem의 종착지 모두를 가능한 현재 위치로 보고 이동을 검사한다. 완료 순서를 예정 시간으로 단정하지 않는다. 완료 구간 밖의 임의 이동은 이 계약이 표현하지 못하므로, 그런 운영에는 직원 위치/available_at의 별도 계약이 필요하다.

실패 작업은 직원 종착지를 알 수 없어 해당 근무의 추가 배정을 차단한다. 현재 계약에 위치 확인을 전달할 필드는 없으므로 UI에서 확인만 했다고 이 오류를 해제할 수 없다. 다음 근무의 명시 시작 위치 또는 후속 위치 계약을 사용해야 하며 실패 이력을 삭제/완료로 위장하지 않는다. 진행 중 직원도 완료 전의 예상 종료를 이용한 추가 예약은 지원하지 않는다. 기존 변경 없는 미래 작업은 보존하지만 실제 실행 가능하다는 완료 예측을 추가하지 않는다.

## 인수 시나리오와 검증 범위

- 오전 완료 + 오후 추가 납품: 오전 직원/장비/시각/구간 및 실제 상태 불변, 새 미래 작업만 생성.
- 예정 종료가 지났으나 IN_PROGRESS: 다른 직원으로 배정, 모두 바쁘면 빈 후보.
- 예정 출발이 지났으나 ASSIGNED: NEEDS_REVIEW, 무저장.
- 초안 이후 시작 이벤트: AS(v1)·회수(v2) confirm 거부, 계획/운영/감사 정보 추가 변경 없음.
- revision 동일 + 출발 시간 경과: 신규 납품 prepare 및 v1/v2 validate 거부.
- 진행 중 장비: 미래 READY/조건부 가용으로 발표하지 않음.

A 시험은 `app/backend/tests/engine/test_execution.py`. 상태 피드백은 합성 snapshot 또는 격리 SQLite의 기존 status 컬럼 갱신으로 재현했다. 실제 직원 이벤트 API/UI·Oracle 동시 잠금·운영 clock/배포 인수는 **B 연결 후 별도 검증**이다. 정확한 실행 결과는 TASKS TEL-054와 [A 기록](A.md)을 따른다.
