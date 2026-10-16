# 배포 가이드 (team-4-1, OCI 서울, aarch64)

목표: `https://rentwise.ccmall.shop` 에 접속하면 OCI 인스턴스에서 돌아가는 rentwise 가 뜨고, 확정한 계획이 Oracle DB 에 저장된다.

```
브라우저 ─HTTPS→ Cloudflare(rentwise.ccmall.shop) ─터널(서버가 밖으로 연결)→ cloudflared
   → web(nginx, Vue 정적 파일, /api 프록시) → api(FastAPI :8000) → db(Oracle Free :1521)
```

- 앱(web·api·cloudflared)은 team-4-1, **DB 는 team-4-2** 에 둡니다 → [DB_SPLIT.md](DB_SPLIT.md). 서버 1대로 돌리려면 `.env` 에 `DB_HOST=db`, `COMPOSE_PROFILES=localdb`.
- 외부에 여는 포트는 없습니다. HTTPS 는 Cloudflare 터널이 담당하고, DB·API 포트는 서버 밖으로 게시하지 않습니다.
- 이미지는 **서버에서 직접 빌드**합니다(aarch64 네이티브라 QEMU 불필요, 레지스트리 인증 불필요).

## 0. 사전 확인 (1분)

```bash
ssh opc@146.56.139.138 -i team-4-1.key
uname -m                  # aarch64
docker version && docker compose version
free -h && df -h /        # 여유 메모리 4GB+, 디스크 15GB+ 권장 (Oracle 이미지+데이터)
```

## 1. 코드 받기

```bash
git clone https://github.com/hacksungboo/rentwise_oci.git ~/rentwise_oci
cd ~/rentwise_oci/infra
```

## 2. Oracle 이미지가 ARM 을 지원하는지 확인 (DB 게이트)

```bash
docker buildx imagetools inspect gvenzl/oracle-free:23-slim | grep -A1 Platform
# linux/arm64 가 보여야 합니다
```

- 보이면 그대로 진행합니다.
- 안 보이면 `.env` 의 `DB_IMAGE` 를 공식 이미지 후보로 바꿔 같은 확인을 합니다:
  `container-registry.oracle.com/database/free:latest-lite` (공식 이미지는 앱 계정 자동 생성 방식이 달라 B에게 알려주세요)
- 둘 다 실패하면 PostgreSQL 로 DB 만 전환하는 비상안을 씁니다(명세 §9.2). 이 경우도 B에게 먼저 알려주세요.

## 3. 환경 변수

```bash
cp .env.example .env
vi .env
```

| 변수 | 값 |
|---|---|
| `CLOUDFLARE_TUNNEL_TOKEN` | [CLOUDFLARE_TUNNEL.md](CLOUDFLARE_TUNNEL.md) 에서 받은 `eyJ...` 토큰 |
| `ORACLE_PASSWORD`, `DB_PASSWORD` | 영문·숫자 조합 (특수문자는 URL 에 들어가 문제 생길 수 있음) |
| `SESSION_SECRET` | `openssl rand -hex 32` 결과 |
| `DEMO_ACCOUNTS` | 시연 계정. 비밀번호를 바꾸세요 |
| `ENGINE_MODE` | 지금은 `mock`. A 엔진 연동 후 `real` |

## 4. 배포

```bash
./scripts/deploy.sh            # origin/main 최신으로 빌드·기동, API 준비까지 대기
./scripts/check.sh             # 컨테이너·내부 경로·터널·공개 주소·포트 노출 점검
SMOKE_PASSWORD=<admin 비밀번호> ./scripts/smoke.sh   # 실제 Oracle 로 시연 동선 전체 시험
```

- **첫 기동은 Oracle 초기화 때문에 3~5분** 걸립니다. `docker compose logs -f db` 에서 `DATABASE IS READY TO USE!` 를 확인하세요.
- API 는 시작할 때 테이블을 만들고, DB 가 비어 있으면 시연 seed 를 넣습니다.
- `smoke.sh` 는 시작과 끝에 시연 데이터를 초기화합니다. 측정 기록이 있으면 먼저 `./scripts/backup.sh`.

## 5. 업데이트 / 롤백

**평소에는 PR 을 main 에 병합하면 자동 배포됩니다** → [CICD.md](CICD.md)

아래는 CD 를 쓸 수 없을 때의 비상용 수동 배포(서버에서 직접 빌드)입니다.

```bash
cd ~/rentwise_oci/infra
./scripts/deploy.sh                  # main 최신
./scripts/deploy.sh 3f2a9c1          # 특정 커밋으로 고정 또는 롤백
cat .deploy-history                  # 배포 이력 (시각, 커밋, ghcr=CD 배포)
```

**10-17 09:30 기능 동결 이후에는 커밋 SHA 를 지정해서만 배포**합니다.

## 6. 시연 전 체크리스트

- [ ] `./scripts/check.sh` 전부 ✓
- [ ] `./scripts/smoke.sh` 통과
- [ ] 다른 네트워크(휴대폰 LTE 등)에서 `https://rentwise.ccmall.shop` 로그인
- [ ] 화면 상단에 `Oracle DB`, 하단에 빌드 SHA 표시 확인
- [ ] 화면의 **시연 초기화** 버튼으로 처음 상태로 되돌려 두기

## 7. 문제 해결

| 증상 | 확인 |
|---|---|
| `deploy.sh` 가 준비 대기에서 끝남 | `docker compose logs api` → `DB 대기 중` 이면 DB 기동 중이거나 비밀번호 불일치 |
| `ORA-01017` | `.env` 의 `DB_PASSWORD` 를 바꿨는데 볼륨에는 예전 계정이 남아 있음. 시연 데이터만 있으면 `docker compose down && docker volume rm rentwise_oracle-data` 후 재배포 (**측정 기록이 있으면 먼저 백업**) |
| `ORA-12514` | DB 가 아직 기동 중이거나 서비스명(`FREEPDB1`) 불일치 |
| 공개 주소 502 | 터널 퍼블릭 호스트네임의 서비스가 `http://web:80` 인지 |
| 공개 주소 1033 | cloudflared 컨테이너 상태/토큰 확인 |
| 로그인은 되는데 버튼 누르면 403 `BAD_ORIGIN` | `.env` 의 `PUBLIC_HOSTNAME` 이 실제 접속 주소와 같은지 |
| 로그인 직후 다시 로그인 화면 | HTTP 로 접속 중인데 `COOKIE_SECURE=true`. 서버 안 디버깅(`127.0.0.1:8080`)일 때만 `false` |
| `exec format error` | 다른 아키텍처에서 빌드한 이미지. 서버에서 `deploy.sh` 로 다시 빌드 |

서버 안에서 화면 확인: 내 PC 에서 `ssh -L 8080:127.0.0.1:8080 opc@146.56.139.138 -i team-4-1.key` 후 `http://localhost:8080` (이때는 `COOKIE_SECURE=false` 필요).
