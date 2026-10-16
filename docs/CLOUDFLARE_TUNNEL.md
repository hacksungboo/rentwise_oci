# Cloudflare 터널 — rentwise.ccmall.shop

`ccmall.shop` 이 이미 Cloudflare 에 등록되어 있다는 전제입니다. 터널은 서버가 Cloudflare 로 **나가는** 연결만 쓰므로 OCI 보안 목록을 건드리지 않아도 됩니다.

## 1. 터널 만들기

1. https://one.dash.cloudflare.com → 계정 선택 → **Networks → Tunnels → Create a tunnel**
2. 유형 **Cloudflared**, 이름 `rentwise-seoul`
3. 설치 화면의 명령어 안에 있는 **`eyJ...` 로 시작하는 토큰만 복사**해서 `infra/.env` 의 `CLOUDFLARE_TUNNEL_TOKEN` 에 넣습니다. (토큰은 비밀번호와 같습니다. 채팅·깃허브에 붙이지 마세요)

## 2. 퍼블릭 호스트네임

| 항목 | 값 |
|---|---|
| Subdomain | `rentwise` |
| Domain | `ccmall.shop` |
| Path | (비움) |
| Service Type | `HTTP` |
| URL | `web:80` |

저장하면 DNS 에 `rentwise.ccmall.shop` CNAME 이 자동으로 생깁니다.

> URL 이 `localhost:80` 이 아니라 `web:80` 인 이유: cloudflared 가 Compose 네트워크 안의 컨테이너라 서비스 이름으로 찾습니다.

## 3. 확인

```bash
cd ~/rentwise_oci/infra
docker compose logs cloudflared | grep -i "Registered tunnel connection"   # 여러 줄 보이면 정상
curl -I https://rentwise.ccmall.shop/healthz
```

## 4. 권장 설정

- **SSL/TLS → Edge Certificates → Always Use HTTPS** 켜기 (세션 쿠키가 HTTPS 전용)
- 기존 Verifi 터널(`verifi.ccmall.shop`)과는 별개 터널로 만듭니다.
