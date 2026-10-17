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
