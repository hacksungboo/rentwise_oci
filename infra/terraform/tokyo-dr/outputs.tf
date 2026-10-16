output "dr_public_ip" {
  value = oci_core_instance.dr.public_ip
}

output "ssh" {
  value = "ssh opc@${oci_core_instance.dr.public_ip}"
}

output "image" {
  value = data.oci_core_images.ol9_arm.images[0].display_name
}

# 아래 두 URL 은 비밀번호와 같다. 채팅·GitHub 에 붙이지 말 것.
#   terraform output -raw backup_upload_url
output "backup_upload_url" {
  value     = "https://objectstorage.${var.region}.oraclecloud.com${oci_objectstorage_preauthrequest.upload.access_uri}"
  sensitive = true
}

output "backup_read_url" {
  value     = "https://objectstorage.${var.region}.oraclecloud.com${oci_objectstorage_preauthrequest.read.access_uri}"
  sensitive = true
}
