variable "tenancy_ocid" {
  description = "개인 테넌시 OCID (콘솔 → 프로필 → Tenancy)"
  type        = string
}

variable "compartment_ocid" {
  description = "리소스를 만들 컴파트먼트. 비우면 루트(테넌시)"
  type        = string
  default     = ""
}

variable "region" {
  description = "홈 리전이어야 Always Free 가 적용됨"
  type        = string
  default     = "ap-tokyo-1"
}

variable "ssh_public_key" {
  description = "인스턴스 접속용 SSH 공개키 내용 (ssh-ed25519 AAAA...)"
  type        = string
}

variable "ssh_allowed_cidr" {
  description = "SSH(22) 허용 대역. 내 공인 IP/32 권장 (curl ifconfig.me)"
  type        = string
}

# Always Free A1 한도: 테넌시 전체 2 OCPU / 12GB (2026 기준 문서)
variable "ocpus" {
  type    = number
  default = 2
}

variable "memory_gb" {
  type    = number
  default = 12
}

variable "boot_volume_gb" {
  description = "Always Free 블록 스토리지 합계 200GB 이내"
  type        = number
  default     = 50
}

variable "repo_url" {
  type    = string
  default = "https://github.com/hacksungboo/rentwise_oci.git"
}

variable "bucket_name" {
  type    = string
  default = "rentwise-backup"
}

variable "par_expires" {
  description = "백업 업로드/조회용 사전 인증 URL 만료 시각 (RFC3339)"
  type        = string
  default     = "2026-11-30T00:00:00Z"
}
