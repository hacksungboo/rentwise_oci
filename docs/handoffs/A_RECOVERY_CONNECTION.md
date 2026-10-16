# B 담당 전달 — 회수 지연 복구 연결

2026-10-17 · TEL-052/056 · 통합 기준 main `9666202`, 작업 `feat/a-engine-updates`.

**현재 B는 회수 지연을 기존 `services/v2_bridge.py`로 계산·확정한다. 이 경로는 그대로 유지한다.** 아래 native v1 recovery는 밀린 A 구현을 보존한 선택적 adapter이며, 현재 웹 회수 지연을 위해 새로 활성화할 필요가 없다. 선택적으로 사용할 때만 별도 confirm 훅이 필요하다. 이전 main9ab0c25의 미연결 설명을 현재 B 전체 상태로 해석하지 않는다.
이 문서는 구현된 A 코드의 연결 명세다. B 서비스·UI·DB·배포는 변경하지 않았다.

## A 구현과 범위

`RealEngine(recovery_enabled=True)`는 **기존 단일 장비의 회수 지연 1건**을 받는다.
기존 B `SolverInput`/`SolverResult`, snapshot, normalized RESCHEDULE PICKUP을 사용한다.
새 공용 DTO/DB 컬럼/HTTP API/의존성이 없다. 해석/계산/사람 확정은 기존 단계 그대로다.
LLM 호출은 계산·확정 함수에 없다. 기존 AI 운영 연결은 [별도 문서](A_AI_CONNECTION.md)를 따른다.

- 회수 현장 작업·왕복 이동, 연결된 창고 준비를 다시 계산한다. 준비는 창고 도착+의존 최소 간격부터 시작한다.
- 후속 납품 시간은 유지한다. 원래 장비로 가능하면 우선하고, 불가능하면 동일 품목의 창고 준비 완료 장비를 탐색한다.
- 직원 기술/활성·근무·휴식·이동·고객 방문창·기한, 물리 상태/예약/준비/의존 순서를 전체 후보에서 검증한다.
- 대여·예약 연결이 없는 데이터를 새로 만들지 않는다. 기존 ACTIVE 회수 대여와 PLANNED 후속 대여가 필요하다.
- 후보는 전체 기존 계획이다. 자동 영향 범위는 회수·준비·납품 최대3개다. 명시 직원 override 최대3개는 별도 반영·검증한다.
- 탐색은 최대1000후보/2000ms, 방문 시작을 요청 창 안에서5분 간격으로 탐색한다. 가능한 후보 중 대체 횟수→직원 변경 수→안정 정렬 순으로 고른다. 전역 최적해를 보장하지 않는다.
- 새 작업/다개체/TRANSFER/복수 지연/검토 필요 예약/시작·완료된 영향 작업은 자동 복구하지 않는다.
- 탐색 실패는 빈 후보·빈 예약 변경과 사유를 반환한다. 제한 초과는 불가능 판정이 아니다.

### 예시 (원본 B 개발 seed)

사람 확인 조건: J-PICK1 방문14:00~14:10, 창고 복귀 기한17:00.

| 항목 | 계산 결과 |
|---|---|
| 회수 | E2, 13:40 출발 → 14:00~14:10 현장 → 14:30 창고 |
| 창고 준비 | J-PREP1, 14:30~15:00 |
| 기존 정오 납품 | J-DEL1, 동일 모델 P02 사용, 12:00~12:15 약속 유지 |
| 회수 대여 R-H | expected_return_at=14:10 (현장 회수 종료; 창고 준비 종료와 구분) |
| 후속 대여 R-S2 | 예정 asset_id=P02 |
| 예약 | RS-H 종료15:00으로 교체, RS-S2는 P02 예약으로 교체 |
| 의존 | 대체한 납품의 D-PREP1-DEL1만 제거; RETURN_TO_PREP 유지 |

P04는 미래 예약이 있으므로 종료 미정 납품 대여의 대체로 쓸 수 없다.
확정은 예정값만 바꾼다. Asset 물리 상태·위치, Rental actual_start/actual_end/status는 바꾸지 않는다.
현재 B 개발 seed의 AS2 담당은 E2로 수정되어 있다. native adapter 시험은 예전 명시 E2 override도 호환한다. A가 seed를 다시 수정하지 않는다.

## B 필수 연결 — 생성 1곳, 확정 1곳

기본 `RealEngine().solve` 직접 호출은 회수 지연을 NEEDS_REVIEW로 반환한다. B 웹 서비스는 기존 v2 bridge를 따로 호출하므로 기본 설정에서도 회수 지연 계산·확정이 된다.
**생성 플래그만 켜서는 웹 확정이 되지 않는다.** 기존 2인자 validate는 회수·준비 변경을 계속 거부한다.
아래 두 연결을 함께 적용하고 검증한 뒤 활성화한다. 승인된 조건을 검증하기 위해 기본 validate를 완화하면 안 된다.

### 1. engine_registry.py

기존 real 생성 지점에 `recovery_enabled=True`를 추가한다. 기존 budget adapter가 있다면 그대로 함께 주입한다.
mock에는 적용하지 않는다. 환경 변수만으로 이 플래그가 켜지는 구현은 없다.

### 2. services/plans.py confirm

기존 workspace 잠금·plan/status/revision·중복 확정 검사를 모두 유지한다.
잠금 안에서 읽은 최신 snapshot, DB 후보 전체, 저장 operations와 result_json 예약 변경을 A에 넘긴다.
재탐색/모델 호출 없이 순수 재검증으로 저장 변경분을 계산한다. 반환 객체를 요청 입력으로 받으면 안 된다.

