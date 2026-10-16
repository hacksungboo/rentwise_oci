# 작업 현황

| ID | 담당 | 브랜치 | 상태 | 소유 경로 | 수용 기준 |
|---|---|---|---|---|---|
| TEL-046 | A / Codex | codex/a-engine | Review | app/backend/rentwise/engine/, app/backend/tests/engine/, docs/handoffs/A.md | 독립 v2 core 및 최초 PR 제출 |
| TEL-048 | A / Codex | codex/a-engine | Review | engine/, tests/engine/, A 인수인계·작업 기록 | B v1 변경 없이 계산·확정·재조회, 지원 밖 작업 무저장 차단 |

## TEL-046 이식 계획 및 위험

1. origin/main의 경로와 pytest 구조에 A 엔진을 이식한다.
2. B v1 계약을 유지하고 공용 contracts/v2에 v2 스키마·DTO·정규화·hash를 추가한다. 공용 경로는 B 소유자 리뷰 후 병합한다.
3. A 행동 회귀와 기존 B pytest, frontend typecheck/build를 실행하고 결과를 인수인계에 기록한다.
4. 최신 main에 맞춘 codex/a-engine을 push하고 PR을 연다.

위험: B 서비스의 v1 snapshot/확정 저장 경로는 v2 전체 후보와 호환되지 않는다. RealEngine/AI 해석·서비스 연결과 C 독립 인수는 이 PR에서 완료했다고 주장하지 않는다. C 정답·eval·기존 미커밋 작업은 옮기지 않는다.

## TEL-046 검증 결과 (2026-10-16)

PASS: backend pytest 74개(A 67 + B 7), 정상/지연 직접 호출 + 독립 VALID, frontend typecheck/build.
프런트 로컬 런타임은 Node24.19.0/npm10.9.2이며 CI Node22 실행은 별도 확인 필요.
NOT CONFIGURED: scripts/check.sh(원격 저장소에 없음). SKIPPED: compose 검사(Docker CLI 없음), 화면/서버/실제 모델/C 독립 인수.
B 소유 contracts/v2 추가 리뷰 및 실제 API/DB 연결은 미완료다. 상세: docs/handoffs/A.md.

## TEL-047 — B 호환 경계 검토 (TEL-048로 대체)

B v1과 A v2의 입출력·확정 경계를 검토했다. 최종 구현은 아래 TEL-048을 따른다.
B 서비스에 context/DTO/저장 훅 추가를 요청하던 로컬 초안은 채택하지 않았다.

## TEL-048 — B 수정 없는 v1 EnginePort 채택 (TEL-047 대체)

- Owner A/Codex, codex/a-engine, Review. 소유: engine/, tests/engine/, docs/handoffs/A.md 및 이 작업 기록.
- 사용자 결정: B v1에 맞춘다. B DTO/service/DB/seed/프런트/registry 변경 없이 RealEngine()의 네 v1 서명으로 동작해야 한다. 추가 context·추가 결과 DTO·metadata 주입 요구는 제거한다.
- 범위: B native 필드/nullable rental_id/TRANSFER semantics 그대로 검사, B 설정의 demo clock 사용(없으면 서버 시각), 물리/기간 재고 및 제한 탐색. B가 저장할 수 있는 기존 업무 직원 변경·기존 창 내 AS 시간 변경만 자동 확정 후보로 제공. 신규 작업·개체 대체·회수/납품/TRANSFER/PREP 실행시각 변경·조건 확대는 NEEDS_REVIEW. 직접 v2 core의 원래 지원은 유지한다.
- 신뢰 경계: B의 사람 확인/revision/잠금 guard를 계속 사용한다. v1 validate는 전달된 전체 일정·기존 조건·자원·예약 검사를 수행하며 v2 전체 후보/확인 이력 검증을 주장하지 않는다. 모델은 별도, 미설정은 명시 오류.
- 계획: native v1 검사/가용성 → 제한 solver → 무인자 facade → B 실제 seed/API/DB confirm 및 재시작 후 검증 → 전체 회귀/문서.
- 수용 기준: exact B DTO JSON 왕복, 실제 B seed availability, 두 인자 validate, B 코드 불변 API create/confirm/requery 성공(지원 범위), 회수 지연/장비 대체 무저장 차단, malformed/time/skill/break/travel/booking/frozen 회귀.

TEL-048 결과: 기존 DTO와 두 인자 validate만 사용하는 native v1 RealEngine으로 전환했다. 추가 결과 DTO/context/metadata 주입·B 저장 훅 요구는 제거했다. 직접 v2 core와67개 시험은 유지한다. B 원본 seed의 nullable 대여 연결은 v1대로 허용하고 레코드를 생성하지 않는다. 원본 J-AS2/E1의 휴식 침범은 감지하며 직원 E2 변경으로 실제 B API/SQLite create→confirm→requery를 통과했다. 기존 창 안 AS 시각 조정도 동일 경로로 통과했다. 초안 무변경·멱등/중복409·새 엔진 재검증·Rental/Reservation/Dependency/Asset 불변 확인.

PASS `cd app/backend && .venv/bin/python -m pytest -q`:107 tests(v2 67+v1 33+B7), 외부 anyio deprecation1. PASS diff 공백/문서 링크, B 소유 코드/DTO/seed 무변경 검사. NOT CONFIGURED scripts/check.sh(없음). SKIPPED 프런트/infra 재빌드(변경 없음), 화면/Oracle/모델/C gold. Review 상태이며 codex/a-engine / PR #2에서 검토한다. 배포는 미실행이다.

커밋 전 최종 검사: PASS backend pytest107개, PASS frontend npm run build(Vite30 modules, 로컬 Node24.19.0/npm10.9.2). B 코드/DTO/DB/seed/프런트/infra는 변경하지 않았다. GitHub CI 결과는 PR 최신 head에서 별도로 확인한다.
