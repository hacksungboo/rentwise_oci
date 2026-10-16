# 도쿄 DR (개인 OCI 프리티어, Terraform)

서울(주최측 테넌시) 운영 환경의 **리전 간 백업 + 웜 스탠바이**를 개인 테넌시 도쿄(홈 리전) Always Free 로 만든다.

```
[서울 · 주최측]                                   [도쿄 · 개인 Always Free]
team-4-1 web·api ─▶ team-4-2 Oracle
                       │ 매시간 expdp
                       └─ HTTPS PUT (쓰기 전용 PAR) ─▶ Object Storage: rentwise-backup
                                                          │ 장애 시 최신 덤프 (읽기 전용 PAR)
                                                          ▼
                                                    rentwise-dr (A1 2 OCPU/12GB)
                                                    web·api·Oracle 단일 서버 모드
                                                    └─ 별도 터널 → dr.rentwise.ccmall.shop
```

- 실시간 복제가 아니다. Oracle Free 에는 Data Guard 가 없고, 두 테넌시 사이 사설망 연결도 없다. 목표치: **RPO 1시간 / RTO 수 분** (리허설로 측정해 발표에 사용).
- 서울 서버에는 개인 계정 키를 두지 않는다. 버킷 **쓰기 전용 URL** 만 준다.

## Terraform 이 만드는 것 (`infra/terraform/tokyo-dr`)

| 리소스 | 내용 | 프리티어 |
|---|---|---|
| VCN·서브넷·IGW·라우트 | 10.10.0.0/16, 퍼블릭 서브넷 1개 | 무료 |
| 보안 목록 | 인바운드 **SSH(22) 내 IP 만**. 서비스는 터널이라 개방 없음 | 무료 |
| 인스턴스 `rentwise-dr` | VM.Standard.A1.Flex 2 OCPU / 12GB, Oracle Linux 9 aarch64, 부트 50GB, cloud-init 으로 Docker·git 설치 + 저장소 클론 | A1 한도·블록 200GB 이내 |
| 버킷 `rentwise-backup` | 비공개, Standard | 20GB 이내 |
| PAR 2개 | 업로드 전용(서울용), 목록+다운로드 전용(도쿄용) | 무료 |

## 1. 준비 (내 PC, 10분)

1. **Terraform 설치**: https://developer.hashicorp.com/terraform/install (macOS: `brew install terraform`)
2. **OCI API 키 만들기** (개인 계정 콘솔)
   - 우측 상단 프로필 → **My profile** → **API keys** → **Add API key** → *Generate API key pair* → 개인키 다운로드
   - 화면에 나온 설정 내용을 `~/.oci/config` 에 붙여넣고, `key_file=` 을 다운로드한 키 경로로 수정
   - `chmod 600 ~/.oci/*.pem`
3. **SSH 키** (없으면): `ssh-keygen -t ed25519 -f ~/.ssh/rentwise-dr`
4. **내 공인 IP**: `curl ifconfig.me`

> 설치가 번거로우면 OCI 콘솔의 **Resource Manager → Stacks** 에 이 폴더를 zip 으로 올려도 된다(인증 자동). 이 문서는 로컬 기준.

## 2. 생성

```bash
cd infra/terraform/tokyo-dr
cp terraform.tfvars.example terraform.tfvars
vi terraform.tfvars        # tenancy_ocid(~/.oci/config 의 tenancy), ssh_public_key(~/.ssh/rentwise-dr.pub 내용), ssh_allowed_cidr(내IP/32)

terraform init
terraform plan             # 생성될 리소스 확인 (13개 내외)
terraform apply            # yes
terraform output           # dr_public_ip, ssh
```

- **`Out of host capacity`** 가 나오면 도쿄 A1 재고 부족이다. 몇 분 뒤 `terraform apply` 를 다시 실행하면 된다(만들어진 네트워크·버킷은 그대로 두고 인스턴스만 다시 시도).
- `LimitExceeded` 면 이미 다른 A1 이 한도를 쓰고 있다. `terraform.tfvars` 에 `ocpus = 1`, `memory_gb = 6` (Oracle Free 는 6GB 로도 동작).

## 3. 접속 확인 (3~5분 뒤)

```bash
ssh -i ~/.ssh/rentwise-dr opc@$(terraform output -raw dr_public_ip)
ls /var/lib/rentwise-dr-ready && docker version && ls ~/rentwise_oci   # cloud-init 완료 확인
```

## 4. 비밀 URL 다루기

