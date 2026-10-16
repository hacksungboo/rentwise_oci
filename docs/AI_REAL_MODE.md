# real 모드 (GPT 해석 + A 배정 엔진) 켜기·확인·기록

```
고객 원문 ─▶ GPT(A 해석, Structured Outputs) ─▶ 원문 근거·ID·날짜 검증 ─▶ 사람 확인
        ─▶ 회수 지연: A v2 core (반납→정비→다음 납품, 같은 모델 대체)  /  그 외: A v1 호환 엔진
        ─▶ 완전 후보 재검증 ─▶ 확정 트랜잭션(Oracle) ─▶ 재조회
```

| 구성 | 위치 | 담당 |
|---|---|---|
| GPT 해석·검증 | `app/backend/rentwise/engine/interpret.py`, `intent_checks.py`, `b_review.py` | A |
| 배정·검증 v2 core | `app/backend/rentwise/engine/solver.py`, `validate.py` | A |
| v2 연결(형식 변환·ID 발급·저장) | `app/backend/rentwise/services/v2_bridge.py`, `services/plans.py` | B |
| 비용 장부·호출 기록 | `app/backend/rentwise/services/ai_ledger.py`, 표 `rw_ai_budget` `rw_ai_ledger` `rw_ai_calls` | B |

## 1. 켜기 (team-4-1)

```bash
cd ~/rentwise_oci/infra
vi .env
#   ENGINE_MODE=real
#   OPENAI_API_KEY=sk-...        ← 채팅·GitHub·슬라이드에 붙이지 말 것
#   OPENAI_MODEL=gpt-5.6-luna    ← A 가 가격 정책을 등록한 모델만 허용
#   AI_BUDGET_USD=3              ← 누적 사용 한도. 0 이면 유료 호출 차단
docker compose up -d api         # .env 다시 읽기 (이미지는 배포 버전 그대로)
docker compose logs api | grep "ai:"     # ai: model=gpt-5.6-luna key=set budget_usd=3
```

**배포 직후 한 번은 화면의 "시연 초기화"(또는 smoke)로 seed 를 다시 넣어야 합니다.** seed 를 고쳤기 때문입니다(J-AS2 담당 E2, 준비 작업 시간대, 직접 이동 예약).

## 2. 확인

```bash
SMOKE_AI=0 SMOKE_PASSWORD=<admin 비번> ./scripts/smoke.sh   # AI 호출 없이 v2 계산·확정 경로 (무료)
SMOKE_PASSWORD=<admin 비번> ./scripts/smoke.sh              # GPT 1회 포함 전체 (약 $0.001)
```

- 마지막에 `AI: mode=real model=... 호출 성공 1 / 실패 0 · 사용 $0.000x` 가 찍힙니다.
- 화면: 조건 확인 패널 배지가 **AI 해석**, 상단 OCI 배지 → 실행 환경 패널 **AI 해석** 칸에 최근 호출·토큰·지연·사용액.

## 3. 기록 보기

| 어디 | 무엇 |
|---|---|
| `docker compose logs -f api \| grep ai.` | 호출마다 한 줄: `ai.interpret request=… model=… status=OK\|ERROR code=… attempts=… tokens_in=… tokens_out=… latency_ms=… provider_id=…`, 한도 초과 시 `ai.budget exceeded` |
| `GET /api/v1/admin/ai` (관리자) | 한도·정산액·예약 포함 사용액, 성공/실패 수, 최근 10건 |
| `rw_ai_calls` | 성공·실패 모든 해석 호출 (시연 초기화로 지우지 않음) |
| `rw_ai_ledger` | 호출 시도별 예약/정산/불명. timeout 등 사용량을 모르면 예약액을 그대로 잡아 둠 |
| `rw_interpretations.call_json` | 저장된 해석의 모델·토큰·지연·OpenAI 응답 ID |

원문·연락처·API 키는 어떤 기록에도 남기지 않습니다.

```sql
-- team-4-2 DB 에서
SELECT created_at, status, error_code, input_tokens, output_tokens, latency_ms FROM rw_ai_calls ORDER BY created_at DESC FETCH FIRST 10 ROWS ONLY;
SELECT status, COUNT(*), SUM(NVL(settled_usd, reserved_usd)) FROM rw_ai_ledger GROUP BY status;
```

## 4. 비용

