# DB 서버 분리 (team-4-1 앱 / team-4-2 DB)

```
team-4-1 (10.0.0.198)                       team-4-2 (10.0.0.218)
 cloudflared → web → api ──사설망 TCP 1521──▶ Oracle Free (host 네트워크)
                                              firewalld: 1521 은 10.0.0.198 에서만 허용
```

- 앱과 DB가 메모리·디스크를 나눠 쓰지 않고, DB 장애와 앱 배포가 서로 영향을 덜 줍니다.
- CD 는 앱 서버(api·web)만 교체합니다. DB 서버는 배포 때 건드리지 않습니다.
- DB 를 Docker 포트 게시(-p) 대신 **host 네트워크**로 띄웁니다. Docker 포트 게시는 firewalld 규칙을 우회하기 때문입니다.

## 이전 절차 (약 15분, 첫 Oracle 기동 3~5분 포함)

> 순서: **PR 병합(CD 배포) → 4-2 에 DB 기동 → 4-1 연결 전환**. PR 만 병합해서는 아무것도 바뀌지 않습니다(4-1 은 계속 로컬 DB 사용).

### 1. team-4-2: DB 기동

```bash
ssh opc@131.186.25.47 -i team-4-2.key
git clone https://github.com/hacksungboo/rentwise_oci.git ~/rentwise_oci 2>/dev/null || git -C ~/rentwise_oci pull
cd ~/rentwise_oci/infra/db-server
cp .env.example .env && vi .env        # ORACLE_PASSWORD, DB_PASSWORD 는 team-4-1 infra/.env 와 똑같이
./firewall.sh                           # 1521 을 10.0.0.198 에서만 허용
docker compose up -d
docker compose logs -f db               # "DATABASE IS READY TO USE!" 확인 후 Ctrl+C
```

### 2. team-4-1: 연결 확인 후 전환

```bash
ssh opc@146.56.139.138 -i team-4-1.key
timeout 3 bash -c "</dev/tcp/10.0.0.218/1521" && echo "연결 OK"   # 실패하면 3번 문제 해결

cd ~/rentwise_oci/infra
grep -q '^DB_HOST=' .env && sed -i 's/^DB_HOST=.*/DB_HOST=10.0.0.218/' .env || echo 'DB_HOST=10.0.0.218' >> .env
sed -i '/^COMPOSE_PROFILES=/d' .env
docker compose up -d api               # 새 DB 주소로 api 재생성 → 빈 DB 에 seed 자동 적재
./scripts/check.sh                     # 1-1. DB 서버 연결 ✓ 확인
SMOKE_PASSWORD='<admin 비밀번호>' ./scripts/smoke.sh

docker stop rentwise-db                # 기존 로컬 DB 중지 (볼륨은 남겨 두어 되돌리기용)
```

화면의 실행 환경 패널에서 **DB 호스트**가 4-2 로 바뀐 것을 확인할 수 있습니다.

### 되돌리기 (단일 서버로)

```bash
cd ~/rentwise_oci/infra
sed -i 's/^DB_HOST=.*/DB_HOST=db/' .env && echo 'COMPOSE_PROFILES=localdb' >> .env
docker compose up -d                   # 로컬 db 다시 기동, api 재연결
```

## 3. 문제 해결

| 증상 | 확인 |
|---|---|
| 4-1 에서 `연결 OK` 가 안 나옴 | 4-2 에서 `sudo firewall-cmd --list-rich-rules` 에 10.0.0.198 / 1521 규칙이 있는지, `ss -ltn \| grep 1521` 로 DB 가 떠 있는지, OCI 보안 목록의 1521 원본이 10.0.0.0/24 를 포함하는지 |
| api 로그 `ORA-01017` | 두 서버 `.env` 의 `DB_PASSWORD` 가 다름 |
| api 로그 `DB 대기 중` 이 계속 | 4-2 DB 가 아직 기동 중. `docker compose logs db` |
| 화면 데이터가 처음 상태 | 정상. 새 DB 라서 seed 가 다시 들어갔습니다 (기존 데이터는 4-1 볼륨에 남아 있음) |

## 백업

DB 서버에서: `cd ~/rentwise_oci/infra/db-server && ./backup.sh`
(`infra/scripts/backup.sh` 는 단일 서버 모드용입니다)
