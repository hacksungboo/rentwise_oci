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

## 다음 단계 (별도 PR)

1. team-4-2: 매시간 `expdp` → 업로드 URL 로 `curl -T` (cron)
2. 도쿄: 단일 서버 모드(`DB_HOST=db`, `COMPOSE_PROFILES=localdb`)로 GHCR 이미지 기동, 최신 덤프 `impdp` 복원 스크립트
3. Cloudflare 에 두 번째 터널 → `dr.rentwise.ccmall.shop`
4. 장애 리허설: team-4-2 DB 중지 → 도쿄 복원 → 메인 호스트네임 전환, 소요 시간 기록

## 정리 (해커톤 후)

```bash
terraform destroy
```
