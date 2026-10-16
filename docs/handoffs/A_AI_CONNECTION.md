# B 담당 전달 — A AI 엔진 최소 연결

2026-10-16 · A/Codex · TEL-049/050 · codex/a-ai-intent의 AI PR.
기준: main `1cd1186`(DB 분리 PR #7·배포 이미지 고정 PR #8 포함). 기존 A 공개 기반 `e0e8c9a` 이후 AI 변경.
이 문서는 전달용이다. B에게 메시지를 보내거나 운영 서버를 수정한 것은 아니다.

## 최소 연결 범위

**기존 AS 방문창 안 시각 변경**을 자연어→사람 확인→계산→확정으로 연결한다.
B의 intent/EnginePort/API 필드·저장 구조는 유지한다. 네 업무를 해석하지만 신규/장비 대체/회수·납품·이동 실행시간 변경의 자동 확정은 여전히 지원 밖이다.

| 항목 | A에서 처리한 내용 | B 조치 |
|---|---|---|
| 누락 AS 기한 | 유일하게 선택된 기존 AS이고 새 시작이 원래 창 안이면 기존 기한을 확인 초안에 제시. 원문 추출과 구분한 한국어 질문 유지 | 기존 체크박스·기한 입력 그대로 사용. 17시 추천 버튼 수정 불필요 |
| 누락 기존 품목 | 대상 작업과 고객이 일치하면 기존 품목 참조를 표시. 모델이 품목 모호함을 표시한 경우에는 유지 | 기존 품목별 service_minutes 추천 그대로 사용 |
| 화면에 없는 확인 항목 | 질문 삭제·자동 승인 대신 AI_REVIEW_UNSUPPORTED / payload=null. 여러 작업이면 전부 차단 | 기존 오류 배너로 표시 가능. 전체 업무 지원 UI는 후속 |
| 비용 저장 | 시도 상한·reserve/settle/unknown 호출·시간초과/재시도 제어 제공 | **필수: 영속·원자적 BudgetPort 구현** |
| 엔진 생성 | RealEngine(budget=adapter), 기존 네 메서드 서명 유지 | **필수: engine_registry의 real 생성 한 곳에 adapter 주입** |
| 환경 | OPENAI_API_KEY, 기본 gpt-5.6-luna. 키/원장 미설정은 유료 호출 차단 | **필수: 서버 키·허용 예산 설정 후 ENGINE_MODE=real** |

## 1. 비용원장 — 운영 AI 전에 필수

현재 B에는 구현이 없다. 팀 계약의 서버 내부 인터페이스:

```python
from decimal import Decimal
from rentwise.contracts.types import Usage
from rentwise.engine.interpret import BudgetExceeded

# B가 구현할 영속 adapter의 서명 (아래 클래스는 구현 예시가 아님)
class PersistentBudgetAdapter:
    def reserve(self, attempt_key: str, max_cost_usd: Decimal) -> str: ...
    def settle(self, reservation_id: str, usage: Usage, price_version: str) -> None: ...
    def mark_unknown(self, reservation_id: str, reason: str) -> None: ...
```

- reserve는 짧은 트랜잭션에서 잔액/한도 검사와 예약을 원자적으로 처리한다. 같은 attempt_key에는 같은 예약 ID를 반환한다. 부족하면 BudgetExceeded를 발생시키거나 문자열 BUDGET_EXCEEDED를 반환한다.
- A는 재시도·별도 호출마다 다른 키를 사용한다. request/revision만 같다는 이유로 이전 예약을 재사용하면 실제 별도 호출 비용을 놓친다.
- settle은 Usage의 모델 토큰 수로 정산한다. 중복 정산은 이중 차감하지 않고 원래 결과로 끝나야 한다. 예약/정산 실패 시 이미 확보된 상한을 잃지 않는다.
- timeout/usage 없음은 mark_unknown으로 예약을 유지한다. 앱 오류가 났다는 이유로 비용을 0으로 되돌리지 않는다.
- **요청 처리 트랜잭션과 별도로 커밋해야 한다.** 현재 B의 interpret API는 tx 안에서 모델을 호출하고 오류면 ApiError로 롤백한다. 같은 conn에 비용을 쓰면 모델 사용 후 해석 실패 시 비용원장도 사라질 수 있다. 비용 adapter는 독립된 짧은 트랜잭션을 열고 네트워크를 기다리며 원장 행 잠금을 잡지 않는다. SQLite와 Oracle에서 실제로 검증한다.
- 모델키/원문/연락처를 원장에 저장하지 않는다. reservation_id, attempt_key, 상태, 상한/정산액, usage, price_version, 오류 코드 등 필요한 서버 메타데이터만 저장한다.
- 이번 로컬 개발의 $0.05 승인은 **운영 총예산 설정이 아니다.** 운영 예산·허용 모델은 운영자가 정한다. FakeBudget/ProbeBudget을 운영 서버에 넣지 않는다.

현재 가격 정책: `PRICE_VERSION=openai-standard-2026-10-16`, Luna 입력 $0.20 / cached $0.02 / 출력 $1.20 per 1M.
캐시 쓰기 1.25배까지 고려한 시도당 예약 상한 **$0.0044**, 최대2시도다.
공용 Usage에는 cache_write_tokens가 없으므로, 미캐시 입력에 1.25배를 적용해 보수적으로 정산하면 상한을 넘지 않는다.
정확한 캐시 쓰기 비용을 따로 기록하려면 공용 계약 변경으로 협의하며 A/B가 별도 도메인 Usage를 복제하지 않는다.

## 2. 단일 주입 지점과 설정 — 필수

수정 위치: `app/backend/rentwise/engine_registry.py`의 real 분기.

```python
from rentwise.engine import RealEngine

# budget_adapter는 위 계약에 맞춰 B가 만든 서버의 영속 adapter 인스턴스
return RealEngine(budget=budget_adapter)
```

별도 AI 서버·새 HTTP DTO·스키마 버전·solver 호출 변경은 필요 없다. 기존 get_engine 캐시가 엔진/adapter를 재사용한다.
ENGINE_MODE=real과 OPENAI_API_KEY를 서버 프로세스에 주입한다. 기존 compose는 이 키를 전달한다.
OPENAI_MODEL을 생략하면 gpt-5.6-luna, 다른 모델을 사용하려면 A의 가격/사용 정책 등록이 필요하다.
키를 이미지·코드·프런트 변수에 넣지 않는다. A는 상위 `.env`를 자동 탐색하거나 로드하지 않는다.
DB 분리는 DATABASE_URL 설정으로 B가 처리하며 A는 DB 서버 주소를 알 필요가 없다.
다중 worker로 늘리면 동시 AI1을 프로세스 전체에 적용할 별도 서버 제어가 필요하다(현재 A Lock은 프로세스 단위).

## 3. 기존 화면에서의 확인 동작

입력 예: `오늘 J-AS1 정수기 AS 방문을 오전 10시 15분으로 변경해 주세요.`

- A가 추출한 시작10:15, 기존 업무의 품목 WP-A, 기존 기한11:00을 표시한다.
- 기한 질문은 "원문에 새 완료 기한이 없습니다. 기존 작업의 완료 기한 …11:00을 유지합니까?"이다.
- 종료는 미정 상태를 유지한다. B의 기존 `시작 + 현장 40분` 버튼을 누르면10:55가 된다.
- 기한 체크를 하기 전에는 `ready=false`이고 서버도 UNCONFIRMED_FIELDS로 계산을 막는다.
- 기한 체크 뒤 사람 확인 PUT → 기존 plan/confirm 흐름을 사용한다. 모델이 기한을 명시했거나 모호하다고 한 경우 A가 기존 기한으로 덮어쓰지 않는다.
- 원래 방문창 밖 시각·다른 대상/기한 확대를 자동 승인하지 않는다. 사용자가 기한을17시로 다시 바꾸면 기존 solver가 거절할 수 있다.

현재 seed에는 별도 **J-AS2/E1 휴식 충돌**이 있다. A의 API 시험에서는 기존 overrides로 E2를 명시해 이 문제를 분리했다.
현재 화면은 해당 override를 보내지 않는다. 실제 화면 시연 전에 B/C가 적합한 seed·담당자 배치를 검수하거나 기존 직원 변경 경로를 연결해야 한다.
A가 seed를 바꾸거나 AI가 직원 E2를 골랐다고 주장하지 않는다.

## 4. 오류와 후속 화면 작업

현재 B는 InterpretationResult ERROR를 HTTP502로 내보내며 code/message/retryable을 전달한다.

| 코드 | 의미 / 사용자 경로 |
|---|---|
| AI_NOT_CONFIGURED | 서버 키 없음. 설정 확인 또는 수동 입력 |
| AI_BUDGET_NOT_CONFIGURED | adapter 주입 없음. real 생성 지점 확인 |
| BUDGET_EXCEEDED / AI_BUDGET_UNAVAILABLE | 예산 부족·원장 실패. 자동 재호출 대신 수동 검토 |
| AI_REVIEW_UNSUPPORTED | 원문은 해석됐으나 현 화면에서 고객·대여 종료일·업무 종류 등의 확인을 완료할 수 없음. 지원 조건을 원문에 명시하거나 수동 검토 |
| AI_SCHEMA_INVALID / AI_REFUSED / AI_INCOMPLETE / AI_TIMEOUT | 유효한 해석으로 저장하지 않음. 조건 재입력·수동 검토 |

AI_REVIEW_UNSUPPORTED의 상세 paths는 내부 DomainError.details에 있다. 현재 B 서비스는 details를 HTTP에 전달하지 않으므로 화면은 code/message만 사용하면 된다.
에러 배너 표시는 기존 코드로 된다. 다만 현재 UI에는 AI 오류 후 수동 조건 입력으로 전환하는 동선이 없으므로 **오류 시 수동 시연까지 필요하면** 이 버튼/폼은 B의 추가 작업이다. 기존 PUT interpretation API는 사용 가능하다.
고객 선택/대여 종료일·무기한/지원하지 않는 요청 취소·재작성 등을 화면에서 직접 처리하려면 후속으로 해당 입력을 추가한다. 무기한 null을 '미확인'과 구분해 확인할 수 있어야 한다. 새 편집 항목을 추가하면 A의 `b_review.py` 허용 필드도 함께 갱신해야 한다.
그 전에 A의 확인 질문을 제거하거나 숨은 값을 자동 승인해서 우회하지 않는다. 신규 대여/이동 자동 확정은 UI 외에 B 저장 범위 확장도 별도 필요하다.

## B 인수 검사

1. 실제 원장 adapter와 fake ModelClient로 reserve 중복·잔액 경합·정산 중복·unknown 유지·API 롤백 후 원장 잔존을 SQLite/Oracle에서 검사한다.
2. real registry로 해석 성공, AI origin/usage 저장, 요청 수정 후 revision 거절, 사람 확인 전 계산422를 확인한다.
3. 기존 AS 창 안 요청에서 종료 추천·기한 확인 → READY → confirm → DB 재조회. seed 충돌을 별도로 해결하고 사람/AI 담당 선택을 구분한다.
4. 키/원장/예산/모델/입력 불가 오류 배너와 필요한 수동 동선을 확인한다. A 해석 대역 단위시험과 실제 모델·운영 원장·화면 인수를 구분한다.
5. DB 분리 적용은 `docs/DB_SPLIT.md`대로 별도 서버 연결·Oracle read/write·재시작 지속성을 검증한다. A에서는 이 운영 작업을 수행하지 않았다.

현재 A 결과와 정확한 실행 증거는 [A 인수인계](A.md)의 TEL-050/051에 기록한다. 사용자가 이후 commit/push/PR을 승인해 새 AI PR로 제출한다. main 병합·배포와 B 운영 연결은 별도다.
