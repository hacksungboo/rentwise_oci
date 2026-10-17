# 내부 직원이 없는 배송·회수 변경안

2026-10-17 · TEL-063/064 · 기준 main `a4081bb` · `ENGINE_MODE=real`.

## 사용자 동선

기존 요청 입력/해석 → 사람이 대상·방문창·기한 확인 → 변경안 계산 → 책임자 확인·확정이다. 단일 요청과 순차 처리 대기열에 같은 정책을 적용한다.

| 조건 | 제안 | 확정 전후 |
|---|---|---|
| 내부 직원으로 유효한 계획을 찾음 | 내부 직원 배정 우선 | 기존 흐름 |
| 배송 변경에 내부 직원이 없음 | 배송 작업 전용 퀵 계획 자원에 배정 | `퀵 배정 제안 · 호출 필요`; 실제 업체 호출·수락·결제는 별도 |
| 당일 회수 변경에 내부 직원이 없음 | 고객 방문창과 직원 근무표가 있는 다음 날짜를 탐색 | 회수 날짜·시간·완료 기한 변경, 준비와 후속 납품을 함께 검증한 뒤 제안 |
| 장비·준비·방문창·기한·데이터 조건을 만족 못함 | 미해결 유지 | 기존 확정 일정 표시, 확정 차단 |

여기서 근무일은 주말 여부를 추측하지 않고 **등록된 해당 업무 자격 직원의 근무표와 고객 방문 가능 시간**으로 판단한다. 주말도 둘 다 열려 있으면 제안할 수 있다. 조회 범위는 현재 7일 지평 안의 다음 1~6일이며, 그 안에서 완전한 계획을 못 찾으면 미해결로 남긴다. 미래 회수와 직원 수동 지정 요청에는 자동 연기를 적용하지 않는다.

## 계산·저장 계약

- `engine/solver.py`: 기존 PICKUP 변경과 신규 납품 순수 엔진에 **기존 DELIVERY 변경**을 추가했다. 기존 납품의 PLANNED 대여/예약 연결을 확인하고 실제 대여 값은 보존한다. 아직 시작하지 않은 예약의 출발 시각 변경은 승인된 기존 납품과 정확히 연결될 때만 허용한다. 과거·ACTIVE 대여·기간 외 예약 보호는 유지한다.
- `engine/staff.py`: 기존 직원 경로 검사를 공유한다. 현장 작업, 출발/복귀 이동, 근무 종료·휴식·기존 일정·고객창·기한을 모두 확인해 `인력 없음`과 `방문 자체 불가`를 구분한다. 후속 납품의 고객 약속은 기존 SERVICE 시각으로 고정한다.
- `services/dispatch_fallback.py`: 정상 계획부터 시도한다. 탐색 실패와 별도 인력 검사가 모두 충족될 때만 대안을 시도하고, **모든 후보를 독립 validator로 검증**한다. 회수 연기 시 연결된 PREP의 종료 가능 창·기한도 제안 날짜로 확장하고 변경 승인을 요구한다. 후속 납품은 약속 시각을 유지하며 같은 모델 장비 대체가 가능해야 한다.
- 퀵은 `QK-` + 작업 ID의 SHA256 앞 24자리로 만든 배송별 전용 자원이다. 전용 근무표 `QS-...-YYYYMMDD`는 그 날짜 00~24시의 **계획 가정**이다. 외부 업체의 실제 가용성·자격·요금·수락을 검증한 뜻이 아니다. 다른 배송/회수/AS로 재사용할 수 없으며, 다음 정상 탐색에서도 내부 직원보다 먼저 선택되지 않는다.
- 초안에는 후보와 퀵 자원 메타데이터만 저장한다. 운영 employees/shifts/jobs/reservations/rentals/dependencies는 바꾸지 않는다. 확정 시 기존 workspace 잠금, 최신 HUMAN 해석, revision, 독립 재검증 후 자원 삽입과 기존 완전 후보 저장·revision+1을 같은 트랜잭션으로 수행한다. 실패하면 자원 삽입도 롤백한다.
- 기존 employee/shift 표를 사용하므로 DB 스키마·마이그레이션·새 환경변수·패키지·실제 퀵 API는 추가하지 않았다. 확정 후에도 자원 이름의 **호출 필요**를 유지한다. 호출 완료 관리와 실제 실행 상태 갱신은 이번 범위 밖이다.
- 순수 solve 1단계당 기존 2초·1000후보·변경 영향 3건 제한을 유지한다. 대안 파이프라인은 최대 14단계이며 여러 날짜/방문창을 검사하므로 HTTP 전체가 2초 이내라는 보장은 없다. 결과 `search_stats`는 단계 합산 후보 수·전체 경과 시간·한도 도달 여부이다. 한도에 걸린 실패를 불가능의 증명으로 표시하지 않는다.

버전: `solver_version=rental-solver-normal-delay-v2-1`, v1 `rental-solver-b-v1-4`, 내부 `dispatch_policy_version=dispatch-fallback-v1`. AI 해석/설명 프롬프트·가격·예산은 변경하지 않았다. 대안 생성에는 모델을 추가 호출하지 않는다.

