# 서울(team-4-2) DB 백업을 받는 버킷. Always Free Object Storage 20GB 이내.
# 서울 서버에는 API 키 대신 "쓰기 전용 사전 인증 URL(PAR)" 만 준다.

data "oci_objectstorage_namespace" "ns" {
  compartment_id = var.tenancy_ocid
}

resource "oci_objectstorage_bucket" "backup" {
  compartment_id = local.compartment_id
  namespace      = data.oci_objectstorage_namespace.ns.namespace
  name           = var.bucket_name
  access_type    = "NoPublicAccess"
  storage_tier   = "Standard"
}

# 서울 → 업로드 전용 (조회·삭제 불가)
resource "oci_objectstorage_preauthrequest" "upload" {
  namespace    = data.oci_objectstorage_namespace.ns.namespace
  bucket       = oci_objectstorage_bucket.backup.name
  name         = "seoul-db-upload"
  access_type  = "AnyObjectWrite"
  time_expires = var.par_expires
}

# 도쿄 DR 서버 → 목록 조회 + 다운로드 전용
resource "oci_objectstorage_preauthrequest" "read" {
  namespace             = data.oci_objectstorage_namespace.ns.namespace
  bucket                = oci_objectstorage_bucket.backup.name
  name                  = "tokyo-dr-read"
  access_type           = "AnyObjectRead"
  bucket_listing_action = "ListObjects"
  time_expires          = var.par_expires
}
