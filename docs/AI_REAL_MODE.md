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

- 모델 단가(A 기준): 입력 $0.20 / 캐시 $0.02 / 출력 $1.20 per 1M 토큰. 호출 1회 실제 약 $0.0005~0.001, 예약 상한 $0.0044, 최대 2회 시도.
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
