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

- 추가: `app/fixtures/v1/seed_busy_1017.json`. busy-v1의 모든 날짜를 +1일 옮긴 판으로, 시연의 '오늘'을 실제 날짜 10-17(토)과 맞춘다.
  - clock_anchor 2026-10-17T09:00:00+09:00, 계획 범위 10-17~10-24.
  - 바쁜 근무일 10-17, 10-20~23, 10-18(일) 근무, 10-19(월) 휴무.
  - 날짜 외 데이터(ID·장비·직원·이동시간·업무 순서)는 그대로다. 기존 seed를 +1일 이동한 사본과 같음을 C가 확인했다.
  - manifest sha256 `d8a716e10ad9…`, 파일 sha256 `237db68ac829…`.
- 그대로 둠: `app/fixtures/v1/seed_busy.json`(10-16판, manifest sha256 `ce2d9106…`). CI가 `RENTWISE_BUSY_SEED`로 이 파일을 써서 busy 시험을 돌리므로(PR #28) 바꾸지 않는다.
- 서버 반영: 병합·배포 뒤 team-4-1 `infra/.env`에서 `SEED_PATH=/app/fixtures/v1/seed_busy_1017.json`으로 바꾸고 `docker compose up -d api`. 그다음 '시연 초기화'.
