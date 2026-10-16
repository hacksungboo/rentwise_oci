# 로컬 개발

Oracle 없이 SQLite 로 바로 띄울 수 있습니다. (운영은 Oracle. SQLite 성공을 클라우드 완료로 보지 않습니다)

## 백엔드

```bash
cd app/backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                                   # 메인 시연 동선 테스트
uvicorn rentwise.main:app --reload --port 8000
# http://localhost:8000/api/docs
```

- DB 파일: `app/backend/rentwise-dev.db` (지우면 다음 기동 때 seed 다시 적재)
- 계정: `admin / rentwise2026` (로컬 기본값. 서버는 `.env` 의 `DEMO_ACCOUNTS`)

## 프론트엔드

```bash
cd app/frontend
npm install
npm run dev          # http://localhost:5173 (/api 는 :8000 으로 프록시)
npm run typecheck && npm run build
```

## seed 다시 만들기 (임시 개발 seed)

```bash
python3 app/fixtures/dev/build_dev_seed.py
```