## API·화면 연결 (B 검토 사항)

경로와 입력 형식은 기존 `POST /plans`, `POST /request-queues/{id}/plan`, `POST /plans/{id}/confirm`을 그대로 쓴다. PlanView의 선택 필드만 추가했다.

```json
{
  "fallbacks": [
    {"kind": "QUICK", "job_id": "J-DEL1", "status": "CALL_REQUIRED", "notice": "계획용 퀵 배정…"},
    {"kind": "PICKUP_NEXT_WORKDAY", "job_id": "J-PICK1", "old_window_start": "…", "window_start": "…", "window_end": "…", "due_at": "…", "notice": "회수 날짜·방문 시간·완료 기한 변경…"}
  ],
  "preview_employees": [{"id": "QK-…", "name": "퀵서비스 · 호출 필요 (J-DEL1)"}]
}
```

화면은 pending 퀵을 별도 타임라인 행에 배치한다. 회수·준비 변경 카드는 전후 날짜를 표시하며 상단에서 제안 방문창과 새 기한을 확인한다. 날짜 이동 버튼으로 다음날 미리보기와 확정본을 조회한다. 확정 버튼은 **대체 배정·변경 일정 확인하고 확정**이다. 이 버튼은 실제 업체 호출을 수행하지 않는다. 공용 EnginePort/DTO와 운영 스키마는 유지했다.

B 후속: 변경된 `services/plans.py`, `v2_bridge.py`, 신규 정책 service와 Vue 표시를 함께 리뷰·배포한다. 별도 B 구현 없이 이 브랜치에 화면/API 저장 연결을 포함했다. 실제 업체 호출을 붙이려면 제공사 가용성/품목 운송 자격/수락/요금·호출 상태 및 실패 보상 처리를 별도 설계해야 한다. 운영 Oracle/다중 서버 인수와 운영 반영은 미수행이다.

## busy-v1에서 전체 일정이 사라져 보인 원인 (TEL-063)

원본 busy 운영 seed는 현행 계획 169건이다. 기존 v1 검증기가 10월19일 `J-TRF1`의 출발 고객 창을 두 번째 도착 방문에도 적용해 `VISIT_WINDOW`를 잘못 반환했다. B bridge와 R3 계약은 출발·도착 창을 구분한다. v1도 기존 두 번째 SERVICE 시작~납품 기한을 도착 창으로 검사하도록 맞췄다. 출발창/양쪽 고객창/도착 기한과 고정 시각 제약은 유지한다.

미해결 결과는 후보 0건인데 API가 현행 169건과 비교해 169개 삭제 diff를 만들고 화면이 이를 미리보기로 적용했다. 실제 운영 DB 삭제는 재현되지 않았다. 이제 비FEASIBLE 결과는 부분 후보 저장·diff를 만들지 않으며, 화면도 READY+FEASIBLE+현재 revision일 때만 후보를 적용한다. 불가능한 요청은 오류를 보이면서 현재 일정과 비활성 확정 버튼을 유지한다.

같은 개발용 AS 요청: 수정 전 UNRESOLVED/삭제 diff169 → 수정 후 READY/변경1/삭제0. 별도 불가능 AS 요청은 계속 미해결이다. C seed/gold/사례 분류를 변경하지 않았다.

## 무료 재현·검증

```bash
cd app/backend
python -m pytest -q tests/test_dispatch_fallback.py tests/engine/test_dispatch_guards.py tests/test_unresolved_preview.py
RENTWISE_BUSY_SEED=/absolute/path/to/seed_busy.json python -m pytest -q
cd ../frontend
npm run typecheck
npm run build
```

모델은 FakeClient/미사용, DB는 격리 SQLite다. busy seed 환경변수가 없으면 해당 운영 seed 통합 시험만 SKIPPED이다. 인력 우선·퀵 초안 무저장/확정/재계산·자원 재사용 금지·재고 보호·회수 익일/고객 주말 휴무/범위 내 날짜 없음·명시 직원 우선·예약 과거 보호·stale/롤백·큐 최신 계획 연계·단계 상한을 시험한다. 수동 업무 대비 성공률/실제 업체 가용성이나 C 평가 점수의 근거는 아니다.

실행 결과(2026-10-17): backend 전체 **456 PASS**(415+TEL06312+TEL06429), frontend typecheck/build **PASS**(39modules), root bootstrap/기존A69 **PASS**(별도 저장소). IAB에서 busy 사본의17:30인력종료→퀵납품확정r8→다음근무일회수/PREP·기존17:30납품/P02대체확정r9와169건보존을 확인했다. 배송 Fake 응답의 잘못된 인용은 차단되어 수동 기존 작업 입력으로 이어졌고 회수는 Fake 해석을 사용했다. 유료모델·실제업체·운영Oracle/다중서버·모바일·배포는 **SKIPPED**, 실제repo rootcheck/backend별도lint/type/build는 **NOT CONFIGURED**다.