```python
from rentwise.engine.recovery import VERSION as RECOVERY_VERSION

# 기존 잠금/버전 검사 이후; p는 DB에서 읽은 plan, cand는 기존 _items 결과.
engine = get_engine()
meta = json.loads(p.result_json or '{}')
changes = None
if p.solver_version == RECOVERY_VERSION:
    changes = engine.prepare_confirmation(
        snapshot, json.loads(p.operations_json or '[]'), cand,
        meta.get('reservation_changes', []), input_hash=p.input_hash,
    )
    vr = changes.validation
else:
    vr = engine.validate(snapshot, [PlanItem(**row) for row in cand])

# 기존 vr.status != VALID -> 422 CONSTRAINT_VIOLATION 유지.
```

유효한 회수 복구일 때 기존 예약 교체 반복문과 작업 갱신 부분을 아래 반환값으로 처리한다.
기존 AS/직원 변경 경로는 현재대로 둔다. 모든 쓰기는 같은 기존 confirm 트랜잭션 안에서 수행한다.

| 반환값 | 저장 처리 |
|---|---|
| `job_updates[job_id]` | asset_ids→asset_ids_json, 시간 필드→to_db; 각 작업 revision+1. **기존 작업 반복문과 중복 적용하지 않는다** |
| `rental_updates[rental_id]` | asset_id 또는 expected_return_at만 갱신; 시간은 to_db |
| `dependency_deletions` | 반환된 dependency ID만 삭제. successor 전체를 지우지 않는다 |
| `reservation_changes` | 기존 REPLACE 저장 그대로: old_id SUPERSEDED + 새 ACTIVE 예약 INSERT, plan_id는 확정 plan ID로 지정 |

예약 변경은 재계산한 `changes.reservation_changes`를 사용한다. 입력 delta와 정확히 같아야 A가 VALID를 반환한다.
새 예약 ID는 `RS-` + sha256(input_hash + ':' + old_id)의 앞40자리로 결정적이며64자 이하다.
과거 SUPERSEDED 예약은 옛 asset_id를 유지한다. ACTIVE 예약과 현재 Rental의 asset_id 일치 검증은 계속 적용한다.
연결을 끈 상태에서 예전 복구 초안을 확정하면 RECOVERY_NOT_ENABLED로 막힌다.

그 뒤 현행 계획 교체·state_revision+1·request CONFIRMED·감사 기록·기존 멱등 처리는 그대로 실행한다.
부분 커밋/별도 Rental 트랜잭션은 금지한다. 실패하면 전체 롤백한다.
구체적인 SQLAlchemy 변환 참고: `tests/engine/test_recovery.py::_reference_write`.
이 함수는 **격리 SQLite 시험용 예제**이며 revision/감사/HTTP 멱등 가드를 대체하지 않는다.

## 화면과 검증

현재 B 초안 생성·조회는 DTO 변경 없이 READY/diff/impact_edges/reservation_changes를 처리한다.
기존 원문→해석→사람 확인 폼을 유지한다. 모델/예산 미연결은 회수 solver 구현과 별개다.
새 회수 기한은 사람이 확인해야 한다. 원래 기한보다 늦은 회수에 기존 기한을 자동 승인하지 않는다.

원래 TEL-052 검증은 신규56개 포함242개였고, 최신 B/전체 A 통합 검증은362개 PASS다. native recovery의56개 시험도 포함한다. HTTP native 경로 시험은 v2 bridge 선택을 시험에서만 비활성화하며, 별도 기존 B v2 HTTP 성공 회귀를 함께 유지한다.
HTTP 초안·비교 성공과 **미수정 confirm의422/무저장**을 확인했다.
참고 저장 adapter로 전체 변경분 커밋→새 엔진 validate VALID/가용 재조회와 중간 예외→전체 롤백도 확인했다.
실제 B confirm 연결 성공, 운영 Oracle/행 잠금·동시성, 브라우저·배포는 아직 검증하지 않았다.

B 인수 시 필수 확인:

1. 실제 confirm200 뒤 Job/Rental/Reservation/Dependency/현행 계획을 재조회해 위 예시와 일치.
2. 같은 멱등 키 재요청은 동일 응답, 새 키 중복 확정·오래된 revision은409.
3. 계산 뒤 장비 상태·예약·작업이 바뀌면 재계산 또는422/409로 전체 무저장.
4. 저장 중 예외 시 모든 변경 롤백; 기존 AS/직원 변경·mock 회귀 유지.
5. 기존 B 비용원장/v2 회수 연결을 유지하고 실제 브라우저/운영 Oracle에서 선택한 경로를 인수한다.


## TEL-056 당일 보호 통합

`RealEngine.prepare_confirmation`은 fresh clock을 읽어 native recovery에도 TEL-054의 과거 미시작·진행 직원·고정 작업 보호를 적용한다. 직접 `recovery.prepare_confirmation`을 쓰면 `as_of`를 반드시 전달해야 한다. 기존 두 인자 validate는 회수 변경을 자동 허용하지 않는다. 동시 `recovery_enabled=True, delivery_enabled=True`도 업무별 dispatch하며 혼합 요청은 부분 적용하지 않는다. 현재 B v2 bridge에는 이 플래그가 필요 없다. 기존 BudgetPort 주입은 유지한다.
