# B 인수인계

## 2026-10-16 · feat/b-skeleton-main-flow

- 계약: `rental.bundle.v1` (intent v1, solver v1, validation/availability/interpretation-result v1)
- 데이터: `rental-dev-v1` (B 임시 seed, SYNTHETIC)
- 엔진: mock (`dev_fakes/mock_engine.py`) — 회수 일정 변경만 계산, 나머지는 NEEDS_REVIEW

### 실행 결과

| 검사 | 명령 | 결과 |
|---|---|---|
| 백엔드 단위·흐름 | `cd app/backend && pytest -q` | PASS (7) — SQLite |
| 시연 동선 스모크 | `infra/scripts/smoke.py` (로컬 uvicorn) | PASS (14단계) — SQLite |
| Oracle 문법 | 스키마·주요 쿼리 Oracle dialect 컴파일 | PASS (실기동 아님) |
| 프론트 타입·빌드 | `npm run typecheck && npm run build` | PASS |
| compose 문법 | `docker compose config -q` | PASS |
| Docker 이미지 빌드 | — | SKIPPED (작업 환경에서 레지스트리 차단) |
| Oracle 실기동·서버 배포·공개 HTTPS | `deploy.sh`, `check.sh`, `smoke.sh` | **미실행 — team-4-1 에서 다음 단계** |

### 기능 상태 (명세 F/T 기준)

| 기능 | 상태 |
|---|---|
| F01 현황·가용 (S1) | 구현 (mock availability) |
| F02 해석·사람 보정 (S2) | 구현 (mock 해석, origin 구분, 확인 필요 항목 차단) |
| F03 배정·영향 | mock 연결. A 실제 엔진 대기 |
| F04 비교·확정·보류 | 구현 (잠금·revision·validate·멱등·중복 확정 차단) |
| F05 현장 완료 (S5) | 미구현 |
| F06 클라우드 | 구성 완료, 배포 미실행 |
| F07 재현 | `/admin/reset`, seed sha256 |

### 다음 할 일

1. team-4-1 배포 → `check.sh`, `smoke.sh` 로 Oracle 경로 확인
2. A 엔진 정상/지연 묶음 나오면 `ENGINE_MODE=real` 로 I2 통합
3. C 정식 seed 수령 → 적재 형식 맞추기
4. S5 직원 화면(완료 이벤트)
