# C 인수인계

## 2026-10-17 · feat/c-busy-seed

- 추가: `app/fixtures/v1/seed_busy.json`
  - 데이터: rental-synth-busy-v1, SYNTHETIC. 거래처 38, 직원 12, 장비 132, 업무 174(준비 포함), 평일 하루 25~34건.
  - manifest sha256: ce2d91062a98…
  - T17 같은 조건 측정에 쓰는 seed다. 정답(gold)과 사례 분류는 넣지 않았다.
- 변경: `infra/docker-compose.yml`
  - api에 `SEED_PATH`를 전달한다. 기본값은 지금과 같은 `/app/fixtures/v1/seed.json`이라 동작이 바뀌지 않는다.
  - 서버 `infra/.env`에 `SEED_PATH=/app/fixtures/v1/seed_busy.json`을 넣으면 '시연 초기화'와 빈 DB 자동 적재가 busy seed를 쓴다.
- 기존 `seed.json`과 시험은 그대로다(B 시험이 그 내용을 기대함).
- 알려진 제한: A의 해석 입력 한도(INPUT_LIMIT=8000바이트)가 그대로면, busy seed에서는 AI 해석이 AI_INPUT_TOO_LARGE로 거절된다(거래처 후보 38곳). A에게 상향을 요청했다.

## 2026-10-17 · feat/c-busy-seed-1017

- 변경: `app/fixtures/v1/seed_busy.json`의 모든 날짜를 +1일 이동했다. 시연의 '오늘'을 실제 날짜 10-17(토)과 맞추기 위해서다.
  - 기준 시각(clock_anchor) 2026-10-17T09:00:00+09:00, 계획 범위 10-17~10-24.
  - 바쁜 근무일 10-17, 10-20~23, 10-18(일) 근무, 10-19(월) 휴무.
  - 날짜 외 데이터(ID·장비·직원·이동시간·업무 순서)는 그대로다. C가 기존 seed를 +1일 이동한 사본과 동일함을 확인했다.
  - manifest sha256 `d8a716e10ad9…`, 파일 sha256 `237db68ac829…`. 이전판(ce2d9106…)과 섞어 쓰지 않는다.
- 영향(소유자에게 따로 요청함):
  - `RENTWISE_BUSY_SEED`를 지정해 돌리는 busy 시험 5개가 10-16 날짜를 고정해 둬서 이 seed로는 실패한다. CI에서는 건너뛴다. 요청서: C 저장소 `rental/handoffs/A_B_요청_busy날짜이동.md`.
  - TEL-061 측정 절차서의 고정값(sha256, 기준 시각)을 다시 고정해야 한다.
- 서버 반영: 병합·배포 뒤 '시연 초기화'를 누르면 새 seed가 들어간다(SEED_PATH는 이미 seed_busy.json).
