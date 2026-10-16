# B 담당 전달 — 신규 납품 자동 배정

2026-10-17 · TEL-053 · `codex/a-new-delivery` · 기준 main `03e7913` (B PR #11 포함).
통합 작업: `/private/tmp/rentwise-a-release-20261017`, 기준 main9666202. 최초 개발 기록은 아래 TEL-053 기준을 따른다.
TEL-056에서 TEL-052 native 회수 adapter·TEL-054 당일 보호·TEL-055 입력 한도와 함께 feat/a-engine-updates에 통합했다. 원래 worktree도 보존한다. 최신 B의 회수 v2 bridge·비용원장·검수 seed를 기준으로 하며 이들을 교체하지 않는다.

## A에서 구현한 것

기존 B v1 `SolverInput`/`SolverResult`/`PlanItem`/`ReservationChange`를 사용한다. 공용 타입 파일·JSON Schema·DB 스키마·외부 API 필드를 바꾸지 않았다.
`NormalizedOperation`이 기존부터 허용하는 extra 필드에 서버 내부 `allocation`과 `return_policy`를 넣어야 한다. **서버 입력 연결은 필요하다.**

```python
engine = RealEngine(budget=existing_ledger, delivery_enabled=True)
result = engine.solve(solver_input)
changes = engine.prepare_delivery_confirmation(
    latest_snapshot, saved_operations, stored_candidate_items, stored_reservation_changes,
    request_id=stored_plan.request_id, input_hash=stored_plan.input_hash,
)
```

기본 `delivery_enabled=False`는 유지한다. 기본 생성자/직원·AS 경로 및 B의 기존 회수 v2 경로는 그대로다.
생성 플래그만 켜면 부족하다. 아래 정규화·초안 표시·확정 저장을 함께 연결해야 한다.
계산/재검증은 DB·네트워크·LLM·캐시를 사용하지 않는다. 기존 네 메서드 서명은 유지한다.

- 기존 `CREATE DELIVERY` 요청 1건/장비1대를 배정한다. 기존 고객·품목·방문창·완료 기한·수량이 필요하다.
- 같은 품목 장비와 활성·자격 직원, 방문 시작 후보를 탐색한다. 장비 개체를 명시하면 그 개체만 사용한다.
- 직원 근무/휴식/앞뒤 이동·창고 복귀, 고객 방문창, 기존 약속, 실제 장비 위치·준비·예약·의존을 전체 계획에서 검사한다.
- 기본 경로는 창고→고객 현장→창고다. 출고 출발부터 예약을 잡는다. 준비는 출발 전에 끝나야 한다.
- 창고 READY 또는 기존 예약 release/PREP가 명시된 조건부 장비만 사용한다. 고객에 있는 장비는 기존 PICKUP→RETURN_TO_PREP 연결도 필요하다. 회수·준비를 새로 만들거나 미루지 않는다.
- 기존 작업의 시간·장비·조건은 유지한다. 명시 직원 override 최대3개만 별도로 적용·검증한다.
- 유효안 중 고객 선호 직원→준비 의존 없는 장비→기존 직원 변경 수→이동분→빠른 방문/안정 ID 순으로 고른다. 우선순위 UNKNOWN은 B의 기존 NORMAL 정책으로 처리하고 원래 해석/evidence를 바꾸지 않는다.
- 자동 시각은5분 격자, 창 폭=작업시간인 명시 고정시각은 그대로 검사한다. 최대1000후보/2000ms cooperative 제한이다. 검사/직렬화 한 번의 비용은 제한을 넘길 수 있으며 전역 최적해를 보장하지 않는다.
- 실패/미지원/결손은 빈 후보·빈 예약 변경과 사유를 반환한다. 탐색 미발견은 불가능 증명이 아니다. 제한 전에 유효안을 찾으면 FEASIBLE + limit_reached=true일 수 있다.

### 대여와 점유

신규 Rental은 PLANNED, actual_start/actual_end=null이다. Asset 물리 상태/위치를 바꾸지 않는다.
`FIXED`는 실제 반납이 아닌 expected_return_at만 설정한다. 인도 완료보다 빠른 대여 종료는 거절한다.
**회수·준비 release가 없는 신규 대여의 예약 end_at은 FIXED여도 null(무기한)**이다. 따라서 horizon 밖 미래 예약도 충돌하면 배정하지 않는다. 단순히 rental_end_at에 재고가 준비된다고 간주하지 않는다.

예시: C-S / PR-A / 1대 / 2026-10-16 방문15:00~15:15 / 기한17:00.

| 항목 | 결과 |
|---|---|
| 직원·장비 | E1 / P02 |
| 경로 | 14:40 창고 출발 → 15:00~15:15 현장 → 15:35 창고 복귀 |
| 생성 | B가 발급한 ID로 Job1개·PLANNED Rental1개·ACTIVE Reservation1개 |
| 예약 | 14:40부터 무기한 점유; 확정 plan_id 연결 |
| 기존 계획 | 시간·장비·약속 그대로 |

## B 연결 1 — 서버 정규화와 활성화

`services/plans.py::create_plan`에서 기존 HUMAN 해석/미확인 필드·revision 검사를 먼저 수행한다.
`_normalize` 결과에서 CREATE DELIVERY만 처리하고, **canonical_hash를 계산하기 전에** 아래 내부 값을 넣는다.
ID는 B가 요청ID+해석revision+operation index 등에서 안정적으로 발급한다. 재계산 시 같은 ID를 사용하고 DB/현재 snapshot과 충돌하지 않아야 한다. 각 ID는64자 이하의 영문/숫자/`_.:-`이며 서로 달라야 한다.
권장 발급은 종류 접두사+32자리 hash 등 짧은 ID다. 기존 `PI-{plan_id}-{job_id}`도64자 이내인지 검사하고, 길면 B가 plan/행 ID를 hash로 발급해야 한다. A는 plan/행 ID를 생성하지 않는다.

```python
# 기존 NormalizedOperation 객체에 서버가 붙이는 내부 extra 필드.
# payload/AI evidence/브라우저에서 allocation을 받아 복사하지 않는다.
op.allocation = {
    'job_id': allocated_job_id,
    'rental_id': allocated_rental_id,
    'reservation_id': allocated_reservation_id,
    'dependency_id': allocated_dependency_id,  # 준비 의존이 필요할 때만 생성에 사용
}
op.return_policy = reviewed_return_policy  # FIXED 또는 OPEN_ENDED
```

`rental_end_at != null`이고 사람이 확인한 날짜이면 FIXED다. null만 보고 OPEN_ENDED를 자동 선택하면 안 된다.
반납 미정은 사람이 그 정책을 명시 선택하고 확인 이력에 남긴 경우만 OPEN_ENDED로 전달한다.
현재 폼은 반납 미정 편집/확인 경로가 부족하므로 연결 전에는 종료일을 명시한 납품부터 인수한다.
반납 미정 UI를 추가할 때 null도 확인 완료로 판정하는 선택 상태와 서버 검사를 함께 구현해야 한다. 단순 `filled(null)=true`나 확인 질문 제거로 처리하면 안 된다.
AI 후처리 `b_review.py`는 현재 화면이 다룰 수 없는 대여 종료·고객 질문을 AI_REVIEW_UNSUPPORTED로 차단한다. 새 편집 UI가 준비되면 A의 허용 필드도 함께 검토해야 한다.

이 값을 포함한 `o.model_dump()`로 B의 기존 canonical_hash를 계산하고 operations_json에도 그대로 저장한다.
engine_registry의 기존 `LedgerBudget()` 주입을 유지하면서 `delivery_enabled=True`를 추가한다.
B `v2_bridge.supports`는 기존 회수 전용 그대로 둔다. CREATE를 그쪽으로 보내면 현재 `_apply_v2`가 Job/Rental INSERT를 하지 않으므로 납품 생성이 완성되지 않는다.

## B 연결 2 — 초안 메타데이터와 비교 표시

FEASIBLE 응답 후, 운영 상태에 쓰기 전에 같은 snapshot/operations/result로 prepare_delivery_confirmation을 호출해 VALID인지 검사한다.
새 Job/Rental/Reservation을 이때 운영 테이블에 INSERT하면 안 된다.
후보 PlanItem은 기존처럼 B가 plan/행 ID를 붙여 저장할 수 있다. plan_items.job_id는 현재 스키마에서 FK가 아니다.

```python
from rentwise.engine.delivery import VERSION as DELIVERY_VERSION

if result.solver_version == DELIVERY_VERSION and result.status == 'FEASIBLE':
    changes = engine.prepare_delivery_confirmation(
        snapshot, ops, result.candidate_items, result.reservation_changes,
        request_id=request_id, input_hash=input_hash,
    )
    # VALID가 아니면 422/명시 오류로 종료; READY 초안으로 저장하지 않는다.
    meta['delivery_job_creates'] = changes.job_creates
```

`plan_view`는 운영 jobs 조회에 없는 신규 job_id의 kind/site를 알 수 없다. `meta.delivery_job_creates`를 jobs lookup에 overlay한 뒤 기존 diff를 만든다. API DTO를 바꿀 필요는 없다. 이것은 표시용 메타데이터이며 확정의 신뢰 원본으로 사용하지 않는다.
기존 meta.result 반환의 허용 필드 목록을 유지해 내부 생성 데이터가 화면에 그대로 노출되지 않게 한다.

## B 연결 3 — 기존 confirm 트랜잭션

workspace 잠금·READY/status/plan revision/state_revision/중복 확정·멱등 처리를 유지한다.
확정 시 현재 HUMAN 해석이 plan의 interpretation_revision과 여전히 일치하는지도 검사한다. 기존 confirm은 이 비교가 없으므로 계산 후 요청 재수정 사례를 인수해야 한다.
잠금 안에서 최신 snapshot을 읽고, DB의 operations_json/전체 후보/result_json 예약 변경과 plan.request_id/input_hash를 넘긴다. 모델·재탐색을 실행하지 않는다.

```python
if p.solver_version == DELIVERY_VERSION:
    changes = get_engine().prepare_delivery_confirmation(
        snapshot, json.loads(p.operations_json or '[]'), cand,
        meta.get('reservation_changes', []),
        request_id=p.request_id, input_hash=p.input_hash,
    )
    vr = changes.validation
    # 기존 VALID 이외 -> 422 CONSTRAINT_VIOLATION / 전체 무저장
elif meta.get('v2_candidate') is not None:
    # 현재 B 회수 경로 유지
    ...
else:
    # 현재 B 직원/AS 경로 유지
    ...
```

VALID일 때 다음 반환값을 같은 트랜잭션에 저장한다. 생성분은 요청이나 초안 표시 메타데이터에서 받지 않고 **방금 재계산한 반환 객체만** 사용한다.

| 반환값 | 처리 |
|---|---|
| job_creates | Job INSERT. asset_ids→asset_ids_json(J), 시간4필드→to_db, revision=1 |
| rental_creates | Rental INSERT. 실제/예정 시각3필드→to_db, PLANNED/실제null 유지 |
| dependency_creates | 필요한 PREP→신규 납품 ASSET_REUSE 의존 INSERT (없으면 생략) |
| reservation_changes | CREATE 예약 INSERT. plan_id는 확정 plan ID로 덮어쓰고 시간→to_db |
| job_updates | 명시 직원 변경이 있는 기존 Job의 revision+1. 직원 배정 자체는 저장된 PlanItem에 있음 |

신규 납품 분기는 기존 Job UPDATE 반복문 및 `_apply_v2`와 중복 적용하지 않는다. 기존 작업/대여/예약/의존을 전부 덮어쓰거나 지우지 않는다.
끝에 현재 B `_finish_confirm`으로 현행 계획·revision+1·요청상태·감사 기록을 처리한다. 모든 쓰기가 성공한 뒤 한 번 커밋하고 예외는 전체 롤백한다.
실제 변환 예제: `tests/engine/test_delivery.py::reference_write`. 이것은 격리 시험용 adapter이며 B의 권한/승인/revision/멱등 가드를 대체하지 않는다.
비활성 상태에서 기존 신규 납품 초안을 확정하면 DELIVERY_NOT_ENABLED로 무저장 차단한다.

## 검증과 인수 범위

- 최신 main 기준 기존 backend190개 PASS 후 A 신규66개 추가, 전체 **256개 PASS**. 전체 검증 결과는 [A 인수인계](A.md)의 TEL-053 기록을 따른다.
- 새 engine 인스턴스·기존 Result JSON 왕복·B 발급 plan/행 ID로 재검증 가능하며 입력을 변경하지 않는다.
- 순수 계산의 정상/선호 직원 휴식 대체/조건부 준비/미래 예약/대여 정책·인도 시각/시간·후보 상한/위조 후보·예약 delta/상태 변경을 검증했다.
- HTTP 초안 시험에는 **서버 정규화 대역**으로 B 발급 allocation/정책과 opt-in engine만 주입했다. 초안 저장·조회는 되지만 기존 화면 조회의 신규 kind/site=null 한계와 미수정 confirm422/무저장을 확인했다.
- 격리 SQLite에서는 준비 완료 및 조건부 장비 모두 생성분 저장→기존 `_finish_confirm`→새 엔진 VALID/가용 재조회, Job 생성 직후 또는 finish 이후 예외→전체 롤백을 검증했다. 운영 DB/브라우저/실제 B 연결 성공으로 확대하지 않는다.
- 새 유료 LLM 호출 없음. 기존 B의 GPT 비용원장/회수 연결 시험도 전체 회귀에 포함한다.

B 인수 시 확인할 사항:

1. 실제 웹에서 종료일 명시 신규 납품→사람 확인→새 업무 종류/현장·직원·장비 표시→confirm200→Job/Rental/Reservation/의존 및 현행 계획 재조회.
2. 계산 후 요청/해석 수정·state 변경은409 또는 재계산, 새 예약/수리/직원 달력 충돌은422/무저장.
3. 같은 멱등 키 재요청은 동일 응답, 중복 확정/오래된 revision은409, 저장 도중 예외는 전 생성분 롤백.
4. 기존 직원/AS·회수 v2·mock 회귀, 운영 Oracle/동시 확정, 반납 미정 UI/확인 이력 인수.
