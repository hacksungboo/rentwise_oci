# 인프라 설계와 운영 (rentwise)

> 전체 그림: [architecture/rentwise-oci.drawio](architecture/rentwise-oci.drawio) (draw.io 로 열기, 아이콘은 Oracle 공식 OCI 아이콘)
> 세부 절차 문서: [CICD.md](CICD.md) · [DB_SPLIT.md](DB_SPLIT.md) · [TOKYO_DR.md](TOKYO_DR.md) · [CLOUDFLARE_TUNNEL.md](CLOUDFLARE_TUNNEL.md) · [AI_REAL_MODE.md](AI_REAL_MODE.md) · [DEPLOY_GUIDE.md](DEPLOY_GUIDE.md)

## 1. 한눈에 보기

```
사용자 ─HTTPS─▶ Cloudflare (rentwise.ccmall.shop, TLS 종료)
                    │  Cloudflare Tunnel (서버가 밖으로 연결, 인바운드 포트 0개)
┌ OCI 서울 ap-seoul-1 (주최측 테넌시) ─────────────────────────────────────────────┐
│ VCN(주최측) · 퍼블릭 서브넷 10.0.0.0/24 · AD-1 · Fault Domain 1                   │
│  team-4-1  10.0.0.198  A1.Flex 4 OCPU / 24GB       team-4-2  10.0.0.218  A1.Flex  │
│   cloudflared → web(nginx) → api(FastAPI) ──1521──▶  Oracle AI Database 26ai Free │
│   backup.sh (매시간)                                 (모니터링 스택 예정)           │
└───────────────│───────────────────────────────────────────────────────────────────┘
                │ HTTPS · AES-256 암호화 파일 · 쓰기 전용 URL
┌ OCI 도쿄 ap-tokyo-1 (개인 Always Free 테넌시) ───────────────────────────────────┐
│ Object Storage rentwise-backup (비공개)      VCN 10.10.0.0/16 · 서브넷 10.10.1.0/24 │
│                                              rentwise-dr (Terraform 정의, 미기동)  │
└───────────────────────────────────────────────────────────────────────────────────┘
GitHub (PR → CI) → main 병합 → Actions(ARM64 빌드) → GHCR → SSH 배포 → 자동 롤백
```

| 항목 | 값 |
|---|---|
| 서비스 주소 | https://rentwise.ccmall.shop |
| 네트워크 | 리전 ap-seoul-1 · AP-SEOUL-1-AD-1 · 두 서버 모두 FAULT-DOMAIN-1 · 퍼블릭 서브넷 10.0.0.0/24 (게이트웨이 10.0.0.1) · VCN CIDR 은 주최측 관리 |
| 앱 서버 | team-4-1 · 사설 10.0.0.198 · VM.Standard.A1.Flex(aarch64) 4 OCPU / 24GB |
| DB 서버 | team-4-2 · 사설 10.0.0.218 · VM.Standard.A1.Flex(aarch64) 4 OCPU / 24GB |
| DB | Oracle AI Database 26ai Free (`gvenzl/oracle-free:23-slim`), PDB `FREEPDB1` |
| 앱 | Vue 3 + nginx(web), FastAPI(api), Docker Compose |
| 외부 공개 | Cloudflare Tunnel 만 (서버에 80/443 인바운드 없음) |
| 이미지 저장소 | GHCR `ghcr.io/hacksungboo/rentwise-{api,web}:<커밋 SHA>` |
| 백업 저장소 | OCI 도쿄 Object Storage `rentwise-backup` |
| IaC | Terraform `infra/terraform/tokyo-dr` (도쿄 VCN·인스턴스·버킷·PAR) |

## 2. 외부 접근: Cloudflare Tunnel

- 사용자는 `https://rentwise.ccmall.shop` 로 접속하고, TLS 인증서·종료는 Cloudflare 가 맡는다.
- team-4-1 의 `cloudflared` 컨테이너가 **밖으로** Cloudflare 에 연결을 유지하고, 요청은 그 연결을 거꾸로 타고 `web:80`(nginx) 으로 들어온다.
- 그래서 **서버에 여는 인바운드 포트가 없다.** 공인 IP 로 직접 들어오는 웹 요청 경로 자체가 없고, DDoS·스캔은 Cloudflare 앞단에서 걸러진다.
- nginx 는 정적 화면을 주고 `/api` 만 같은 Docker 네트워크의 `api:8000` 으로 넘긴다. api·DB 포트는 서버 밖으로 게시하지 않는다(`127.0.0.1:8080` 디버깅용만).
- 세션 쿠키 `HttpOnly; Secure; SameSite=Lax`, 변경 요청은 Origin 검사.

