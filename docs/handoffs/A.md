# A 엔진 인수인계 — TEL-046

2026-10-16 · Owner A / Codex · 브랜치 `codex/a-engine` · 상태 Review(서비스 통합 미완료)
기준 main: `3afac349c8d86f723bd04276843b6535715487b4`.

## 제공 범위

`from rentwise.engine import solve, validate, availability`로 실제 결정적 엔진을 호출한다.
DB·HTTP·모델 호출 및 입력 수정은 없다. 경로는 이 저장소의 OWNERSHIP을 따른다.

- solve: 정상 CREATE DELIVERY와 RESCHEDULE PICKUP→기존 PREP→기존 DELIVERY의 후보를 자동 생성한다.
- validate: 전체 Job/PlanItem/유효 예약/Rental/Dependency를 원본 snapshot과 비교한다. VALID/INVALID/DATA_MISSING.
- availability: 물리 수량과 기간 가용성을 분리하고 예약 경계·예상 준비완료마다 window를 나눈다.
  조건부 준비는 독립 검증을 통과한 계획에만 부여한다. 미정 회수 종료를 임의로 풀지 않는다.

영향 그래프를 위상 정렬하고 직원/동일 모델 개체/시각의 제한 DFS를 수행한다.
전체 후보가 독립 validate를 통과한 경우만 FEASIBLE이다. 기존 고객 약속·진행/완료·실적을 보존한다.
수동 override도 동일 검사 대상이다. 이유/영향 edge/예약 delta/탐색 통계를 반환한다.

범위: 요청/영향 작업별 개체1개, 영향 최대3개, 창고 경유 경로.
신규 AS/TRANSFER/새 회수·PREP/다개체 요청은 확인필요다. 기존 AS/TRANSFER 행은 보존한다.
max_candidates≤1000/max_search_ms≤2000의 cooperative limit이며 hard realtime/최적해 보장은 없다.
한도 전 유효안이 있으면 FEASIBLE+limit_reached가 가능하며, 없으면 NO_SOLUTION_FOUND다.
자격 직원0/동일품목 유효개체0/독립 시각 하한만 제한적 불가능 증명에 사용한다.

## B와 연결할 계약

공용 [v2 계약과 실행 예시](../../app/backend/rentwise/contracts/v2/README.md),
[스키마](../../app/backend/rentwise/contracts/v2/schemas/bundle.json)가 기준이다.
계약 보완 R1 전체 후보/R2 확인 완료 정규화/R3 TRANSFER 양쪽 방문창을 함께 기록했다.

| 항목 | 현재 B main | 이번 A core |
|---|---|---|
| 타입 | contracts/types.py Pydantic v1 | contracts/v2/types.py JSON TypedDict v2 |
| snapshot | 엔티티 배열만 | metadata/as_of/버전/horizon + 배열 |
| operation | 평면 patch | 완전한 Job + 확인/반납정책/대여 ID |
| PlanItem 구간 | segments | segments_json |
| 계획/행 ID | solve 후 B 발급 | solve 전 B 발급, id_allocations로 전달 |
| input hash | sha256: 접두사 | 공용 solver_input_hash의 bare64 |
| validate 입력 | PlanItem 목록 | 전체 CandidatePlan |
| 저장 | 기존 Job/행/예약 일부 | 동일 후보의 대여·의존 포함 원자 저장 필요 |

B v1 DTO/mock/API를 덮어쓰지 않았다. 공용 contracts/v2는 추가 변경이며 B 소유자 리뷰·병합과 A/C 확인이 필요하다.
`RealEngine` 및 interpret는 아직 제공하지 않는다. **현재 API에서 ENGINE_MODE=real로 전환하면 안 된다.**
registry가 기대하는 RealEngine 연결과 4개 함수의 v1→v2 전환은 아래 후속 작업이다.
기존 B mock 기본값과 UI 동작이 이 PR의 실제 엔진 연결 근거가 되지는 않는다.

B 다음 작업:

1. 실제 DB snapshot에 metadata/as_of/전체 참조·기간 밖 점유를 포함한다.
2. 사람 확인 이력에서 approved_job_ids와 정규화 operation을 만들고, 새 계획/행/예약/의존 ID를 먼저 발급한다.
3. 공용 serializer로 hash를 계산하고 v2 solve를 호출한다. 전체 candidate_plan을 draft에 보존한다.
4. 확정 잠금 안 최신 revision/snapshot으로 전체 후보를 재검증한 뒤 **검사한 동일 후보**를 원자 저장한다.
   Rental 예정값/신규 Job·대여/Dependency까지 포함하고 Asset 및 actual_* 실적은 덮어쓰지 않는다.
5. 해석 adapter와 EnginePort/RealEngine을 연결한 후 실제 API→solve→confirm 통합시험을 추가한다.

## 검증

검증 결과는 PR 작성 전 아래에 기록한다. C eval/gold는 런타임·시험에 복사하지 않는다.
이 PR의 sample.py는 작은 A 합성 데이터이며 정식 C 인수/실제 모델/클라우드 검증이 아니다.
기존 로컬 C 공개 seed 호환시험 2개는 이 main에 C build_snapshot이 없어 이식하지 않았다.

| 상태 | 명령 / 확인 | 결과 및 한계 |
|---|---|---|
| PASS | `cd app/backend && .venv/bin/python -m pytest -q` | Python3.12, 74 passed(A67+B7), 외부 anyio 별칭 deprecation warning 1개 |
| PASS | 공용 v2 README의 정상/지연 직접 호출 예시 | 두 요청 FEASIBLE, 독립 validate VALID |
| PASS | `cd app/frontend && npm ci --no-audit --no-fund` | lockfile 기준47 packages 설치 |
| PASS | `cd app/frontend && npm run typecheck` | vue-tsc 오류 없음 |
| PASS | `cd app/frontend && npm run build` | Vite30 modules, build 성공 |
| PASS | `bash -n infra/scripts/*.sh` | 배포 스크립트 구문 검사 |
| PASS | `git diff --cached --check` 및 새 문서 상대 링크 확인 | 공백 오류/깨진 내부 링크 없음 |
| NOT CONFIGURED | `sh scripts/check.sh` | 이 원격 main에 scripts/check.sh 없음(실행 시 exit127). 기존 별도 로컬 bootstrap 검사를 이 저장소 검증으로 대체하지 않음 |
| SKIPPED | `docker compose config -q` | 로컬 Docker CLI 없음, CI compose job에서 확인 필요 |
| SKIPPED | 로컬/서버 화면·Oracle·실제 모델·C 독립 gold | 본 PR 범위 밖이며 완료로 간주하지 않음 |

프런트 명령은 번들 Node24.19.0 + /private/tmp의 npm10.9.2 CLI로 실행했다.
시스템 PATH에 node/npm이 없어 검증 도구만 /private/tmp에 준비했으며 repository lockfile/package.json은 바꾸지 않았다.
CI의 Node22 환경 검사는 GitHub Actions에서 별도 확인해야 한다.

정상 합성 요청은 NEW-DEL/P02/E1, 고객 서비스11:00~11:15를 생성했다.
지연은 PICK/E2 출발13:40→회수14:00~14:10→창고14:30→PREP15:00,
기존 DEL은 P02/E1로 고객12:00~12:15 약속을 유지했다.

기존 원본 작업 폴더는 최초 커밋 없는 저장소여서 별도 clone에서 main 기준으로 선별 이식했다.
VOC·C fixtures/eval 및 다른 미커밋 파일은 포함하지 않았다. main 직접 push/병합/배포는 하지 않는다.
