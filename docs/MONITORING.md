# 모니터링 (Alloy → Prometheus · Loki → Grafana)

```
team-4-1 (10.0.0.198)   mon-alloy ──사설망 push (9090 · 3100)──┐
                                                               ▼
team-4-2 (10.0.0.218)   mon-alloy ──▶ mon-prometheus :9090 (메트릭 3일) ─┐
                                      mon-loki       :3100 (로그 3일)  ─┴─▶ mon-grafana :3000
                                                                            ▲
사용자 ─HTTPS─▶ Cloudflare (grafana.ccmall.shop) ─터널─▶ team-4-1 cloudflared ┘ (사설망 3000)
```

| 수집 | 내용 |
|---|---|
| 호스트 | CPU · 메모리 · 디스크 · 네트워크 (Alloy `prometheus.exporter.unix`) |
| 컨테이너 | 컨테이너별 CPU · 메모리 · 실행 여부 (Alloy 내장 cAdvisor) |
| 서비스 응답 | 공개 주소 `https://rentwise.ccmall.shop/api/v1/health/ready` 30초마다 확인 (blackbox) |
| 로그 | 모든 Docker 컨테이너(api · web · cloudflared · db · 모니터링) → Loki. api 의 `ai.interpret` 줄은 `ai_status` 라벨(OK/ERROR) |

대시보드 **rentwise 운영** (Grafana 홈): 서비스 상태·응답 시간 · AI 해석 성공/실패(24h)·지연·토큰 · API 오류 로그 · HTTP 요청(상태 코드별) · 서버 CPU/메모리/디스크 · 컨테이너 CPU/메모리 · AI 해석 기록 · 컨테이너 로그 검색.

- 앱 코드는 바꾸지 않았다. AI 지표는 api 가 이미 남기는 한 줄 로그(`ai.interpret … status= tokens_in= latency_ms=`)에서 뽑는다.
- 사용 자원: team-4-2 추가 약 1GB 메모리, 디스크는 보관 3일 기준 수백 MB.
- CI(`ci.yml` 의 monitoring 작업)가 PR 마다 전체 스택을 띄우고 대시보드의 모든 쿼리를 실제로 실행해 확인한다.

## 보안

- 모든 컨테이너 **host 네트워크** + firewalld 규칙. Docker 포트 게시는 firewalld 를 우회하므로 쓰지 않는다.
- team-4-2 의 3000 · 3100 · 9090 은 **team-4-1 사설 IP(10.0.0.198)에서만** 허용(`firewall.sh`). 인터넷에 직접 열지 않는다.
- Grafana 는 Cloudflare 터널로만 공개, 관리자 로그인 필수(가입·익명 접근 끔), 비밀번호는 `.env` 로만. 원하면 Cloudflare Access(이메일 인증)를 앞에 추가.
- Alloy 는 수집을 위해 Docker 소켓·호스트 경로를 **읽기 전용**으로 마운트한다(privileged). UI 는 127.0.0.1 에서만.

## 설치 (약 15분)

### 0. OCI 보안 목록 (콘솔, 한 번)

VCN → 서브넷의 보안 목록 → 수신 규칙 추가: 소스 `10.0.0.198/32`, TCP, 대상 포트 `3000,3100,9090`.
(1521 을 열 때와 같은 방식. 이미 VCN 내부 전체를 허용했다면 생략)

### 1. team-4-2 (모니터링 서버)

```bash
ssh opc@131.186.25.47 -i team-4-2.key
cd ~/rentwise_oci && git pull
cd infra/monitoring
cp .env.example .env && vi .env        # GRAFANA_ADMIN_PASSWORD 만 채우면 됨 (영문·숫자 12자+)
./firewall.sh                           # 3000·3100·9090 ← 10.0.0.198 만
docker compose up -d
docker compose ps                       # mon-prometheus · mon-loki · mon-grafana · mon-alloy 모두 Up
```

### 2. team-4-1 (앱 서버)

```bash
ssh opc@146.56.139.138 -i team-4-1.key
cd ~/rentwise_oci && git pull
cd infra/monitoring
cat > .env <<'ENV'
COMPOSE_PROFILES=agent
HOST_LABEL=team-4-1
MON_HOST=10.0.0.218
ENV
timeout 3 bash -c "</dev/tcp/10.0.0.218/9090" && timeout 3 bash -c "</dev/tcp/10.0.0.218/3100" && echo "연결 OK"
docker compose up -d                    # mon-alloy 만
```

### 3. 확인 (team-4-2, 2분 뒤)

```bash
cd ~/rentwise_oci/infra/monitoring
GRAFANA_ADMIN_PASSWORD='<비밀번호>' python3 ci_check.py team-4-1
GRAFANA_ADMIN_PASSWORD='<비밀번호>' python3 ci_check.py team-4-2
```

모두 ✓ 면 끝. 서버 안에서 화면을 먼저 보려면: 내 PC 에서 `ssh -L 3000:127.0.0.1:3000 opc@131.186.25.47 -i team-4-2.key` → http://localhost:3000 (이때는 `.env` 에 `GRAFANA_COOKIE_SECURE=false`).

### 4. 공개 주소 연결 (Cloudflare)

Zero Trust → Networks → Tunnels → 기존 rentwise 터널 → **Public hostname 추가**
- Subdomain `grafana`, Domain `ccmall.shop`
- Service `HTTP` · `10.0.0.218:3000`

→ https://grafana.ccmall.shop 에서 `admin` / `.env` 의 비밀번호로 로그인. 홈 화면이 **rentwise 운영** 대시보드.

## 문제 해결

| 증상 | 확인 |
|---|---|
| team-4-1 `연결 OK` 안 나옴 | 0번 보안 목록, team-4-2 `sudo firewall-cmd --list-rich-rules` 에 3100·9090 규칙 |
| 대시보드에 team-4-1 이 없음 | team-4-1 `docker logs mon-alloy --tail 50` 에서 `connection refused`/`timeout` → 위 항목 |
| 컨테이너 패널만 비어 있음 | `docker logs mon-alloy` 에 cadvisor 오류. 나머지 수집에는 영향 없음 |
| Grafana 502 (공개 주소) | 터널 Service 가 `10.0.0.218:3000` 인지, team-4-2 방화벽 3000 규칙 |
| 로그인 후 바로 튕김 | http 로 접속 중인데 `GRAFANA_COOKIE_SECURE=true`. 공개 주소(https)로 접속하거나 false |
| 디스크가 걱정 | `.env` 의 `RETENTION=1d` 후 `docker compose up -d` (Loki 는 loki.yml 의 `retention_period`) |

내리기: `docker compose down` (데이터 유지) / `docker compose down -v` (데이터 삭제). 앱·DB 에는 영향 없음.