- 기존 등록 단가 정책: `PRICE_VERSION=openai-standard-2026-10-16`, 입력 $0.20 / 캐시 $0.02 / 출력 $1.20 per 1M 토큰. 이번 변경에서 가격표를 바꾸거나 실제 청구액을 측정하지 않았습니다.
- `INPUT_LIMIT=16000`: 지시문·응답 schema·후보 목록·원문을 포함한 요청 전체 UTF-8 바이트 수 + 고정 여유256이 16,000 이하여야 합니다. 실제 토큰 개수를 뜻하지 않습니다. 원문2000자·기존 작업15개 제한은 유지합니다. 38곳(busy-v1)·120곳 대표 입력을 시험하며, 거래처 수 자체의 무조건 허용 한도는 아닙니다.
- `OUTPUT_LIMIT=2000`, `PROMPT_VERSION=rental-extract-v1.1` 유지. 프롬프트/응답 schema/모델/단가를 바꾸지 않았으므로 PRICE/PROMPT 버전도 유지합니다.
- 입력 바이트 상한을 보수적 토큰 상한으로 사용하는 기존 정책에 따라, **시도당 $0.0064**를 예약합니다: `(16000 × 1.25 × $0.20 + 2000 × $1.20) / 1,000,000`. 1.25배는 기존 캐시 쓰기 여유이고 출력에는 reasoning 등 전체 output usage가 포함됩니다. 실제 토큰·비용은 응답 usage로 정산합니다. 사용량을 모르는 시도는 예약을 유지합니다.
- 최대2시도이므로 요청당 최대 예약 $0.0128, 240회×2시도이면 $3.072입니다(모든 시도를 상한으로 예약 유지하는 계산). 이전8000 정책은 같은 기준 $2.112였습니다. $6.14/$4.22는 이 조건의 산술 결과가 아닙니다. 이 수치가 운영 예산 설정을 자동으로 늘리지는 않습니다.
- 구조·형식 토큰이 존재하므로 이 검사는 정확한 토큰 계수가 아닌 보수적 로컬 정책입니다. [OpenAI 토큰 계수 문서](https://developers.openai.com/api/docs/guides/token-counting)와 구분하며, 이번 수정은 토큰 계수 API나 유료 모델 호출을 추가하지 않습니다.
- `AI_BUDGET_USD=3` 이면 최악 기준으로도 수백 회. 전체 지원금($50)과 별개로 서버가 이 한도에서 멈춥니다.
- 테스트(pytest·CI)는 모델 대역을 쓰므로 유료 호출이 없습니다. 반복 점검은 `SMOKE_AI=0`.

## 5. AI 가 실패하면

오류 배너에 코드가 나옵니다(`AI_TIMEOUT`, `BUDGET_EXCEEDED`, `AI_SCHEMA_INVALID` …). 배너 아래 **기존 작업을 골라 직접 입력**으로 같은 요청을 사람이 입력해 계산·확정까지 계속할 수 있습니다.

## 6. 지원 범위

| 요청 | real 결과 |
|---|---|
| 회수 지연 (기존 PICKUP 일정 변경) | A v2 core: 회수 직원 재배정, 준비 이동, 다음 납품 같은 모델 대체, 예약·대여·의존 갱신 |
| 기존 A/S 방문창 안 시각 변경, 직원 변경 | A v1 호환 엔진 |
| 신규 납품·이동·장비 지정 변경 등 | 검토 필요(NEEDS_REVIEW)로 확정 차단 |


## 7. TEL-055 입력 한도 회귀 재현 (무료)

```bash
cd app/backend
python -m pytest -q tests/engine/test_input_limit.py
# C가 제공한 운영 seed만 지정. gold/scenarios/사례 분류 파일은 읽지 않습니다.
RENTWISE_BUSY_SEED=/absolute/path/to/seed_busy.json python -m pytest -q tests/engine/test_input_limit.py
```

환경변수를 지정하지 않으면 C seed HTTP 시험만 SKIPPED이고, 38/120곳·경계/초과·예약 시험은 항상 실행됩니다. busy 통합 시험은 격리 SQLite, 실제 B 비용원장/사람 확인/계획/확정 코드를 쓰고 모델만 FakeClient로 대체합니다. 실제 OpenAI 의미 정확도·청구액·운영 Oracle 결과로 확대하지 않습니다.

B 후속 검토: 후보를 보낸 거래처 + 원문 이름/약칭의 결정적 검색 결과로 좁히면 입력 크기와 지시문 주입 표면을 줄일 수 있습니다. 이 변경은 B services/DB를 수정하지 않습니다. 후보 축소 시 중복 이름·모호함을 숨기거나 선택된 출처 거래처를 누락하지 않도록 별도 검증해야 합니다.