## 3. 서울 리전 DB 노드 분리 (team-4-1 앱 / team-4-2 DB)

```
team-4-1 (10.0.0.198)                         team-4-2 (10.0.0.218)
 cloudflared → web → api ──사설망 TCP 1521──▶  Oracle Free (host 네트워크)
```

- **이유**: 앱 배포·재시작과 DB 가 메모리·디스크·장애를 나눠 갖지 않게. CD 는 앱 서버만 교체하고 DB 서버는 배포 때 건드리지 않는다.
- **접근 제한 (2중)**: OCI 보안 목록의 1521 허용 + team-4-2 `firewalld` rich rule 로 **10.0.0.198 에서 오는 1521 만** 허용(`infra/db-server/firewall.sh`).
- Docker 포트 게시(`-p`)는 firewalld 를 우회하므로, DB 는 **host 네트워크**로 띄워 방화벽 규칙이 그대로 적용되게 했다.
- DB 연결 정보는 양쪽 서버의 `.env` 로만 주입(이미지·저장소에 없음). 앱은 기동 시 DB 를 최대 10분 기다린 뒤 표를 만들고, 비어 있으면 seed 를 넣는다.
- 되돌리기: `.env` 의 `DB_HOST=db`, `COMPOSE_PROFILES=localdb` 로 단일 서버 모드 전환(절차: DB_SPLIT.md).

## 4. CI/CD

```
PR ─▶ ci.yml      백엔드 pytest(190+) · 프론트 타입검사/빌드 · compose 문법 · terraform fmt/validate
                      │
main 병합 ─▶ cd.yml  ① 같은 CI 재사용(workflow_call)
                     ② ARM64 네이티브 빌드 (GitHub ubuntu-24.04-arm 러너, 서버와 같은 aarch64, QEMU 없음)
                     ③ GHCR 푸시: rentwise-{api,web}:<커밋 SHA>, :latest  (빌드 캐시: GitHub Actions cache)
                     ④ SSH(배포 전용 키) → team-4-1: git checkout <SHA> → deploy-image.sh <SHA>
                          · Actions 임시 토큰(GITHUB_TOKEN)으로 GHCR 로그인 → pull → 로그아웃
                          · api·web 만 교체(DB·볼륨 불변)
                          · /api/v1/version 의 build_sha == SHA 이고 DB ready 일 때까지 최대 3분 대기
                          · 실패하면 직전 성공 SHA 로 자동 롤백, 이력은 infra/.deploy-history
                          · 성공하면 배포 SHA 를 .env 에 기록(누가 compose 를 직접 실행해도 같은 버전)
                     ⑤ 공개 주소 https://rentwise.ccmall.shop 에서 새 SHA 응답 확인
```

| 설계 결정 | 이유 |
|---|---|
| 커밋 SHA 태그로만 배포 | 화면 하단·`/version` 의 SHA 로 실행 중 버전을 증명, 정확한 롤백 |
| ARM 러너 네이티브 빌드 | 서버가 aarch64. 에뮬레이션 빌드보다 빠르고 `exec format error` 위험 없음 |
| `concurrency: deploy-production` | 연속 병합 시 배포가 겹치지 않고 순서대로 |
| 배포 전용 SSH 키 + `known_hosts` 고정 | 팀 인스턴스 키를 GitHub 에 올리지 않음, 중간자 공격 방지. 문제 시 이 키만 폐기 |
| 서버에 장기 레지스트리 토큰 없음 | 배포마다 Actions 임시 토큰으로 로그인 후 즉시 로그아웃 |
| 블루/그린 미도입 | 단일 앱 서버·짧은 대회 일정. 대신 준비 확인 + 자동 롤백으로 실패 배포를 막음 |
| 비상 경로 | CD 장애 시 서버에서 `scripts/deploy.sh <SHA>` 로 직접 빌드 배포 |

GitHub Secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS` (값은 저장소에 없음).

## 5. 매시간 백업 → 도쿄 Object Storage

```
team-4-2 Oracle ──1521──▶ team-4-1 api 컨테이너: python -m rentwise.backup export (모든 rw_* 표 → JSON)
                          → gzip → 무결성 검사(gzip -t)
                          → AES-256-CBC 암호화(PBKDF2 20만 회) + HMAC-SHA256
                          → HTTPS PUT (쓰기 전용 사전 인증 URL)
                          ▶ 도쿄 rentwise-backup/rentwise/seoul/rentwise-<UTC시각>.json.gz.enc
