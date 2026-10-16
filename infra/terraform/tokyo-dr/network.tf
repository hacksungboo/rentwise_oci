# 인바운드는 SSH 만. 서비스 트래픽은 Cloudflare 터널(서버 → 밖) 이라 포트를 열지 않는다.

resource "oci_core_vcn" "dr" {
  compartment_id = local.compartment_id
  cidr_blocks    = ["10.10.0.0/16"]
  display_name   = "rentwise-dr-vcn"
  dns_label      = "rwdr"
}

resource "oci_core_internet_gateway" "dr" {
  compartment_id = local.compartment_id
  vcn_id         = oci_core_vcn.dr.id
  display_name   = "rentwise-dr-igw"
  enabled        = true
}

resource "oci_core_route_table" "dr" {
  compartment_id = local.compartment_id
  vcn_id         = oci_core_vcn.dr.id
  display_name   = "rentwise-dr-rt"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.dr.id
  }
}

resource "oci_core_security_list" "dr" {
  compartment_id = local.compartment_id
  vcn_id         = oci_core_vcn.dr.id
  display_name   = "rentwise-dr-sl"

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }

  ingress_security_rules {
    description = "SSH (관리자 IP 만)"
    source      = var.ssh_allowed_cidr
    protocol    = "6"
    tcp_options {
      min = 22
      max = 22
    }
  }

  ingress_security_rules {
    description = "Path MTU discovery"
    source      = "0.0.0.0/0"
    protocol    = "1"
    icmp_options {
      type = 3
      code = 4
    }
  }
}

resource "oci_core_subnet" "public" {
  compartment_id             = local.compartment_id
  vcn_id                     = oci_core_vcn.dr.id
  cidr_block                 = "10.10.1.0/24"
  display_name               = "rentwise-dr-public"
  dns_label                  = "pub"
  route_table_id             = oci_core_route_table.dr.id
  security_list_ids          = [oci_core_security_list.dr.id]
  prohibit_public_ip_on_vnic = false
}
