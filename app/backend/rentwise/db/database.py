from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy import create_engine, delete, insert, select, text
from sqlalchemy.engine import Connection, Engine

from rentwise.config import settings
from rentwise.db import tables as T
from rentwise.timeutil import iso, now, to_db

log = logging.getLogger("rentwise.db")
_engine: Engine | None = None


def get_db_engine() -> Engine:
    global _engine
    if _engine is None:
        url = settings.database_url
        kw: dict[str, Any] = {"pool_pre_ping": True, "future": True}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False}
        else:
            kw.update(pool_size=4, max_overflow=0)
        _engine = create_engine(url, **kw)
    return _engine


def reset_engine_for_tests(url: str) -> Engine:
    global _engine
    _engine = None
    object.__setattr__(settings, "database_url", url)
    return get_db_engine()


def is_oracle(conn: Connection) -> bool:
    return conn.dialect.name == "oracle"


def wait_for_db(timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with get_db_engine().connect() as c:
                c.execute(text("SELECT 1 FROM dual" if c.dialect.name == "oracle" else "SELECT 1"))
            return
        except Exception as e:  # noqa: BLE001
            if time.monotonic() > deadline:
                raise
            log.warning("DB 대기 중: %s", str(e)[:120])
            time.sleep(5)


def init_schema() -> None:
    eng = get_db_engine()
    T.metadata.create_all(eng)
    with eng.begin() as c:
        if c.execute(select(T.schema_version.c.version)).first() is None:
            c.execute(insert(T.schema_version).values(version=T.SCHEMA_VERSION, applied_at=now(), note="initial"))


# --------------------------------------------------------------------------- seed
J = lambda v: json.dumps(v, ensure_ascii=False)  # noqa: E731

SEED_ORDER = [  # FK 순서. 삭제는 역순
    T.locations, T.customers, T.items, T.assets, T.rentals, T.reservations, T.employees, T.shifts,
    T.travel_times, T.jobs, T.dependencies, T.plans, T.plan_items,
]
RUNTIME_TABLES = [T.audit_log, T.idempotency, T.interpretations, T.requests]


def load_seed(conn: Connection, seed: dict[str, Any]) -> None:
    """DEMO workspace를 seed로 초기화한다 (명시적 reset 전용)."""
    for t in RUNTIME_TABLES + list(reversed(SEED_ORDER)) + [T.workspace_state]:
        conn.execute(delete(t))
    ws = seed["workspace"]
    rows = {
        T.locations: seed["locations"],
        T.customers: [{**c, "visit_windows_json": J(c["visit_windows"])} for c in seed["customers"]],
        T.items: [{"id": i["id"], "category": i["category"], "model_name": i["model_name"],
                   "service_minutes_json": J(i["service_minutes_by_kind"]), "prep_minutes": i["prep_minutes"],
                   "direct_transfer_allowed": i["direct_transfer_allowed"]} for i in seed["items"]],
        T.assets: [{**a, "last_event_at": to_db(a["last_event_at"])} for a in seed["assets"]],
        T.rentals: [{**r, **{k: to_db(r[k]) for k in ("actual_start", "actual_end", "expected_return_at")}}
                    for r in seed["rentals"]],
        T.reservations: [{**r, "start_at": to_db(r["start_at"]), "end_at": to_db(r["end_at"])}
                         for r in seed["reservations"]],
        T.employees: [{"id": e["id"], "name": e["name"], "skills_json": J(e["skills"]), "active": e["active"]}
                      for e in seed["employees"]],
        T.shifts: [{**{k: v for k, v in s.items() if k != "break_windows"},
                    "start_at": to_db(s["start_at"]), "end_at": to_db(s["end_at"]),
                    "break_windows_json": J(s["break_windows"])} for s in seed["shifts"]],
        T.travel_times: seed["travel_times"],
        T.jobs: [{**{k: v for k, v in j.items() if k != "asset_ids"}, "asset_ids_json": J(j["asset_ids"]),
                  **{k: to_db(j[k]) for k in ("window_start", "window_end", "due_at", "rental_end_at")}}
                 for j in seed["jobs"]],
        T.dependencies: seed["dependencies"],
        T.plans: [{**seed["plan"], "created_at": to_db(seed["plan"]["created_at"]),
                   "confirmed_at": to_db(seed["plan"]["confirmed_at"]), "engine_mode": "seed",
                   "solver_status": "FEASIBLE"}],
        T.plan_items: [_plan_item_row(p) for p in seed["plan_items"]],
    }
    for t in SEED_ORDER:
        if rows[t]:
            cols = set(t.c.keys())
            conn.execute(insert(t), [{k: v for k, v in r.items() if k in cols} for r in rows[t]])
    conn.execute(insert(T.workspace_state).values(
        id=ws["id"], state_revision=ws["state_revision"], current_plan_id=ws["current_plan_id"],
        dataset_version=ws["dataset_version"]))


def _plan_item_row(p: dict[str, Any]) -> dict[str, Any]:
    return {"id": p["id"], "plan_id": p["plan_id"], "job_id": p["job_id"], "employee_id": p["employee_id"],
            "asset_ids_json": J(p["asset_ids"]), "start_at": to_db(p["start_at"]), "end_at": to_db(p["end_at"]),
            "segments_json": J([dict(s) for s in p["segments"]]), "reason_codes_json": J(p.get("reason_codes", []))}


def ensure_seeded() -> bool:
    with get_db_engine().begin() as c:
        if c.execute(select(T.workspace_state.c.id)).first() is not None:
            return False
        seed = json.loads(settings.seed_path.read_text(encoding="utf-8"))
        load_seed(c, seed)
        return True


# --------------------------------------------------------------------------- 조회 → 계약 dict
def _ts(d):
    return iso(d) if d is not None else None


def row_to_dict(table, row) -> dict[str, Any]:
    d = dict(row._mapping)
    for k, v in list(d.items()):
        col = table.c[k]
        if isinstance(col.type, T.DateTime):
            d[k] = _ts(v)
    return d


def read_snapshot(conn: Connection, plan_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """명세 §4 snapshot 배열. plan_items 는 지정 계획(기본: 현행 계획)의 행."""
    ws = conn.execute(select(T.workspace_state)).one()
    plan_id = plan_id or ws.current_plan_id

    def all_rows(t, order=None):
        q = select(t)
        if order is not None:
            q = q.order_by(order)
        return [row_to_dict(t, r) for r in conn.execute(q)]

    customers = []
    for c in all_rows(T.customers, T.customers.c.id):
        c["visit_windows"] = json.loads(c.pop("visit_windows_json"))
        customers.append(c)
    items = []
    for i in all_rows(T.items, T.items.c.id):
        i["service_minutes_by_kind"] = json.loads(i.pop("service_minutes_json"))
        items.append(i)
    employees = []
    for e in all_rows(T.employees, T.employees.c.id):
        e["skills"] = json.loads(e.pop("skills_json"))
        employees.append(e)
    shifts = []
    for s in all_rows(T.shifts, T.shifts.c.id):
        s["break_windows"] = json.loads(s.pop("break_windows_json"))
        shifts.append(s)
    jobs = []
    for j in all_rows(T.jobs, T.jobs.c.id):
        j["asset_ids"] = json.loads(j.pop("asset_ids_json"))
        jobs.append(j)
    pis = []
    q = select(T.plan_items).where(T.plan_items.c.plan_id == plan_id).order_by(T.plan_items.c.start_at)
    for r in conn.execute(q):
        pis.append(plan_item_from_row(r))
    return {
        "locations": all_rows(T.locations, T.locations.c.id),
        "customers": customers,
        "items": items,
        "assets": all_rows(T.assets, T.assets.c.id),
        "rentals": all_rows(T.rentals, T.rentals.c.id),
        "reservations": all_rows(T.reservations, T.reservations.c.id),
        "employees": employees,
        "shifts": shifts,
        "jobs": jobs,
        "plan_items": pis,
        "dependencies": all_rows(T.dependencies, T.dependencies.c.id),
        "travel_times": all_rows(T.travel_times),
    }


def plan_item_from_row(r) -> dict[str, Any]:
    d = row_to_dict(T.plan_items, r)
    d["asset_ids"] = json.loads(d.pop("asset_ids_json"))
    d["segments"] = json.loads(d.pop("segments_json"))
    d["reason_codes"] = json.loads(d.pop("reason_codes_json"))
    return d