cron: 매시간 17분 (scripts/install-backup-cron.sh), 기록: infra/backups/backup.log
```

- **백업 방식**: 앱 계층 논리 백업. DB 종류와 무관하고 Oracle Data Pump·OCI 계정 키가 필요 없다. 복원은 한 트랜잭션으로 전체 교체하며 실패하면 원래 상태가 유지된다. 확정 후 백업 → 초기화 → 복원하면 같은 상태로 돌아오는 것을 자동 시험으로 확인한다.
- **보관**: 서버 로컬 최근 48개, 버킷은 누적(파일 수 KB 수준, Always Free 20GB 이내).
- **복원**: `scripts/restore.sh <파일>` 또는 `scripts/restore.sh latest`(버킷 최신). 복원 전 요약(state_revision·현행 계획·표별 행 수)을 보여주고 확인을 받으며, 직전 상태를 `pre-restore-*` 로 남긴다.
- **목표치**: RPO ≤ 1시간(매시간 백업), RTO = 스탠바이 기동 + 복원 시간(리허설로 측정).

### 백업 경로의 보안 조치

| 위험 | 조치 |
|---|---|
| 전송 중 도청·변조 | Oracle 공식 엔드포인트로 HTTPS(TLS) 전송, 서버 인증서 검증. 인바운드 포트 개방 없음(서버 → 밖 방향만) |
| 서울 서버에 클라우드 계정 키 보관 | 두지 않음. 대신 버킷 전용 **사전 인증 요청(PAR) URL** 만 사용 |
| 업로드 URL 유출 | **쓰기 전용**(조회·목록·삭제 불가)이라 기존 백업을 읽거나 지울 수 없음. 만료일 설정(2026-11-30), 의심 시 `terraform apply -replace=…` 로 즉시 재발급 |
| 조회 URL 유출 | 서울 서버에는 두지 않고 복원 서버에만. 새어도 파일이 암호화돼 있어 키 없이 읽을 수 없음 |
| 버킷·파일 자체 노출 | 버킷 `NoPublicAccess` + 저장 시 Oracle 관리 키 암호화 + **업로드 전 클라이언트 측 AES-256 암호화** |
| 백업 파일 위·변조 | HMAC-SHA256 검사 실패 시 복원 중단(키 불일치·손상 포함) |
| 평문 업로드 실수 | 암호화 키가 없으면 업로드 자체를 거부 |
| 비밀값 노출 | URL·암호화 키·DB 비밀번호·OpenAI 키는 서버 `.env` 로만 주입. `.env`·`*.tfstate`·`*.tfvars`·`infra/backups/` 는 `.gitignore`, 로그·DB 기록에 키·원문 미저장 |
| 백업 내용 | 합성 시연 데이터 + AI 호출 메타데이터. 로그인 비밀번호(환경변수)·API 키는 백업에 들어가지 않음 |

## 6. 도쿄 리전 DR 설계

### 설계 (Terraform 으로 코드화, `infra/terraform/tokyo-dr`)

| 리소스 | 상태 | 내용 |
|---|---|---|
| VCN `rentwise-dr-vcn` 10.10.0.0/16, 퍼블릭 서브넷 10.10.1.0/24, IGW, 라우트 | **생성됨** | 서울(10.0.0.0/24)과 겹치지 않는 대역 |
| 보안 목록 | **생성됨** | 인바운드 SSH(22) 관리자 IP/32 만. 서비스는 터널이라 개방 없음 |
| Object Storage `rentwise-backup` + PAR 2개 | **생성됨·사용 중** | 업로드 전용(서울), 목록·다운로드 전용(도쿄) |
| 인스턴스 `rentwise-dr` A1.Flex 2 OCPU / 12GB (또는 1/6), OL9 aarch64, cloud-init(Docker·git·저장소) | **정의만, 미기동** | 아래 한계 참고 |

전환 시 도쿄 인스턴스는 같은 저장소·같은 GHCR 이미지(aarch64)·같은 compose 를 **단일 서버 모드**(`DB_HOST=db`, `COMPOSE_PROFILES=localdb`)로 띄우고, 최신 백업을 복원한 뒤 별도 터널(`dr.rentwise.ccmall.shop`)로 연다. 장애 시 Cloudflare 에서 메인 호스트네임을 DR 터널로 돌리면 사용자 주소는 그대로다.

### 웜 스탠바이를 상시 띄우지 못한 이유 (프리티어 한계)

1. **A1 용량 부족**: 도쿄 리전 Always Free A1 은 수요가 많아 `Out of host capacity`(500) 가 반복됐다. 사양을 1 OCPU / 6GB 로 낮추고 자동 재시도를 걸어도 대회 시간 안에 할당되지 않았다.
2. **Always Free 범위**: 무료 컴퓨트·블록 스토리지는 테넌시 **홈 리전에서만**, A1 은 테넌시 합계 2 OCPU / 12GB 까지다. 서울 운영 인스턴스는 주최측 테넌시라 도쿄를 같은 테넌시에 둘 수 없고, 개인 테넌시(홈 리전 도쿄)를 써야 했다.
3. **테넌시 분리**: 서울(주최측)·도쿄(개인)가 다른 테넌시라 VCN 원격 피어링(양쪽 IAM 정책 필요)·실시간 복제를 쓸 수 없다. Oracle Free 에디션에는 Data Guard 도 없다. 그래서 **암호화 백업 + 스탠바이 복원** 방식을 택했다.

### 그래도 언제든 전환할 수 있는 이유

- **데이터는 이미 도쿄에 있다**: 매시간 암호화 백업이 도쿄 버킷에 쌓이고 있다(인스턴스와 무관).
- **인프라는 코드로 준비돼 있다**: 용량이 생기는 즉시 `terraform apply` 한 번으로 인스턴스가 만들어지고 cloud-init 이 Docker·저장소까지 준비한다. 네트워크·버킷은 이미 생성돼 있어 인스턴스만 남았다.
- **앱은 이식 가능하다**: 같은 aarch64 이미지·같은 compose·단일 서버 모드, 복원 스크립트 `restore.sh latest` 로 버킷 최신 백업을 내려받아 위변조 검사·복호화·복원까지 한 번에 한다.
- 전환 절차·리허설 순서: [TOKYO_DR.md](TOKYO_DR.md) 7~8장.

## 7. 모니터링 (team-4-2) — 상세: [MONITORING.md](MONITORING.md)

```
team-4-1 Alloy ─┐ (사설망 push)                team-4-2
team-4-2 Alloy ─┴──▶ Prometheus(메트릭, 3일) · Loki(로그, 3일) ──▶ Grafana
                                                              └─ Cloudflare 터널 호스트네임으로 접근
