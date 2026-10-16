# CI/CD

```
PR 생성 ──▶ ci.yml   백엔드 pytest · 프론트 타입검사/빌드 · compose 문법
                          │
main 병합 ─▶ cd.yml   ① 같은 CI 재실행
                      ② ARM64 이미지 빌드 (ubuntu-24.04-arm, 서버와 같은 aarch64)
                      ③ GHCR 저장  ghcr.io/hacksungboo/rentwise-{api,web}:<커밋 SHA>, :latest
                      ④ SSH 로 team-4-1 접속 → git checkout <SHA> → deploy-image.sh
                         → 새 이미지로 api·web 교체 → 해당 SHA 로 응답 + DB ready 확인
                         → 3분 안에 준비 안 되면 직전 버전으로 자동 롤백
                      ⑤ 공개 주소 https://rentwise.ccmall.shop 에서 새 SHA 확인
```

- DB 컨테이너와 데이터 볼륨은 배포 때 건드리지 않습니다.
- 배포는 한 번에 하나씩 순서대로 실행됩니다(`concurrency`).
- 서버는 배포할 때만 Actions 의 임시 토큰(GITHUB_TOKEN)으로 GHCR 에 로그인했다가 바로 로그아웃합니다. 서버에 장기 토큰을 저장하지 않습니다.

## 최초 설정 (한 번만)

### 1. 배포 전용 SSH 키 만들기 (team-4-1 에서)

팀이 받은 인스턴스 키를 GitHub 에 올리지 않고, **배포 전용 키를 따로** 만듭니다. 문제가 생기면 이 키만 지우면 됩니다.

```bash
ssh opc@146.56.139.138 -i team-4-1.key

ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N "" -C "github-actions-deploy"
cat ~/.ssh/github_deploy.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/github_deploy          # ← 출력 전체를 복사 (BEGIN/END 줄 포함). 아래 DEPLOY_SSH_KEY
```

### 2. 서버 지문 (known_hosts) 만들기 (team-4-1 에서)

서버 자신의 공개 호스트 키로 만들기 때문에 중간자 공격 걱정이 없습니다.

```bash
for f in /etc/ssh/ssh_host_ed25519_key.pub /etc/ssh/ssh_host_ecdsa_key.pub; do
  [ -f "$f" ] && echo "146.56.139.138 $(cut -d' ' -f1,2 "$f")"
done                               # ← 출력 전체를 복사. 아래 DEPLOY_KNOWN_HOSTS
```

복사가 끝나면 서버의 개인키 파일은 지워도 됩니다: `rm ~/.ssh/github_deploy` (공개키는 authorized_keys 에 남아 있음)

### 3. GitHub Secrets 등록

저장소 → **Settings → Secrets and variables → Actions → New repository secret**

| 이름 | 값 |
|---|---|
| `DEPLOY_HOST` | `146.56.139.138` |
| `DEPLOY_USER` | `opc` |
| `DEPLOY_SSH_KEY` | 1번의 개인키 전체 (`-----BEGIN OPENSSH PRIVATE KEY-----` ~ `-----END ...-----`) |
| `DEPLOY_KNOWN_HOSTS` | 2번 출력 전체 |

### 4. 서버 상태 확인

- `~/rentwise_oci` 에 저장소가 있고 `infra/.env` 가 채워져 있어야 합니다 (이미 완료).
- 서버의 opc 계정이 `docker` 명령을 sudo 없이 쓸 수 있어야 합니다 (이미 사용 중).

## 사용

- **자동 배포:** PR 을 main 에 병합하면 끝. Actions 탭의 `cd` 에서 진행 상황을 봅니다.
- **수동 재배포:** Actions → `cd` → **Run workflow**
- **특정 버전으로 되돌리기 (서버에서):**
  ```bash
  cd ~/rentwise_oci/infra && grep ghcr .deploy-history        # 배포 이력
  docker login ghcr.io -u <깃허브아이디>                       # 패키지가 private 이면 PAT(read:packages)
  ./scripts/deploy-image.sh <SHA>
  ```
- **CD 가 막혔을 때 비상 배포:** 서버에서 `./scripts/deploy.sh` (서버에서 직접 빌드)

## 문제 해결

| 증상 | 확인 |
|---|---|
| deploy 단계 `Permission denied (publickey)` | `DEPLOY_SSH_KEY` 에 개인키 전체가 들어갔는지, 서버 authorized_keys 에 공개키가 있는지 |
| `Host key verification failed` | `DEPLOY_KNOWN_HOSTS` 값 확인 (2번 다시 실행) |
| `denied: permission_denied` (push) | 저장소 Settings → Actions → General → Workflow permissions 가 막혀 있지 않은지 |
| 서버에서 `pull access denied` | 패키지와 저장소 연결 확인: GitHub 프로필 → Packages → rentwise-api → Package settings → 저장소 접근에 rentwise_oci 가 있는지 |
| 롤백됨 | Actions 로그의 `docker compose logs api` 출력 확인 |
