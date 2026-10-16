# A 엔진의 공용 v2 계약 (B 통합 검토 대기)

기존 `rentwise.contracts.types`의 B v1 Pydantic DTO와 mock/API는 유지한다.

TEL-048: B의 무인자 `RealEngine()`은 기존 v1 계약만 사용한다. B 변경이나 추가 context/DTO를 요구하지 않는다.
직원 변경·기존 방문창 안 AS 시각 조정만 자동 적용하며 회수 지연/개체 대체/신규 작업은 확인필요다.
아래 v2는 별도 직접 호출용 core이며 B v1의 계약을 대체하지 않는다.
최신 연결 범위는 [A 인수인계](../../../../../docs/handoffs/A.md)를 따른다.
A core는 `rentwise.contracts.v2`의 JSON dict 계약만 사용하며 v1 bundle을 거부한다.
이 버전 경로는 공용 계약의 단일 정의이며 엔진 안에 DTO를 복제하지 않는다.
B가 계약 변경을 병합하고 A·C가 의미를 확인해야 한다.

- `types.py`: TypedDict / 향후 EnginePort 서명. interpret는 아직 미구현이다.
- `schemas/bundle.json`: 필수 필드·enum·nullable의 기준.
- `schema.py`: 이 bundle에서 사용하는 JSON Schema 부분집합 검사. 범용 schema 구현은 아니다.
- `normalize.py`: B가 사람 확인한 patch를 완전한 Job으로 만드는 helper.
- `serialization.py`: B와 A가 공유하는 canonical input hash.

## R1: 전체 후보

CandidatePlan (`rental.candidate.v2`)의 필수 키:
`schema_version,bundle_version,base_state_revision,plan_id,approved_job_ids,jobs,plan_items,reservations,rentals,dependencies`.
Job/PlanItem/Rental/Dependency는 최종 전체 배열, reservations는 확정 후 유효할 ACTIVE 전체 예약이다.
기간 밖 겹치는 점유도 유지한다. candidate_items는 candidate_plan.plan_items와 같고 reservation_changes는 파생 delta다.
B는 최신 snapshot 및 이 전체 후보로 validate한 뒤 **검사한 동일 후보**를 원자적으로 저장해야 한다.
PlanItem 목록만 검증하거나 저장하면 대여·준비 의존·예약의 검사가 빠진다.
운영 Asset 및 Rental actual_*은 계획 결과로 덮어쓰지 않는다.

`approved_job_ids`는 B 서버의 저장된 확인 이력에서 구성한다. 브라우저/모델 값을 그대로 신뢰하지 않는다.
승인된 변경에도 자격·중복·방문창 제약은 적용된다. 잠금 안 revision 검사는 B의 책임이다.

## R2: 사람 확인을 마친 정규화 operation

NormalizedOperation (`rental.operation.v2`) 필수 키:
`schema_version,operation,target_job_id,job,prep_job,rental_id,return_policy,confirmed`.
job은 완전한 Job, prep_job은 완전한 PREP 또는 null이다.
CREATE의 target_job_id는 null, RESCHEDULE은 기존 job.id와 같다.
미언급 필드만 원본에서 상속하며 명시한 null/빈 값은 상속 신호로 사용하지 않는다.
return_policy는 FIXED/OPEN_ENDED/NOT_APPLICABLE이며 미정 종료는 명시 확인한 정책이어야 한다.
confirmed=true와 서버의 승인 목록이 있어야 탐색한다. 신규 ID는 B가 발급한다.

## R3: TRANSFER의 두 방문

Job.window_start/end는 출발지 인수 SERVICE 전체의 창,
destination_window_start/end는 목적지 인도 SERVICE 전체의 창이다(다른 업무에서는 null).
Item.transfer_service_minutes={pickup,delivery}는 각각 양의 분이다.
한 직원/동일 개체의 SERVICE→TRAVEL→SERVICE 연속 block이며 양쪽 Customer.visit_windows도 만족한다.
due_at은 인도 종료기한이다. Item.direct_transfer_allowed와 Job.direct_transfer_confirmed가 모두 필요하다.
기존 예약을 인수 완료에 닫고 새 예약을 같은 시각부터 연결한다. 준비/재고 증가는 추정하지 않는다.
독립 validator는 이 계약을 검사하지만 현재 solver는 신규 TRANSFER를 생성하지 않는다.

## SolverInput / Result

`rental.bundle.v2`, `rental.solver.v2`, `rental.solver-result.v2`를 사용한다.
Snapshot은 `rental.snapshot.v2`와 state_revision/as_of/dataset_version/policy_version/travel_version/horizon_start/end,
12개 엔티티 배열을 모두 포함한다. as_of는 B가 제공하며 A는 현재시각을 읽지 않는다.

SolverInput은 request_id/request_revision/interpretation_revision, 새 plan_id/base_plan_id,
base_state_revision, 버전/horizon, 정규화 operations, approved_job_ids, snapshot, overrides,
id_allocations, input_hash, max_search_ms/max_candidates를 받는다.
정확한 필수 키는 schema의 SolverInput을 따른다.

`id_allocations`:

```json
{
  "plan_items": [{"job_id": "JOB-ID", "id": "NEW-PLAN-ITEM-ID"}],
  "reservations": [{"rental_id": "RENTAL-ID", "id": "NEW-RESERVATION-ID"}],
  "dependencies": [{"job_id": "DELIVERY-JOB-ID", "id": "NEW-DEPENDENCY-ID"}]
}
```

전체 취소되지 않은 Job/유효 예약별 ID를 B가 미리 발급한다. dependency.job_id는 후속 DELIVERY다.
위 JSON은 ID 구조 예시이며 전체 실행 입력이 아니다.
신규 Rental ID는 operation.rental_id에서 받는다. 기존 운영 ID 재사용/중복/배정 누락은 거절한다.

`solver_input_hash(input)`는 input_hash를 제외한 canonical JSON의 **접두사 없는 64자리 SHA256**이다.
객체 key 정렬·UTF-8·공백 없음, snapshot 엔티티는 id, travel_times는 from_id/to_id로 정렬한다.
그 외 배열의 의미 순서는 유지한다. B v1의 `sha256:` hash와 호환되지 않는다.

FEASIBLE에는 독립 validate를 통과한 전체 후보가 필요하다.
실패 결과에는 candidate_plan=null, candidate_items/reservation_changes=[]로 확정 가능한 부분안을 남기지 않는다.
NEEDS_REVIEW/DATA_MISSING/NO_SOLUTION_FOUND/PROVEN_INFEASIBLE을 구분한다.
탐색 실패·한도 도달을 불가능 증명으로 취급하지 않는다.

## 실행 가능한 합성 예시

저장소의 backend 개발 의존성 설치 후 `app/backend`에서:

```sh
python - <<'PY'
from rentwise.engine import solve, validate
from tests.engine.sample import snapshot
from tests.engine.solver_sample import solver_input, normal_operation, delay_operation
for make_operation in (normal_operation, delay_operation):
    snap = snapshot()
    request = solver_input(snap, [make_operation(snap)])
    result = solve(request)
    assert result['status'] == 'FEASIBLE', result
    assert validate(snap, result['candidate_plan'])['status'] == 'VALID'
    print(make_operation.__name__, result['status'], result['affected_job_ids'])
PY
```

위 helper의 ID 발급/승인은 합성 시험 전용이며 실제 B의 권한·DB 저장을 대체하지 않는다.
C seed/gold나 AI 모델을 호출하지 않는다. 서비스 연결 작업은 [A 인수인계](../../../../../docs/handoffs/A.md)를 따른다.