```

- 수집: 호스트 CPU·메모리·디스크, 컨테이너 상태·재시작, 모든 컨테이너 로그(api·web·db·cloudflared).
- 대시보드: 서비스 상태, API 요청·오류(nginx 로그), **AI 해석 호출**(api 로그의 `ai.interpret` 줄: 성공/실패, 토큰, 지연), 로그 검색.
- 보안: 모두 host 네트워크 + firewalld 로 3000·3100·9090 을 team-4-1 사설 IP 에서만 허용, Grafana 는 터널로만 공개(로그인 필수).
- CI 가 PR 마다 전체 스택을 띄워 대시보드의 모든 쿼리를 실제로 실행해 확인한다.
- 4-2 에 두는 이유: 수집 경로가 사설망 안에서 끝나 외부 노출이 없고, 서버 여유(24GB 중 사용 약 3GB)가 충분하다(추가 약 1GB). 도쿄는 테넌시가 달라 수집 경로를 인터넷에 열어야 해서 제외.

## 8. 보안 요약

- 인바운드: 웹 0개(Cloudflare Tunnel), DB 1521 은 앱 서버 사설 IP 만(보안 목록 + firewalld), 도쿄 SSH 는 관리자 IP/32 만.
- 비밀값: 전부 서버 `.env`(커밋 금지) 또는 GitHub Secrets. 이미지·저장소·로그·DB 에 없음.
- 배포: 전용 SSH 키, 호스트 키 고정, 임시 레지스트리 토큰, SHA 고정 배포와 자동 롤백.
- 백업: TLS + 클라이언트 측 AES-256 + HMAC, 쓰기 전용/조회 전용 PAR 분리, 만료일.
- AI: 사용 한도(`AI_BUDGET_USD`) 초과 시 모델 호출 자체를 막고, 호출마다 토큰·비용·지연을 기록(원문·키 미기록).

## 9. 한계와 다음 단계

| 항목 | 현재 | 다음 |
|---|---|---|
| 장애 도메인 | 두 서버가 같은 FAULT-DOMAIN-1 | 서로 다른 Fault Domain 에 배치(하드웨어 장애 분리) |
| 앱 서버 이중화 | 단일(team-4-1) | OCI LB + 앱 2대 또는 블루/그린 |
| DB 고가용성 | 단일 + 매시간 백업 | 유료 에디션 Data Guard / Autonomous DB |
| 도쿄 DR | 백업 저장·IaC 준비, 인스턴스 미기동 | 용량 확보 시 웜 스탠바이 상시 기동, 정기 복원 리허설 |
| RPO | ≤ 1시간 | 백업 주기 단축 또는 변경 로그 전송 |
| 모니터링 | Alloy·Prometheus·Loki·Grafana | 알림(디스코드/메일) 연동 |
