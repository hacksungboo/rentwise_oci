# 브랜치 전략

해커톤 기간이 짧아서 **GitHub Flow**(main + 짧은 작업 브랜치)를 씁니다. develop 브랜치는 두지 않습니다.

## 브랜치

| 브랜치 | 용도 | 규칙 |
|---|---|---|
| `main` | 항상 배포 가능한 상태. 서버(team-4-1)는 main을 배포 | 직접 push 금지, PR로만 병합 |
| `feat/<역할>-<주제>` | 기능 개발 | 예: `feat/a-solver`, `feat/b-confirm-api`, `feat/c-seed-v1` |
| `fix/<역할>-<주제>` | 버그 수정 | 예: `fix/b-stale-plan-409` |
| `docs/<주제>` | 문서만 변경 | 예: `docs/deploy-guide` |
| `chore/<주제>` | 설정, 의존성, CI | 예: `chore/ci-arm64` |

역할 접두어: `a`(AI 해석·배정), `b`(화면·API·DB·배포·통합), `c`(데이터·정답·측정·발표)

## 작업 흐름

```bash
git checkout main && git pull
git checkout -b feat/a-solver
# 작업 → 커밋 (COMMIT_CONVENTION.md 참고)
git push -u origin feat/a-solver
# GitHub에서 PR 생성 → 템플릿 채우기 → 리뷰 1명 → Squash merge
```

- 브랜치는 **작게, 자주** 병합합니다. 반나절 넘게 살아 있는 브랜치는 만들지 않습니다.
- 병합 방식은 **Squash merge**(PR 하나 = main 커밋 하나).
- PR 전에 `git fetch origin && git rebase origin/main`으로 최신화합니다.
- 다른 역할의 소유 경로([OWNERSHIP.md](OWNERSHIP.md))를 수정해야 하면 PR 본문에 적고 소유자에게 리뷰를 받습니다.
- 공용 계약(`app/backend/rentwise/contracts/`) 변경은 B가 병합하며 A·C 확인을 받습니다.

## 리뷰 규칙

- 최소 1명 승인. 급하면 작성자 본인 + 슬랙/카톡 공유 후 병합 가능(시연 전 마지막 3시간 제외).
- **10-17 09:30 기능 동결 이후**에는 버그 수정 PR만 받고, 배포는 커밋 SHA 태그로 고정합니다.
