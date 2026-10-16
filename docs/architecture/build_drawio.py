"""rentwise OCI 아키텍처 draw.io 생성기.

아이콘: Oracle 공식 OCI Architecture Diagram Toolkit 아이콘(PNG, github.com/rUser75/OCI-icons-for-plantuml 의 source/)
        을 파일 안에 data URI 로 넣어 draw.io 에서 별도 라이브러리 없이 열린다.
  python3 build_drawio.py <OCI 아이콘 source 폴더>   →  rentwise-oci.drawio
"""
import base64
import html
import sys
from pathlib import Path

ICON_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "source")
OUT = Path(__file__).with_name("rentwise-oci.drawio")

ICONS = {
    "user": "IdentitySecurity/User.png",
    "users": "IdentitySecurity/UserGroupunisex.png",
    "internet": "Other/InternetCloud.png",
    "vm": "Compute/VirtualMachine.png",
    "flexvm": "Compute/FlexVirtualMachineVM.png",
    "igw": "Networking/InternetGateway.png",
    "vcn": "Groups/VCN.png",
    "subnet": "Groups/Subnet.png",
    "seclist": "IdentitySecurity/SecurityLists.png",
    "firewall": "IdentitySecurity/Firewall.png",
    "db": "Database/DatabaseSystem.png",
    "bucket": "Storage/Buckets.png",
    "objstore": "Storage/ObjectStorage.png",
    "backup": "Storage/BackupRestore.png",
    "encrypt": "IdentitySecurity/Encryption.png",
    "key": "IdentitySecurity/KeyManagement.png",
    "container": "DeveloperServices/Containers.png",
    "registry": "DeveloperServices/ContainerRegistry.png",
    "devops": "DeveloperServices/DevOps.png",
    "iac": "DeveloperServices/ResourceManager.png",
    "monitoring": "ObservabilityAndManagement/Monitoring.png",
    "logging": "ObservabilityAndManagement/Logging.png",
    "analytics": "ObservabilityAndManagement/LoggingAnalytics.png",
    "alarm": "ObservabilityAndManagement/Alarms.png",
    "dr": "ObservabilityAndManagement/FullStackDisasterRecovery.png",
    "genai": "AnalyticsAI/GenerativeAI.png",
    "dns": "Networking/DomainNameSystemDNS.png",
    "apigw": "DeveloperServices/APIGateway.png",
    "cloud": "Other/OtherCloudServices.png",
}

INK = "#312D2A"
ORANGE = "#AE562C"
GRAY = "#9E9892"
GREEN = "#2D5967"
FONT = "fontFamily=Helvetica;"

cells: list[str] = []
_n = [100]


def nid() -> str:
    _n[0] += 1
    return f"c{_n[0]}"


def esc(s: str) -> str:
    return html.escape(s, quote=True).replace("\n", "&#xa;")


