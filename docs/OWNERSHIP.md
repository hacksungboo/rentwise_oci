# 역할별 소유 경로

노션의 실행 명세·공통 개발 계약은 `rental/...` 경로를 예정했지만, 이 저장소는 `app/` + `infra/` + `docs/` 구조를 씁니다. 대응 관계는 아래와 같습니다.

| 명세상 경로 | 이 저장소 경로 | 소유 |
|---|---|---|
| `rental/contracts/` | `app/backend/rentwise/contracts/` | B (A·C 검토) |
| `rental/engine/`, `rental/tests/engine/` | `app/backend/rentwise/engine/`, `app/backend/tests/engine/` | **A** |
| `rental/api/`, `rental/db/`, `rental/api/dev_fakes/` | `app/backend/rentwise/api/`, `.../db/`, `.../dev_fakes/`, `.../services/` | B |
| `rental/tests/api/` | `app/backend/tests/` (engine 제외) | B |
| `rental/web/`, `rental/tests/e2e/` | `app/frontend/` | B |
| `rental/fixtures/v1/` | `app/fixtures/v1/` | **C** |
| `rental/eval/`, `rental/evidence/` | `eval/`, `evidence/` (루트, 서비스 이미지에 포함 안 됨) | **C** |
| `rental/deploy/`, `.github/workflows/` | `infra/`, `.github/workflows/` | B |
| `docs/RENTAL_PRESENTATION.md` | `docs/PRESENTATION.md` | C |
| `rental/handoffs/{A,B,C}.md` | `docs/handoffs/{A,B,C}.md` | 각자 |

## 규칙

- 남의 경로는 고치지 말고 PR이나 메신저로 요청합니다. 통합 담당(B)도 다른 사람 코드를 다시 쓰지 않습니다.
- 공용 타입/스키마를 각자 복제하지 않습니다. `rentwise.contracts`에서 import 합니다.
- `eval/`(독립 정답)은 서비스 런타임·이미지·모델 입력에 절대 들어가지 않습니다. Docker 빌드 컨텍스트는 `app/backend`, `app/frontend`만 사용합니다.

## 현재 임시로 B가 만든 것

| 파일 | 상태 | 넘길 사람 |
|---|---|---|
| `app/fixtures/v1/seed.json` | 메인 시연용 **임시 개발 seed** (회수 지연 사례) | C가 정식 seed로 교체 |
| `app/backend/rentwise/dev_fakes/mock_engine.py` | 고정값을 돌려주는 **mock EnginePort** | A가 `engine/`에 실제 구현 후 `ENGINE_MODE=real` |