```bash
terraform output -raw backup_upload_url   # → team-4-2 의 db-server/.env 에 넣을 값 (다음 단계)
terraform output -raw backup_read_url     # → 도쿄 서버의 infra/.env 에 넣을 값 (다음 단계)
```

- 두 URL 은 **비밀번호와 같다.** 채팅·GitHub·슬라이드에 붙이지 않는다. 유출되면 `terraform apply -replace=oci_objectstorage_preauthrequest.upload` 로 새로 발급.
- `terraform.tfstate` 에도 들어 있으므로 커밋 금지(.gitignore 처리됨). 팀원과 공유할 필요 없음.

## 5. 서울 → 도쿄 매시간 백업 (인스턴스 없이도 동작)

백업은 **앱 서버(team-4-1)** 에서 api 컨테이너가 DB 의 모든 `rw_*` 표를 JSON 으로 내보내 압축한 뒤, 도쿄 버킷의 쓰기 전용 URL 로 올린다. Oracle Data Pump 나 OCI 키가 필요 없고, 어떤 서버의 DB 로도 복원할 수 있다.

```bash
# 내 PC (terraform 폴더)
terraform output -raw backup_upload_url        # 복사 (채팅·GitHub 금지)

# team-4-1
cd ~/rentwise_oci/infra && git pull
vi .env                                        # BACKUP_UPLOAD_URL=https://objectstorage.ap-tokyo-1.oraclecloud.com/p/.../o/
./scripts/backup.sh                            # 1회 시험: ... upload=ok:rentwise/seoul/rentwise-<시각>.json.gz
./scripts/install-backup-cron.sh               # 매시간 17분 자동 실행
tail -f backups/backup.log                     # 실행 기록
```

- 로컬 `infra/backups/` 에 최근 48개 보관, 버킷에는 계속 쌓인다(파일 수 KB, 20GB 무료 한도와 무관).
- OCI 콘솔 → Object Storage → `rentwise-backup` → `rentwise/seoul/` 에서 파일이 보이면 성공.
- 업로드 실패 시 로그에 `upload=FAIL`, 스크립트 종료 코드 1.

## 6. 복원

```bash
./scripts/restore.sh backups/rentwise-<시각>.json.gz     # 로컬 파일로
./scripts/restore.sh latest                              # 버킷 최신 (.env 에 BACKUP_READ_URL 필요)
```

- 복원 전 내용 요약(state_revision, 현행 계획, 표별 행 수)을 보여주고 확인을 받는다. 직전 상태는 `backups/pre-restore-*.json.gz` 로 남긴다.
- 한 트랜잭션으로 전체 교체 → 실패하면 원래 상태 유지.

## 7. 도쿄 스탠바이 (인스턴스가 생기면)

```bash
ssh -i ~/.ssh/rentwise-dr opc@<dr_public_ip>
cd ~/rentwise_oci/infra && cp .env.example .env && vi .env
#   DB_HOST=db, COMPOSE_PROFILES=localdb          ← 단일 서버 모드
#   ORACLE_PASSWORD / DB_PASSWORD / SESSION_SECRET / DEMO_ACCOUNTS  (서울과 같게 해도 됨)
#   CLOUDFLARE_TUNNEL_TOKEN=<dr 터널 토큰>, PUBLIC_HOSTNAME=dr.rentwise.ccmall.shop
#   SERVER_LABEL=OCI ap-tokyo-1 · rentwise-dr
#   BACKUP_READ_URL=<terraform output -raw backup_read_url>
echo "$GHCR_TOKEN" | docker login ghcr.io -u <github id> --password-stdin   # 패키지가 비공개면
./scripts/deploy-image.sh <서울과 같은 커밋 SHA>     # Oracle 첫 기동 3~5분
./scripts/restore.sh latest                          # 서울 최신 백업 적용 → 소요 시간이 RTO
```

Cloudflare: Zero Trust → Tunnels → 새 터널 `rentwise-dr` → 토큰 복사, Public hostname `dr.rentwise.ccmall.shop` → `http://web:80`.

## 8. 장애 리허설 (발표용 수치)

1. 서울에서 `./scripts/backup.sh` 실행 시각 기록 (=마지막 백업 시점)
2. team-4-2 `docker stop rentwise-db` → 서울 화면 오류 확인
3. 도쿄 `./scripts/restore.sh latest --yes` → `dr.rentwise.ccmall.shop` 로그인·화면 확인, 걸린 시간 = RTO
4. 데이터 손실 범위 = 마지막 백업 이후 (매시간이면 RPO ≤ 1시간)
5. 서울 복구: `docker start rentwise-db`

## 정리 (해커톤 후)

```bash
terraform destroy
```
