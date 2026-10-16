"""앱 데이터 논리 백업/복원 (모든 rw_* 표 → JSON).

DB 종류와 무관(Oracle/SQLite)하고 Data Pump 없이 api 컨테이너 안에서 실행된다.
  python -m rentwise.backup export > backup.json      # 표준출력
  python -m rentwise.backup import < backup.json      # 표준입력, 한 트랜잭션으로 전체 교체
  python -m rentwise.backup summary < backup.json     # 내용 요약만 (DB 변경 없음)
시각은 DB 와 같은 UTC naive 값을 ISO 문자열로, 금액은 문자열로 보존한다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Numeric, delete, insert, select

from rentwise.config import settings
from rentwise.db import tables as T
from rentwise.db.database import get_db_engine, init_schema
from rentwise.timeutil import now

FORMAT = "rentwise.backup.v1"


def _out(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v


def _in(col, v: Any) -> Any:
    if v is None:
        return None
    if isinstance(col.type, DateTime):
        return datetime.fromisoformat(v)
    if isinstance(col.type, Numeric):
        return Decimal(v)
    return v


def export_data(conn) -> dict:
    tables = {}
    for t in T.metadata.sorted_tables:
        rows = conn.execute(select(t)).mappings().all()
        tables[t.name] = [{k: _out(v) for k, v in r.items()} for r in rows]
    ws = tables.get(T.workspace_state.name) or [{}]
    return {"format": FORMAT, "schema_version": T.SCHEMA_VERSION, "created_at": now().isoformat() + "Z",
            "build_sha": settings.build_sha, "state_revision": ws[0].get("state_revision"),
            "current_plan_id": ws[0].get("current_plan_id"), "tables": tables}


def summary(data: dict) -> dict:
    return {k: data.get(k) for k in ("format", "schema_version", "created_at", "build_sha",
                                       "state_revision", "current_plan_id")} | {
        "rows": {k: len(v) for k, v in data["tables"].items() if v}}


def restore_data(conn, data: dict) -> dict:
    if data.get("format") != FORMAT:
        raise SystemExit(f"알 수 없는 백업 형식: {data.get('format')}")
    if data.get("schema_version") not in (1, T.SCHEMA_VERSION):
        raise SystemExit(f"스키마 버전 불일치: 백업 {data.get('schema_version')} / 현재 {T.SCHEMA_VERSION}")
    order = T.metadata.sorted_tables
    for t in reversed(order):
        conn.execute(delete(t))
    counts = {}
    for t in order:
        rows = data["tables"].get(t.name) or []
        if rows:
            cols = {c.name: c for c in t.columns}
            conn.execute(insert(t), [{k: _in(cols[k], v) for k, v in r.items() if k in cols} for r in rows])
        counts[t.name] = len(rows)
    if data.get("schema_version") == 1:
        conn.execute(insert(T.schema_version).values(version=T.SCHEMA_VERSION, applied_at=now(),
                                                       note="v1 backup upgraded: empty request queues"))
    return counts


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "export":
        with get_db_engine().connect() as conn:
            json.dump(export_data(conn), sys.stdout, ensure_ascii=False, separators=(",", ":"))
        return 0
    if cmd in ("import", "summary"):
        data = json.load(sys.stdin)
        if cmd == "summary":
            print(json.dumps(summary(data), ensure_ascii=False, indent=1))
            return 0
        init_schema()
        with get_db_engine().begin() as conn:      # 실패하면 전체 롤백
            counts = restore_data(conn, data)
        print(json.dumps({"restored": summary(data), "rows": {k: v for k, v in counts.items() if v}},
                         ensure_ascii=False, indent=1))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