def box(x, y, w, h, label="", stroke=GRAY, dashed=False, fill="none", font=12, bold=True, align="left",
        valign="top", rounded=0, color=INK, sw=1.5, cid=None, sl=10):
    cid = cid or nid()
    style = (f"rounded={rounded};whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth={sw};"
             f"dashed={1 if dashed else 0};verticalAlign={valign};align={align};spacingLeft={sl};spacingTop=4;"
             f"fontSize={font};fontStyle={1 if bold else 0};fontColor={color};{FONT}container=0;")
    cells.append(f'<mxCell id="{cid}" value="{esc(label)}" style="{style}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    return cid


def icon(name, x, y, label="", size=48, font=11, pos="bottom", cid=None, opacity=100, lw=150):
    cid = cid or nid()
    data = base64.b64encode((ICON_DIR / ICONS[name]).read_bytes()).decode()
    style = (f"shape=image;html=1;imageAspect=1;aspect=fixed;image=data:image/png,{data};"
             f"verticalLabelPosition=bottom;verticalAlign=top;labelPosition=center;align=center;"
             f"noLabel=1;opacity={opacity};")
    cells.append(f'<mxCell id="{cid}" value="" style="{style}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{size}" height="{size}" as="geometry"/></mxCell>')
    if label:
        lines = label.count("\n") + 1
        if pos == "right":
            text(x + size + 6, y + size / 2 - 8 * lines, lw, 16 * lines, label, font=font)
        else:
            text(x + size / 2 - lw / 2, y + size + 2, lw, 15 * lines, label, font=font, align="center")
    return cid


def text(x, y, w, h, label, font=11, bold=False, color=INK, align="left"):
    cid = nid()
    style = (f"text;html=1;whiteSpace=wrap;align={align};verticalAlign=middle;fontSize={font};"
             f"fontStyle={1 if bold else 0};fontColor={color};{FONT}")
    cells.append(f'<mxCell id="{cid}" value="{esc(label)}" style="{style}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    return cid


def edge(src, dst, label="", dashed=False, color=INK, pts=(), exit=None, entry=None, font=10, both=False, sw=1.5):
    cid = nid()
    ex = f"exitX={exit[0]};exitY={exit[1]};exitDx=0;exitDy=0;" if exit else ""
    en = f"entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;" if entry else ""
    style = (f"edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor={color};strokeWidth={sw};"
             f"dashed={1 if dashed else 0};endArrow=block;endFill=1;{'startArrow=block;startFill=1;' if both else ''}"
             f"fontSize={font};fontColor={color};{FONT}labelBackgroundColor=#FFFFFF;{ex}{en}")
    p = "".join(f'<mxPoint x="{a}" y="{b}"/>' for a, b in pts)
    pts_xml = f'<Array as="points">{p}</Array>' if pts else ""
    cells.append(f'<mxCell id="{cid}" value="{esc(label)}" style="{style}" edge="1" parent="1" source="{src}" target="{dst}">'
                 f'<mxGeometry relative="1" as="geometry">{pts_xml}</mxGeometry></mxCell>')
    return cid


# =========================================================================== 제목
text(20, 10, 900, 30, "rentwise — OCI 시스템 아키텍처 (서울 운영 · 도쿄 DR · CI/CD · 모니터링)", font=18, bold=True)
text(20, 38, 900, 20, "실선: 운영 중 경로   점선: 전환/예정 경로   아이콘: Oracle OCI Architecture Diagram Toolkit", font=11, color="#6F6964")

# =========================================================================== 외부
users = icon("users", 60, 80, "사용자 / 심사위원\n(브라우저)", size=52)
cf = icon("internet", 560, 80, "Cloudflare\nrentwise.ccmall.shop\nDNS · TLS 인증서 · Tunnel", size=56, lw=190, pos="right")
openai = icon("genai", 900, 80, "OpenAI API\ngpt-5.6-luna\nStructured Outputs", size=52, lw=150, pos="right")
edge(users, cf, "HTTPS 요청")

# =========================================================================== 서울 리전
REG_X, REG_Y, REG_W, REG_H = 20, 200, 1110, 640
box(REG_X, REG_Y, REG_W, REG_H, "Oracle Cloud Infrastructure — 서울 리전 ap-seoul-1 (주최측 테넌시)", stroke=GRAY, dashed=True, font=13)
vcn_x, vcn_y, vcn_w, vcn_h = 50, 250, 1050, 570
box(vcn_x, vcn_y, vcn_w, vcn_h, "VCN (주최측 제공)  ·  사설 IP 10.0.0.x", stroke=ORANGE, font=12, sl=36)
icon("vcn", vcn_x + 6, vcn_y + 3, "", size=24)
igw = icon("igw", 700, 228, "Internet Gateway — 나가는 연결만\n(터널 · GHCR · OpenAI · 백업 업로드)", size=40, font=10, pos="right", lw=240)
sub_x, sub_y, sub_w, sub_h = 70, 295, 1010, 510
box(sub_x, sub_y, sub_w, sub_h, "서브넷 10.0.0.0/24  ·  보안 목록: 웹 인바운드 0개, 1521 은 VCN 내부만", stroke=ORANGE, dashed=True, font=11, bold=False, sl=34)
icon("subnet", sub_x + 6, sub_y + 3, "", size=22)

# ---- team-4-1
a_x, a_y, a_w, a_h = 95, 350, 470, 430
box(a_x, a_y, a_w, a_h, "team-4-1  (앱 서버)\n사설 10.0.0.198 · 공인 146.56.139.138\nVM.Standard.A1.Flex · aarch64 · 4 OCPU / 22GB · Docker Compose",
    stroke=GREEN, fill="#F5F4F2", font=11)
icon("flexvm", a_x + a_w - 56, a_y + 8, "", size=44)
tun = icon("container", a_x + 45, a_y + 85, "cloudflared\nTunnel 커넥터", size=44, lw=120)
web = icon("container", a_x + 205, a_y + 85, "web\nnginx + Vue 3", size=44, lw=120)
api = icon("container", a_x + 365, a_y + 85, "api  FastAPI :8000\nA 엔진(해석·배정)\n비용 장부 · AI 호출 기록", size=44, lw=150)
alloy1 = icon("container", a_x + 45, a_y + 225, "Alloy (예정)\n메트릭 · 컨테이너 로그", size=44, opacity=70, lw=140)
dep = icon("container", a_x + 205, a_y + 225, "deploy-image.sh\nSHA 고정 · 준비 확인\n실패 시 자동 롤백", size=44, lw=140)
bk = icon("backup", a_x + 365, a_y + 225, "backup.sh (cron 매시간)\n논리 백업 → gzip\n→ AES-256 + HMAC", size=44, lw=150)
text(a_x + 250, a_y + 335, 215, 50, "외부 공개 포트 없음\n비밀값은 infra/.env 로만 주입\n(DB·OpenAI 키·백업 URL·암호화 키·터널 토큰)", font=10, color="#6F6964")
edge(tun, web, "http://web:80")
edge(web, api, "/api 프록시")

# ---- team-4-2
b_x, b_y, b_w, b_h = 600, 350, 455, 430
box(b_x, b_y, b_w, b_h, "team-4-2  (DB · 모니터링 서버)\n사설 10.0.0.218 · 공인 131.186.25.47\nVM.Standard.A1.Flex · aarch64 · 4 OCPU / 22GB",
    stroke=GREEN, fill="#F5F4F2", font=11)
icon("flexvm", b_x + b_w - 56, b_y + 8, "", size=44)
db = icon("db", b_x + 60, b_y + 82, "Oracle AI Database 26ai Free\nFREEPDB1 · host 네트워크 :1521", size=48, lw=200)
fw = icon("firewall", b_x + 300, b_y + 86, "firewalld\n1521 ← 10.0.0.198 만", size=40, lw=140)
box(b_x + 15, b_y + 195, b_w - 30, 220, "모니터링 스택 (배포 예정 · 보관 3일)", stroke=GRAY, dashed=True, font=10)
alloy2 = icon("container", b_x + 45, b_y + 275, "Alloy", size=40, opacity=70, lw=80)
prom = icon("monitoring", b_x + 185, b_y + 228, "Prometheus · 메트릭", size=36, opacity=70, lw=130)
loki = icon("logging", b_x + 185, b_y + 318, "Loki · 로그", size=36, opacity=70, lw=100)
graf = icon("analytics", b_x + 335, b_y + 275, "Grafana\n대시보드", size=40, opacity=70, lw=90)
text(b_x + 120, b_y + 380, 320, 30, "서버 · 컨테이너 · API 요청/오류\nAI 해석 호출 · 로그 검색", font=10, color="#6F6964")
edge(alloy2, prom, "", dashed=True, color=GRAY)
edge(alloy2, loki, "", dashed=True, color=GRAY)
edge(prom, graf, "", dashed=True, color=GRAY)
edge(loki, graf, "", dashed=True, color=GRAY)

edge(api, db, "TCP 1521 · 사설망", exit=(1, 0.5), entry=(0, 0.5),
     pts=((a_x + 480, a_y + 107), (a_x + 480, b_y + 106)))
edge(alloy1, alloy2, "메트릭·로그 push (사설망, 예정)", dashed=True, color=GRAY, exit=(0.5, 1), entry=(0.5, 1),
     pts=((a_x + 67, a_y + 400), (b_x + 65, a_y + 400)))
edge(cf, tun, "Cloudflare Tunnel (서버 → 밖 연결 유지, 요청은 역방향)", exit=(0.5, 1), entry=(0.5, 0),
     pts=((588, 330), (a_x + 67, 330)))
edge(api, openai, "HTTPS · 해석 요청 (한도·토큰·비용 기록)", exit=(0.5, 0), entry=(0.5, 1),
     pts=((a_x + 387, 330), (926, 330)))
text(860, 176, 230, 16, "grafana 호스트네임 (예정)", font=10, color=GRAY)
edge(cf, graf, "", dashed=True, color=GRAY, exit=(0.9, 1), entry=(1, 0.5),
     pts=((610, 195), (1100, 195), (1100, b_y + 295)))

# =========================================================================== 도쿄 리전
T_X, T_Y, T_W, T_H = 1170, 200, 610, 640
box(T_X, T_Y, T_W, T_H, "Oracle Cloud Infrastructure — 도쿄 리전 ap-tokyo-1 (개인 Always Free 테넌시 · DR)", stroke=GRAY, dashed=True, font=13)
bucket = icon("bucket", T_X + 45, T_Y + 55, "Object Storage  rentwise-backup\n비공개 · 저장 시 암호화\nrentwise/seoul/*.json.gz.enc", size=50, lw=180)
enc = icon("encrypt", T_X + 225, T_Y + 57, "AES-256 암호화\nHMAC 위변조 검사\n키: 서울·도쿄 .env", size=46, lw=130)
key = icon("key", T_X + 380, T_Y + 59, "사전 인증 URL\n쓰기 전용 / 조회 전용\n만료 2026-11-30", size=42, lw=140)
iac = icon("iac", T_X + 530, T_Y + 59, "Terraform\ntokyo-dr", size=40, lw=90)

tv_x, tv_y, tv_w, tv_h = T_X + 20, T_Y + 215, T_W - 40, 400
box(tv_x, tv_y, tv_w, tv_h, "VCN rentwise-dr-vcn  ·  10.10.0.0/16  (생성됨)", stroke=ORANGE, font=12, sl=36)
icon("vcn", tv_x + 6, tv_y + 3, "", size=24)
icon("igw", tv_x + tv_w - 22, tv_y + 160, "", size=40)
text(tv_x + tv_w - 60, tv_y + 202, 60, 16, "IGW", font=10, align="center")
box(tv_x + 20, tv_y + 45, tv_w - 60, 335, "퍼블릭 서브넷 10.10.1.0/24  ·  보안 목록: SSH 22 ← 관리자 IP/32 만", stroke=ORANGE, dashed=True, font=11, bold=False, sl=34)
icon("subnet", tv_x + 26, tv_y + 48, "", size=22)
dr_x, dr_y, dr_w = tv_x + 40, tv_y + 90, tv_w - 100
box(dr_x, dr_y, dr_w, 205, "rentwise-dr  (Terraform 정의 · 용량 확보 시 기동)\nA1.Flex 2 OCPU / 12GB · Oracle Linux 9 aarch64 · cloud-init(Docker·git)",
    stroke=GREEN, dashed=True, fill="#FAFAF9", font=11)
icon("flexvm", dr_x + dr_w - 52, dr_y + 8, "", size=40, opacity=60)
dct = icon("container", dr_x + 70, dr_y + 85, "cloudflared · web · api\n서울과 같은 GHCR 이미지", size=42, opacity=60, lw=170)
ddb = icon("db", dr_x + 300, dr_y + 85, "Oracle Free\n단일 서버 모드", size=44, opacity=60, lw=120)
text(tv_x + 40, tv_y + 305, tv_w - 100, 60, "한계: 도쿄 Always Free A1 'Out of host capacity' 반복 → 상시 기동 보류\n전환: terraform apply → deploy-image.sh SHA → restore.sh latest", font=10, color="#6F6964")
edge(dct, ddb, "", dashed=True, color=GRAY)

edge(bk, bucket, "매시간 HTTPS PUT · 암호화 파일 · 쓰기 전용 URL (서울에 OCI 계정 키 없음)", color=ORANGE, sw=2,
     exit=(1, 0.5), entry=(0, 0.5), pts=((582, a_y + 247), (582, 795), (1145, 795), (1145, T_Y + 80)))
edge(bucket, ddb, "restore.sh latest  (조회 전용 URL → HMAC 검사 → 복호화 → 복원)", dashed=True, color=ORANGE,
     exit=(0.5, 1), entry=(0.5, 0), pts=((T_X + 70, T_Y + 190), (dr_x + 322, T_Y + 190)))
text(1168, 160, 260, 30, "dr.rentwise.ccmall.shop\n(장애 시 호스트네임 전환)", font=10, color=GRAY)
edge(cf, dct, "", dashed=True, color=GRAY, exit=(0.5, 0), entry=(0, 0.5),
     pts=((588, 62), (1158, 62), (1158, dr_y + 106)))

# =========================================================================== CI/CD
C_X, C_Y, C_W, C_H = 20, 870, 1110, 210
box(C_X, C_Y, C_W, C_H, "CI/CD — GitHub Flow · PR 검사 → main 병합 시 자동 배포 (GitHub Actions)", stroke=GRAY, font=12)
dev = icon("user", 60, 925, "개발자 A·B·C\n기능 브랜치", size=42, lw=110)
gh = icon("cloud", 220, 925, "GitHub\nrentwise_oci (PR)", size=44, lw=120)
ci = icon("devops", 390, 925, "ci.yml (PR)\npytest · 타입검사·빌드\ncompose · terraform validate", size=46, lw=170)
build = icon("devops", 580, 925, "cd.yml (main 병합)\nCI 재사용 → ARM64 네이티브 빌드\nubuntu-24.04-arm", size=46, lw=180)
ghcr = icon("registry", 770, 925, "GHCR\nrentwise-{api,web}\n:커밋 SHA · :latest", size=46, lw=150)
ssh = icon("key", 950, 925, "SSH 배포 (전용 키·호스트 키 고정)\n임시 토큰으로 pull 후 로그아웃\n준비 확인 · 실패 시 롤백", size=42, lw=190)
edge(dev, gh, "push · PR")
edge(gh, ci, "검사")
edge(ci, build, "병합")
edge(build, ghcr, "push")
edge(ghcr, ssh, "")
edge(ssh, dep, "git checkout SHA → deploy-image.sh SHA", exit=(0.5, 0), entry=(0, 0.5),
     pts=((971, 850), (242, 850), (242, a_y + 247)))

# =========================================================================== 관측 흐름
O_X, O_Y, O_W, O_H = 1170, 870, 610, 210
box(O_X, O_Y, O_W, O_H, "관측(Observability) 흐름 — team-4-2 (배포 예정)", stroke=GRAY, font=12)
o1 = icon("container", O_X + 40, O_Y + 75, "컨테이너 · 호스트\n(4-1, 4-2)", size=40, lw=110)
o2 = icon("container", O_X + 175, O_Y + 75, "Alloy\n수집기", size=40, lw=80)
o3 = icon("monitoring", O_X + 315, O_Y + 40, "Prometheus", size=36, lw=90)
o4 = icon("logging", O_X + 315, O_Y + 125, "Loki", size=36, lw=60)
o5 = icon("analytics", O_X + 445, O_Y + 75, "Grafana", size=40, lw=80)
o6 = icon("alarm", O_X + 550, O_Y + 78, "알림(다음)", size=34, opacity=60, lw=80)
edge(o1, o2, "수집")
edge(o2, o3, "메트릭")
edge(o2, o4, "로그")
edge(o3, o5, "")
edge(o4, o5, "")
edge(o5, o6, "", dashed=True, color=GRAY)

xml = ('<mxfile host="app.diagrams.net" type="device"><diagram id="rentwise-oci" name="rentwise OCI">'
       '<mxGraphModel dx="1800" dy="1100" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
       'fold="1" page="1" pageScale="1" pageWidth="1800" pageHeight="1100" math="0" shadow="0"><root>'
       '<mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>")
OUT.write_text(xml, encoding="utf-8")
print(f"wrote {OUT} ({len(xml)//1024} KB, {len(cells)} cells)")
