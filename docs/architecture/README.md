# 아키텍처 그림

| 파일 | 내용 |
|---|---|
| `rentwise-oci.drawio` | 원본 (https://app.diagrams.net 또는 draw.io 데스크톱으로 열기·수정) |
| `rentwise-oci.png` | 미리보기 (draw.io 공식 뷰어로 렌더링) |
| `build_drawio.py` | 생성 스크립트 |

- 아이콘: OCI 자원(Region·VCN·Subnet·Compute·IGW·Object Storage·보안)은 **Oracle 공식 OCI Architecture Diagram Toolkit**, 소프트웨어(Cloudflare·Nginx·Vue·FastAPI·Oracle·Docker·Alloy·Prometheus·Loki·Grafana·GitHub·Terraform·OpenAI 등)는 각 기술 로고(`icons/`, 기존 팀 아키텍처 그림 및 simple-icons). 모두 파일 안에 이미지로 들어 있어 별도 라이브러리 없이 열린다. 각 로고의 상표권은 해당 소유자에게 있다.
- 기존 MoongCheap/Jithub Oracle 페이지 스타일(OCI Region · VCN · Availability Domain · Subnet 상자, 짧은 영문 라벨)을 따른다. 세부 설명은 INFRASTRUCTURE.md 에.
- 실선은 운영 중 경로, 점선은 DR(도쿄 스탠바이) 경로.
- draw.io 에서 직접 고쳐도 되고, 다시 만들려면 아이콘 폴더를 받아 `python3 build_drawio.py <OCI 아이콘 source 폴더>` (아이콘: github.com/rUser75/OCI-icons-for-plantuml 의 `source/`).
