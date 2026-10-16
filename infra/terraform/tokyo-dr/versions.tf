terraform {
  required_version = ">= 1.5"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 6.0.0"
    }
  }
}

# 인증: 로컬은 ~/.oci/config 의 DEFAULT 프로필을 자동으로 사용.
#       OCI Resource Manager 로 실행하면 인증이 자동 주입되므로 그대로 동작.
provider "oci" {
  region = var.region
}
