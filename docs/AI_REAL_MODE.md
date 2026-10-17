# real 모드 (GPT 해석 + A 배정 엔진) 켜기·확인·기록

```
고객 원문 ─▶ GPT(A 해석, Structured Outputs) ─▶ 원문 근거·ID·날짜 검증 ─▶ 사람 확인
        ─▶ 회수·납품 변경: A v2 core (반납→정비→다음 납품, 같은 모델 대체/인력 부족 대안)  /  그 외: A v1 호환 엔진
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
#   OPENAI_MODEL=gpt-5.6-terra    ← A 가 가격 정책을 등록한 모델만 허용
#   AI_BUDGET_USD=3              ← 누적 사용 한도. 0 이면 유료 호출 차단
docker compose up -d api         # .env 다시 읽기 (이미지는 배포 버전 그대로)
docker compose logs api | grep "ai:"     # ai: model=gpt-5.6-terra key=set budget_usd=3
```

**배포 직후 한 번은 화면의 "시연 초기화"(또는 smoke)로 seed 를 다시 넣어야 합니다.** seed 를 고쳤기 때문입니다(J-AS2 담당 E2, 준비 작업 시간대, 직접 이동 예약).

## 2. 확인

```bash
SMOKE_AI=0 SMOKE_PASSWORD=<admin 비번> ./scripts/smoke.sh   # AI 호출 없이 v2 계산·확정 경로 (무료)
SMOKE_PASSWORD=<admin 비번> ./scripts/smoke.sh              # GPT 포함 전체 (유료, 비용은 §4/응답 usage 기준)
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

## 4. 비용 (TEL-065 Terra 기본값)

- 기본 모델은 `gpt-5.6-terra`이며 해석·변경안 설명에 함께 적용합니다. 기존 `.env`에 Luna를 명시했다면 **`OPENAI_MODEL=gpt-5.6-terra`로 수정하고 API를 재기동**해야 합니다. 코드 기본값만 바꿔서는 기존 환경변수 값을 덮어쓰지 않습니다. `.env.example`과 compose 기본값은 Terra로 변경했습니다.
- 공식 문서 확인일 2026-10-17: [Terra 모델](https://developers.openai.com/api/docs/models/gpt-5.6-terra), [표준 가격](https://developers.openai.com/api/docs/pricing). short-context 입력 $2.00 / 캐시 $0.20 / 출력 $12.00 per 1M, 캐시 쓰기 입력의1.25배. 현재 입력 상한은 short-context 범위입니다. Responses/Structured Outputs/`reasoning.effort=none`을 유지합니다. 실제 계정 사용 가능 여부·모델 응답 품질·청구는 이번 무료 시험으로 검증한 것이 아닙니다.
- `INPUT_LIMIT=16000`: 전체 요청 UTF-8 bytes+고정여유256≤16000. 토큰 개수가 아니며 기존 보수적 상한 정책을 유지합니다. 원문2000자·기존 작업15개·38/120곳 대표 입력 회귀도 유지합니다.
- 해석 출력2000, **예약 $0.064/시도**: `(16000×1.25×2 + 2000×12)/1e6`. 최대2시도 **$0.128/요청**, 240회×2시도 상한 예약은 **$30.72**입니다. 실제 사용량은 응답 usage로 정산하고 알 수 없으면 UNKNOWN 예약을 유지합니다.
- 설명 출력1000, **예약 $0.052/1회**: `(16000×1.25×2 + 1000×12)/1e6`. 추가 고객 안내문은 확정 사실로 생성하는 SYSTEM 초안이라 모델 호출·비용이 없습니다.
- Terra `PRICE_VERSION=openai-standard-2026-10-17-terra`. 명시 Luna 호환 가격/과거 `openai-standard-2026-10-16`은 유지합니다. 당시 Luna 예약은 해석$0.0064/설명$0.0052였습니다. 원장은 호출이 전달한 가격 버전으로 정산해 전역 모델 설정이 바뀌어도 다른 모델 가격을 적용하지 않습니다. 등록되지 않은 버전은 정산하지 않고 예약을 유지합니다.
- 해석 `PROMPT_VERSION=rental-extract-v1.1`, 설명 `rental-plan-explain-v1.0`은 그대로입니다. 모델 프롬프트·응답 schema는 바꾸지 않고 설명 표시만 서버가 Markdown으로 구성합니다(`presentation_version=rental-plan-markdown-v1`).
- `AI_BUDGET_USD` 총예산은 자동 증액하지 않습니다. 예산3달러에서 예약 상한을 모두 유지한다면 해석 시도46회까지이며, 성공 정산액이 상한보다 작으면 실제 허용 횟수는 달라집니다. 기존 미정산·불명 예약도 한도에 포함됩니다. 해커톤 총지원금과 서버 한도는 별개입니다.
- 테스트는 FakeClient/격리 SQLite이며 실제 유료 호출0입니다. 과거 Luna 검증 예산 승인을 Terra 호출 승인으로 사용하지 않았습니다.

## 5. AI 가 실패하면

오류 배너에 코드가 나옵니다(`AI_TIMEOUT`, `BUDGET_EXCEEDED`, `AI_SCHEMA_INVALID` …). 배너 아래 **기존 작업을 골라 직접 입력**으로 같은 요청을 사람이 입력해 계산·확정까지 계속할 수 있습니다.

## 6. 지원 범위

| 요청 | real 결과 |
|---|---|
| 회수 지연 (기존 PICKUP 일정 변경) | A v2 core: 회수 직원 재배정, 준비 이동, 다음 납품 같은 모델 대체, 예약·대여·의존 갱신 |
| 기존 납품 일정 변경 | A v2 core: 내부 인력 우선, 부족 시 책임자 확인용 퀵 배정안 |
| 사람이 확인한 기존 A/S 방문창·완료 기한 변경, 직원 변경 | A v1 호환 엔진 (TEL-067) |
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

## 8. 변경안 AI 설명 (TEL-057)

변경안 검토 상단의 **AI 설명 보기**를 누르면 변경된 시간·직원·장비, 대체 이유와 유지되는 약속을 정리합니다. 같은 화면에서 설명이 표시된 뒤에는 버튼을 다시 호출하지 않습니다. 계산·확정 권한과 제약 검사는 기존 엔진/API가 유지합니다.

- 모델은 `OPENAI_MODEL`(기본 gpt-5.6-terra), 기존 `LedgerBudget`을 사용합니다. 별도 키/환경변수/DB 스키마는 없습니다. 설명 코드 배포 후 API 재기동이 필요합니다.
- 설명용 `PROMPT_VERSION=rental-plan-explain-v1.0` 유지. 전체 UTF-8 bytes+256≤16000, 출력1000,20초·1회 시도/자동 재시도 없음. Terra 예약은 **$0.052/설명**이며 가격 버전·계산은 §4를 따릅니다.
- AI는 저장된 변경안으로 서버가 구성한 사실 ID를 정렬합니다. 모든 사실이 한 번씩 포함되어야 하고 모델이 만든 자유 문장·숫자·승인 판정은 표시하지 않습니다. 한국어 사실 문장은 서버가 구성합니다. 이 방식은 변경 사유·시각·담당·장비를 새로 지어내지 않고 읽는 순서를 AI가 정리하도록 합니다.
- PREP 시작/완료는 실제 PREP segment를 사용하고, 납품 약속은 SERVICE 구간을 사용합니다. 고객 이름·직원·장비·현재 변경안 facts만 보내며 요청 원문/전체 고객목록/연락처/키는 보내지 않습니다. 이 항목들은 도구 지시로 사용하지 않습니다.
- 키/예산 없음·시간초과·응답 오류는 **계산 결과 요약**으로 표시합니다. 확정 버튼은 기존 기준으로 유지합니다. 사용량을 모르면 예약을 UNKNOWN으로 유지하고 재호출하지 않습니다. 관리자 AI 기록에서 설명 프롬프트 버전으로 구분할 수 있습니다.
- DB 연결을 닫은 뒤 AI를 호출하고, 호출 후 변경안 revision/input_hash/운영 상태/설명 근거를 다시 검사합니다. 그 사이 보류/확정/다른 변경이 있으면409로 설명을 버립니다. 설명 API가 작업·장비·예약·현행 계획을 변경하지 않습니다.
- 응답은 현재 화면의 동일 변경안에만 보관합니다. 별도 서버 캐시/영속 설명 저장은 없으며 페이지를 다시 열어 요청하면 새 AI 호출입니다.

API: 관리자 `POST /api/v1/plans/{plan_id}/explanation`, body `{expected_plan_revision, base_state_revision, input_hash}`. 응답 `{status: OK|FALLBACK, explanation, call, error_code}`. 설명은 서버가 구성한 Markdown의 제목·목록·굵게·인용을 Vue 보간으로 표시하며 HTML/링크/이미지를 실행하지 않습니다. 기존 plain paragraphs/preserved/notice도 API 호환으로 유지합니다. [A 구현 기록](handoffs/A.md#tel-057--변경안-ai-설명-화면api).

검증은 FakeClient/격리 SQLite/실제 BudgetPort와 로컬 브라우저로 수행했습니다. 실제 유료 모델 호출·운영 Oracle·배포는 별도입니다.

## 9. 내부 인력 부족 대안 (TEL-064)

기존 DELIVERY 변경도 v2 core로 계산한다. 내부 직원 계획부터 찾고, 별도 인력 검사에서 부족이 확인될 때만 퀵 배정 변경안/당일 회수의 다음 근무일 제안을 만든다. 실제 업체 호출·수락·결제는 별도이고 책임자 확정 전 운영 자원을 바꾸지 않는다. 장비·준비·방문창·기한은 완화하지 않는다. 단일 요청/대기열의 기존 계산·확정 API에 연결했으며 새 환경변수/모델 호출/비용 정책은 없다.

버전: v2 `rental-solver-normal-delay-v2-1`, v1 `rental-solver-b-v1-5`(TEL-067 A/S 새 조건 검증), 내부 정책 `dispatch-fallback-v1`. 해석 PROMPT는 TEL-068부터 `rental-extract-v1.2`이며 설명 `rental-plan-explain-v1.0`과 입력16000은 유지한다. 후속 TEL-065의 모델·가격·예약은 §4를 따른다. 여러 날짜의 대안 탐색은 총 2초 보장이 아니며 단계별 제한·자원 표현·확정 계약은 [DISPATCH_FALLBACK.md](DISPATCH_FALLBACK.md)를 따른다.

TEL-063은 busy-v1의 TRANSFER 방문창 오판과 실패 시 전체 삭제처럼 보이던 미리보기를 수정한다. 불가능한 요청은 오류와 현재 일정으로 남으며 확정할 수 없다. seed/gold는 수정하지 않았다.

## 10. 강조 설명·고객 안내문 (TEL-065)

변경안 AI 설명은 **변경 핵심 / 변경 이유 / 유지되는 약속 / 확정 전 안내**로 나누며 고객·변경 후 시간/직원/장비를 굵게 표시합니다. AI는 기존 사실 ID의 순서만 정하고 날짜·수치·문장은 서버가 생성합니다. 이름 안의 Markdown 문법/개행을 인용 처리하며 새 HTML 삽입이나 링크 실행은 허용하지 않습니다. 모델 실패 시 SYSTEM 요약도 같은 형식입니다.

확정 후 단일/대기열 화면에 **고객에게 보낼 안내문**이 표시됩니다. `GET /api/v1/plans/{id}/customer-message`(ADMIN)는 짧은 workspace 잠금 안에서 현재 확정 계획·최신 HUMAN 해석·수신 고객/직접 대상 작업을 확인하고 SYSTEM 초안을 만듭니다. 다른 고객의 후속 일정/직원/장비ID/PREP 정보는 포함하지 않으며, 복사 버튼은 서버에서 최신 유효성을 다시 확인합니다. 예전/미확정/보류/수신 고객 불명·혼합 대상은 차단합니다. 고객 방문은 SERVICE 구간을 쓰고 실제 업무 완료·발송 완료를 주장하지 않습니다. 퀵미호출이면 업체 호출·수락 확인 후 최종 안내하겠다는 문구를 사용합니다. 별도 AI/과금/메시지 저장·발송 채널·새 DB스키마는 없습니다.


### 검토 화면의 지원 범위 오류 (TEL-066)

`AI_REVIEW_UNSUPPORTED`는 AI 추출 이후 B 확인 화면에서 편집할 수 없는 항목(예: 신규 설치의 반납일·무기한 여부 확인)이 있어 멈춘 경우다. HTTP422/retryable=false와 `error.details.paths`를 반환한다. 모델 연결/설정 오류와 구분하며 동일 원문 재시도는 해결책이 아니다. 신규 설치는 사유를 적어 보류하고 별도 검토한다. 실제 연결 오류와 큐 복구 절차는 [대기열 인계](REQUEST_QUEUE.md#tel-066--해석-거절과-연결-오류-구분복구)를 따른다.


### A/S 방문 시각·완료 기한 변경 (TEL-067)

기존 오전 A/S를 오후로 옮길 때 과거 완료 기한을 무조건 유지하지 않는다. 새 방문 종료를 수용하는 경우에만 기존 기한을 추천하고, 그렇지 않으면 입력한 방문 종료 또는 품목별 현장 소요시간으로 계산한 종료를 추천한다. 추천은 사람이 눌러 확인해야 적용되며, 기한은 별도로 수정할 수 있다. 방문 종료와 현장 실제 완료 기록은 별개다.

AS RESCHEDULE에 한해 기존 방문창·기한 밖의 새 조건을 계산할 수 있다. B는 확정 잠금 안에서 최신 HUMAN/확인항목과 저장한 정규화 작업이 일치하는지 검사하고, 해당 AS의 window_start/window_end/due_at만 복사한 검증 snapshot으로 독립 검증한다. 고객 방문창/직원·기술/근무·휴식/이동/다른 작업·고정 상태/장비/의존 제약을 완화하지 않는다. 통과 시 기존 트랜잭션에서 새 조건과 계획을 함께 저장하고 revision을 올린다. 초안 단계는 운영 Job 불변이며 새 schema/env/모델 호출은 없다.

busy-v1 WP-A는30분, B 개발 seed WP-A는40분이다. 같은16시 시작의 방문 종료는 각각16:30/16:40으로 계산해야 한다. 실제 가능 여부는 근무표/고객 창에 따라 달라지며17:30 기한 입력만으로 READY를 보장하지 않는다. 타 업무 종류의 v1 저장 제한은 그대로다.


### 변경 전 약속 문맥과 시간 추천 (TEL-068)

기존 후처리는 같은 고객·종류의 업무가 여러 개면 품목·날짜·기존 시각을 고려하지 않고 대상 선택을 지웠고, 오전·오후가 생략된 시각을 모두 비웠다. TEL-068은 AI가 추출한 종류·고객·품목을 우선 검사한 뒤 단일 RESCHEDULE의 명시적 기존 날짜/시각과 새 숫자 시간 범위·변경 방향을 대조한다. 유일한 후보만 연결하며 모델이 다른 기존 작업을 선택했으면 오류로 막는다.

예: `오늘 4시 프린터 설치를 3시~3시반 사이로 당겨주세요.` → 현재 업무 문맥에서 오늘16시 프린터납품이 유일하면 해당 작업을 연결하고15:00~15:30을 **오후 문맥의 확인용 추천**으로 제시한다. 작업/시작/종료 질문은 남기고 HUMAN 확인 없이는 계산을 막는다. 새로운 원문 근거를 만들거나 자동 승인하지 않는다. 날짜·품목이 다른 납품도 후보 목록에서 구분할 수 있도록 UI에 날짜·품목을 표시하고 납품은 도착고객 기준으로 필터링한다.

지원하는 문맥 패턴은 오늘/내일/모레 + 기존 숫자시각 + 작업을/를 + 새 숫자시각 범위(~·부터·에서) + 당겨/앞당겨/미뤄/늦춰/변경/옮겨/바꿔다. 반=30분, 분 단위와 명시적 오전/오후·24시각도 처리한다. 기존 시각은 existing_jobs의 window_start와 정확히 비교한다. 넓은 방문창과 실제 SERVICE 시각이 다른 경우, 중복된 기존 시각, 날짜 생략, 다중 작업·별도 시간 문장, 변경 방향 불일치, 자정을 넘는 범위는 추측하지 않고 사람 확인을 유지한다. 범용 한국어 날짜 파서를 추가한 것은 아니다.

추천 버튼은 시작 시각이 있어야 종료·기한을 계산할 수 있다. 시작이 없으면 필요한 입력을 구체적으로 안내한다. 기존 작업이 유일하면 선택 추천을 제공하고 선택 시 누락 품목을 연결해 실제 품목별 소요시간을 쓴다. 일반 변경의 기한은 새 종료를 수용하는 기존 기한을 우선 추천하며, 그 외에는 당일17시 또는 그보다 늦은 방문종료를 명시적 추천으로 제시한다. 추천 클릭은 기존 확인 UI에서 사람이 수행한다.

PROMPT_VERSION=`rental-extract-v1.2`, B검토후처리=`b-review-v2`. 모델 Terra/PRICE/전체 입력16000bytes/출력2000/시도 예약$0.064·공유 예산은 그대로다. 추가 모델 호출·새 schema/의존성·운영 초기화는 없다. 기존 해석은 자동 재과금하지 않으며 새 원문 접수·명시적 재해석 후 새 동작을 사용한다.
