# 커밋 컨벤션

[Conventional Commits](https://www.conventionalcommits.org/ko/) 형식을 씁니다. 제목은 한국어로 써도 됩니다.

```
<type>(<scope>): <요약, 50자 이내>

<본문: 무엇을, 왜. 선택>

<꼬리말: 관련 이슈/시험 ID. 선택>
```

## type

| type | 언제 |
|---|---|
| `feat` | 기능 추가 |
| `fix` | 버그 수정 |
| `docs` | 문서만 변경 |
| `refactor` | 동작 변화 없는 구조 개선 |
| `test` | 테스트 추가·수정 |
| `chore` | 빌드, 의존성, 설정 |
| `ci` | GitHub Actions |
| `deploy` | compose, 배포 스크립트, 서버 설정 |
| `data` | seed, 시나리오, 정답 데이터 |

## scope (선택)

`api`, `db`, `web`, `engine`, `contracts`, `infra`, `fixtures`, `eval`, `docs`

## 예시

```
feat(api): 계획 확정 시 stale revision이면 409 반환

workspace 행 잠금 후 base_state_revision을 다시 비교한다.

시험: T10
```

```
data(fixtures): 회수 지연 시나리오 seed v1 추가
fix(web): 변경안 수정 후 확정 버튼이 활성화되던 문제
```

## 규칙

- 한 커밋은 한 가지 변경만 담습니다.
- 비밀값(.env, 키, 토큰)은 절대 커밋하지 않습니다.
- 커밋 전 테스트: `cd app/backend && pytest -q`, `cd app/frontend && npm run build`
