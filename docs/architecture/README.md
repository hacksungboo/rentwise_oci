# 아키텍처 그림

| 파일 | 내용 |
|---|---|
| `rentwise-oci.drawio` | 원본 (https://app.diagrams.net 또는 draw.io 데스크톱으로 열기·수정) |
| `rentwise-oci.png` | 미리보기 (draw.io 공식 뷰어로 렌더링) |
| `build_drawio.py` | 생성 스크립트 |

- 아이콘은 **Oracle 공식 OCI Architecture Diagram Toolkit** 아이콘만 사용했다(© Oracle). 파일 안에 이미지로 들어 있어 별도 라이브러리 없이 열린다. Cloudflare·GitHub·Grafana 등 외부 제품도 OCI 범용 아이콘(Internet, DevOps, Monitoring 등)에 이름표를 붙여 표현했다.
- 실선은 운영 중 경로, 점선은 전환·예정 경로(도쿄 스탠바이, 모니터링).
- draw.io 에서 직접 고쳐도 되고, 다시 만들려면 아이콘 폴더를 받아 `python3 build_drawio.py <OCI 아이콘 source 폴더>` (아이콘: github.com/rUser75/OCI-icons-for-plantuml 의 `source/`).
