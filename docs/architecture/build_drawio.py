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
FONT = "fontFamily=Oracle Sans;"

cells: list[str] = []
_n = [100]


def nid() -> str:
    _n[0] += 1
    return f"c{_n[0]}"


def esc(s: str) -> str:
    s = html.escape(s, quote=True).replace("\n", "&lt;br&gt;")
    return s.replace("&amp;lt;b&amp;gt;", "&lt;b&gt;").replace("&amp;lt;/b&amp;gt;", "&lt;/b&gt;").replace("&lt;b&gt;", "&lt;b&gt;")


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


def region(x, y, w, h, title):
    cid = nid()
    st = ("whiteSpace=wrap;html=1;align=left;spacingLeft=10;spacingTop=2;fontFamily=Oracle Sans;verticalAlign=top;"
          "fillColor=#F5F4F2;rounded=1;arcSize=1;strokeColor=#9E9892;fontColor=#312D2A;fontSize=14;container=0;")
    cells.append(f'<mxCell id="{cid}" value="{esc(title)}" style="{st}" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    return cid


def vcn(x, y, w, h, title, sub=False):
    cid = nid()
    st = (f"whiteSpace=wrap;html=1;strokeWidth={1 if sub else 2};dashed=1;align=left;fontFamily=Oracle Sans;verticalAlign=top;"
          f"fillColor=none;fontColor=#AE562C;strokeColor=#AE562C;fontSize={11 if sub else 12};spacingLeft=5;container=0;")
    cells.append(f'<mxCell id="{cid}" value="{esc(title)}" style="{st}" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    return cid


def ad(x, y, w, h, title):
    cid = nid()
    st = ("whiteSpace=wrap;html=1;strokeWidth=1;align=center;fontFamily=Oracle Sans;verticalAlign=top;rounded=1;arcSize=1;"
          "fillColor=#DFDCD8;strokeColor=#9E9892;fontColor=#312D2A;fontSize=12;container=0;")
    cells.append(f'<mxCell id="{cid}" value="{esc(title)}" style="{st}" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    return cid


def node(x, y, w, h, title, dashed=False):
    cid = nid()
    st = (f"whiteSpace=wrap;html=1;rounded=1;arcSize=2;fillColor=#FCFBFA;strokeColor=#9E9892;dashed={1 if dashed else 0};"
          f"align=left;verticalAlign=top;spacingLeft=8;spacingTop=2;fontFamily=Oracle Sans;fontSize=12;fontColor=#312D2A;container=0;")
    cells.append(f'<mxCell id="{cid}" value="{esc(title)}" style="{st}" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    return cid


def lane(x, y, w, h, title):
    cid = nid()
    st = "whiteSpace=wrap;html=1;fillColor=none;strokeColor=#000000;align=left;verticalAlign=top;spacingLeft=6;fontSize=12;container=0;"
    cells.append(f'<mxCell id="{cid}" value="{esc(title)}" style="{st}" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
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



G = "#7A736E"   # 보조 글씨
O = "#AE562C"   # OCI 주황 (백업 경로)

# ---------------------------------------------------------------- 외부
users = icon("users", 70, 22, "Users", size=40, font=10)
cf = icon("internet", 330, 18, "Cloudflare", size=46, font=10)
oai = icon("genai", 990, 20, "OpenAI API", size=42, font=10)
edge(users, cf, "HTTPS Request", font=10)

# ---------------------------------------------------------------- 서울
region(20, 110, 1130, 700, "<b>OCI Region</b> - Seoul (ap-seoul-1)")
vcn(50, 150, 1070, 640, "<b>VCN</b>  10.0.0.x")
icon("vcn", 1080, 140, "", size=26)
igw = icon("igw", 335, 130, "", size=38)
text(215, 122, 115, 20, "Internet Gateway", font=10, align="right")
ad(80, 190, 1010, 580, "<b>Availability Domain 1</b> (AP-SEOUL-1-AD-1)")
vcn(100, 225, 970, 525, "<b>Subnet</b>  10.0.0.0/24", sub=True)

app_node = node(125, 265, 440, 460, "<b>team-4-1</b>  10.0.0.198\n<font color='#7A736E'>App Server · A1.Flex 4 OCPU / 22GB</font>")
tun = icon("container", 160, 345, "Cloudflared", size=42, font=10)
web = icon("container", 300, 345, "Web (nginx)", size=42, font=10)
api = icon("container", 440, 345, "API (FastAPI)", size=42, font=10)
alloy1 = icon("container", 160, 560, "Alloy", size=42, font=10)
bk = icon("backup", 440, 560, "Backup (hourly)", size=42, font=10)
edge(tun, web, "")
edge(web, api, "")

node(600, 265, 445, 460, "<b>team-4-2</b>  10.0.0.218\n<font color='#7A736E'>DB &amp; Monitoring · A1.Flex 4 OCPU / 22GB</font>")
db = icon("db", 640, 345, "Oracle AI DB 26ai", size=44, font=10)
fw = icon("firewall", 900, 349, "firewalld", size=36, font=10)
vcn(625, 470, 395, 230, "Monitoring", sub=True)
alloy2 = icon("container", 650, 565, "Alloy", size=38, font=10)
prom = icon("monitoring", 790, 510, "Prometheus", size=36, font=10)
loki = icon("logging", 790, 620, "Loki", size=36, font=10)
graf = icon("analytics", 935, 565, "Grafana", size=38, font=10)
edge(alloy2, prom, "")
edge(alloy2, loki, "")
edge(prom, graf, "")
edge(loki, graf, "")

edge(cf, igw, "Cloudflare Tunnel", font=10)
edge(igw, tun, "", exit=(0.5, 1), entry=(0.5, 0), pts=((354, 325), (181, 325)))
edge(api, db, "1521 (private)", font=10)
edge(api, oai, "HTTPS", font=10, exit=(0.5, 0), entry=(0.5, 1), pts=((461, 250), (1011, 250)))
edge(alloy1, alloy2, "Logs & Metrics", font=10, exit=(0.5, 1), entry=(0.5, 1),
     pts=((181, 690), (669, 690)))

# ---------------------------------------------------------------- 도쿄
region(1190, 110, 590, 700, "<b>OCI Region</b> - Tokyo (ap-tokyo-1)")
text(1200, 132, 400, 20, "Always Free tenancy · DR", font=10, color=G)
bucket = icon("bucket", 1250, 190, "Object Storage\n(encrypted backup)", size=46, font=10, lw=130)
tf = icon("iac", 1640, 192, "Terraform", size=40, font=10)
vcn(1215, 320, 540, 380, "<b>VCN</b>  10.10.0.0/16")
icon("vcn", 1715, 310, "", size=26)
vcn(1240, 360, 490, 315, "<b>Public Subnet</b>  10.10.1.0/24", sub=True)
node(1265, 400, 440, 250, "<b>DR Standby</b>\n<font color='#7A736E'>A1.Flex · defined in Terraform</font>", dashed=True)
dapp = icon("container", 1320, 500, "App", size=42, font=10, opacity=55)
ddb = icon("db", 1560, 498, "Oracle DB", size=44, font=10, opacity=55)
edge(dapp, ddb, "", dashed=True, color=G)

edge(bk, bucket, "Hourly Backup (AES-256)", font=10, color=O, sw=2, exit=(0.5, 1), entry=(0, 0.5),
     pts=((461, 760), (1165, 760), (1165, 213)))
edge(bucket, ddb, "Restore", font=10, dashed=True, color=O, exit=(0.5, 1), entry=(0.5, 0),
     pts=((1273, 290), (1582, 290)))
edge(cf, dapp, "Failover", font=10, dashed=True, color=G, exit=(0.5, 0), entry=(0, 0.5),
     pts=((353, 8), (1172, 8), (1172, 521)))

# ---------------------------------------------------------------- CI/CD
lane(20, 860, 1130, 160, "CI/CD")
dev = icon("user", 70, 920, "Developer", size=38, font=10)
gh = icon("cloud", 250, 920, "GitHub", size=40, font=10)
act = icon("devops", 450, 918, "GitHub Actions", size=42, font=10)
ghcr = icon("registry", 660, 920, "GHCR", size=40, font=10)
dep = icon("key", 870, 920, "SSH Deploy", size=38, font=10)
edge(dev, gh, "Push / PR", font=10)
edge(gh, act, "Test · Merge", font=10)
edge(act, ghcr, "Build ARM64", font=10)
edge(ghcr, dep, "Pull", font=10)
edge(dep, app_node, "Deploy · Auto Rollback", font=10, exit=(0.5, 0), entry=(0.75, 1),
     pts=((889, 830), (455, 830)))

# ---------------------------------------------------------------- Observability
lane(1190, 860, 590, 160, "Observability")
o1 = icon("container", 1230, 920, "Containers", size=38, font=10)
o2 = icon("container", 1360, 920, "Alloy", size=38, font=10)
o3 = icon("monitoring", 1490, 885, "Prometheus", size=34, font=10)
o4 = icon("logging", 1490, 960, "Loki", size=34, font=10)
o5 = icon("analytics", 1620, 920, "Grafana", size=38, font=10)
o6 = icon("alarm", 1720, 922, "Alert", size=32, font=10, opacity=60)
edge(o1, o2, "Collect", font=10)
edge(o2, o3, "Metrics", font=10)
edge(o2, o4, "Logs", font=10)
edge(o3, o5, "")
edge(o4, o5, "")
edge(o5, o6, "", dashed=True, color=G)

text(20, 1030, 600, 18, "Solid: running   ·   Dashed: DR (standby)   ·   Icons: OCI Architecture Diagram Toolkit", font=10, color=G)

xml = ('<mxfile host="app.diagrams.net" type="device"><diagram id="rentwise-oci" name="rentwise OCI">'
       '<mxGraphModel dx="1800" dy="1100" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
       'fold="1" page="1" pageScale="1" pageWidth="1800" pageHeight="1100" math="0" shadow="0"><root>'
       '<mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>")
OUT.write_text(xml, encoding="utf-8")
print(f"wrote {OUT} ({len(xml)//1024} KB, {len(cells)} cells)")
