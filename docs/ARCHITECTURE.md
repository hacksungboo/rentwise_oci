# 아키텍처와 연동 지점

기준 문서: 노션 **일반 렌탈 운영 플랫폼 — MVP 실행 명세**, **공통 개발 계약**, 역할별 A·B·C 지시문.

## 구성

```
app/
├── backend/            FastAPI (Python 3.12)
│   └── rentwise/
│       ├── contracts/  공용 계약 v1 (B 소유, A·C 검토)  ← A·C도 여기서 import
│       ├── engine/     A 실제 엔진 (RealEngine)        ← A 소유
│       ├── dev_fakes/  mock EnginePort (B, 개발 전용)
│       ├── api/        HTTP 라우트, 세션, 오류 형식
│       ├── services/   요청·해석, 계획 생성·비교·확정, 운영 현황
│       └── db/         스키마(SQLAlchemy Core), seed 적재, snapshot 조회
├── frontend/           Vue 3 + TypeScript + Vite, nginx 로 서빙
└── fixtures/v1/        seed.json (지금은 B 임시본 → C 정식본으로 교체)
infra/                  docker-compose, .env.example, deploy/check/smoke/backup 스크립트
docs/                   협업·배포·아키텍처 문서
```

## 메인 시연 동선

| 화면 | 동작 | API |
|---|---|---|
| 로그인 | 데모 계정 (admin / e1~e3) | `POST /api/v1/sessions` |
| S1 운영 현황 | 직원별 타임라인, 창고 준비, 장비 재고(물리/가용 분리) | `GET /operations?date=`, `GET /reference` |
| S2 요청 해석 | 원문 입력 → 해석 → 근거 표시 → 확인 필요 항목 체크·수정 | `POST /requests`, `POST /requests/{id}/interpret`, `PUT /requests/{id}/interpretation` |
| S3 변경안 | 보드에 변경 전(점선)·후 표시, 연쇄 영향·이유, 확정/보류 | `POST /plans`, `GET /plans/{id}`, `POST /plans/{id}/confirm`, `POST /plans/{id}/hold` |
| 확정 후 | DB 재조회, 상태 버전 +1 | `GET /operations` |
| 시연 초기화 | seed 로 되돌림 (C 측정용) | `POST /admin/reset` |

공통: 오류 형식 `{error:{code,message,details,retryable},trace_id}`, 변경 요청은 `Idempotency-Key` 지원, 확정·해석은 기준 revision 필수. API 문서: 배포 후 `/api/docs`.

## A 엔진 연동 방법 (mock → real)

1. `app/backend/rentwise/engine/` 에 `RealEngine` 클래스를 만들고 `engine/__init__.py` 에서 export 합니다.
2. `rentwise.contracts.EnginePort` 의 4개 메서드를 같은 서명으로 구현합니다: `interpret`, `availability`, `solve`, `validate`.
3. 서버 `.env` 에서 `ENGINE_MODE=real` → `./scripts/deploy.sh`. API·화면 코드는 바꿀 필요 없습니다.
4. 테스트: `app/backend/tests/engine/` (A 소유). 메인 흐름 테스트는 `ENGINE_MODE=real pytest` 로도 돌릴 수 있게 유지해 주세요.

B가 엔진에 넘기는 값:
- `interpret`: 원문, 수신시각, 출처 거래처, 후보 거래처/품목, 해당 거래처의 기존 작업 요약(최대 15건, `customer_id` 포함)
- `solve`: 사람이 확인한 operations(RESCHEDULE 이면 기존 작업의 item/from/to/due/asset 을 명시적으로 상속), 전체 snapshot(현행 계획의 plan_items 포함), `input_hash`
- `validate`: 확정 트랜잭션 안에서 최신 snapshot + 변경안 전체

## C 데이터 연동 방법

- 지금 `fixtures/v1/seed.json` 은 B 가 `fixtures/dev/build_dev_seed.py` 로 만든 **임시 개발 seed** 입니다(명세 §8.2 회수 지연 산술 반영).
- C 가 정식 seed 를 만들면 같은 `seed.json` 형식(엔티티별 배열 + manifest)으로 교체하거나, CSV 묶음으로 낸 뒤 B 에게 변환을 요청해 주세요.
- 정답(gold)은 루트 `eval/` 에 둡니다. 서비스 이미지와 seed 에 들어가지 않습니다.

## 명세와 다르게 구현한 부분 (B 결정, 재검토 가능)

| 항목 | 명세 | 구현 | 이유 |
|---|---|---|---|
| 시각 저장 | `TIMESTAMP WITH TIME ZONE` | UTC 기준 `TIMESTAMP` + API 에서 +09:00 표시 | Oracle 드라이버별 시간대 바인딩 차이를 피하려고 |
| 마이그레이션 | 순번 SQL + schema_version | 기동 시 `create_all` + `rw_schema_version` | 해커톤 일정. 스키마 변경 시 추가형으로만 |
| seed 형식 | CSV/JSON 파일 묶음 | 단일 `seed.json` | 적재 단순화. C 정식 데이터 받으면 조정 |
| DB 배치 | 단일 서버 | 같음 (team-4-1) | |
| 이미지 | Actions → GHCR → SSH 배포 | 같음 (ARM 러너 네이티브 빌드, 실패 시 자동 롤백). 비상용으로 서버 직접 빌드(`deploy.sh`) 유지 | |

## 아직 안 한 것 (우선순위 낮음)

- S4 장비 상세 화면(API 는 `GET /assets/{id}` 있음), S5 직원 현장 완료 기록(ExecutionEvent)
- 비용 원장(AiUsage)·BudgetPort 저장 구현 → A 실제 모델 연동 시점에
- 계획 수정(PATCH)·재계산, 동시 확정 부하 시험, 백업 복구 리허설
