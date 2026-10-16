"""S1 운영 현황: 물리 재고 / 날짜별 가용 / 직원 타임라인."""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.engine import Connection

from rentwise.config import settings
from rentwise.contracts.types import AvailabilityInput
from rentwise.db import tables as T
from rentwise.db.database import read_snapshot, row_to_dict
from rentwise.engine_registry import get_engine
from rentwise.timeutil import KST, iso, overlaps, parse


def clock_anchor() -> str:
    try:
        return json.loads(settings.seed_path.read_text(encoding="utf-8"))["manifest"]["clock_anchor"]
    except Exception:  # noqa: BLE001
        return iso(parse("2026-10-16T09:00:00+09:00"))


def operations_view(conn: Connection, date: str | None) -> dict:
    ws = conn.execute(select(T.workspace_state)).one()
    snap = read_snapshot(conn)
    anchor = parse(clock_anchor())
    day = parse(f"{date}T00:00:00+09:00") if date else anchor.astimezone(KST).replace(hour=0, minute=0, second=0)
    d0, d1 = day, day + timedelta(days=1)

    avail = get_engine().availability(AvailabilityInput(
        snapshot=snap, from_at=iso(d0), to_at=iso(d1), base_state_revision=ws.state_revision)).model_dump()

    loc = {l["id"]: l for l in snap["locations"]}
    cust_by_loc = {c["location_id"]: c for c in snap["customers"]}
    jobs = {j["id"]: j for j in snap["jobs"]}
    emp = {e["id"]: e for e in snap["employees"]}

    lanes: dict[str, list] = {e: [] for e in emp}
    lanes["PREP"] = []
    for p in snap["plan_items"]:
        if not overlaps(parse(p["start_at"]), parse(p["end_at"]), d0, d1):
            continue
        j = jobs.get(p["job_id"], {})
        site = j.get("from_id") if j.get("kind") in ("PICKUP", "AS", "TRANSFER") else j.get("to_id")
        card = {
            "job_id": p["job_id"], "kind": j.get("kind"), "asset_ids": p["asset_ids"],
            "start_at": p["start_at"], "end_at": p["end_at"], "segments": p["segments"],
            "site_id": site, "site_name": loc.get(site, {}).get("name"),
            "customer_id": cust_by_loc.get(site, {}).get("id"),
            "window_start": j.get("window_start"), "window_end": j.get("window_end"), "due_at": j.get("due_at"),
            "reason_codes": p.get("reason_codes", []), "status": j.get("status"),
        }
        lanes[p["employee_id"] or "PREP"].append(card)
    breaks = {}
    for s in snap["shifts"]:
        if parse(s["start_at"]) >= d0 and parse(s["start_at"]) < d1:
            breaks[s["employee_id"]] = {"shift": [s["start_at"], s["end_at"]], "breaks": s["break_windows"]}

    totals: dict[str, int] = {}
    for a in snap["assets"]:
        if a["physical_state"] != "RETIRED":
            totals[a["physical_state"]] = totals.get(a["physical_state"], 0) + 1

    # 고객 위치 카드에 표시할 현재 보유 개체
    holdings = {}
    for a in snap["assets"]:
        if a["location_id"]:
            holdings.setdefault(a["location_id"], []).append(a["id"])

    return {
        "workspace": {"state_revision": ws.state_revision, "current_plan_id": ws.current_plan_id,
                      "dataset_version": ws.dataset_version, "clock_anchor": clock_anchor(),
                      "engine_mode": get_engine().mode},
        "date": d0.date().isoformat(),
        "physical_totals": totals,
        "total_assets": sum(totals.values()),
        "availability": avail,
        "items": snap["items"],
        "assets": snap["assets"],
        "employees": [{"id": e["id"], "name": e["name"], "shift": breaks.get(e["id"], {}).get("shift"),
                       "breaks": breaks.get(e["id"], {}).get("breaks", []),
                       "items": sorted(lanes[e["id"]], key=lambda c: c["start_at"])} for e in emp.values()],
        "prep_items": sorted(lanes["PREP"], key=lambda c: c["start_at"]),
        "locations": [{**l, "holdings": holdings.get(l["id"], []),
                       "customer_id": cust_by_loc.get(l["id"], {}).get("id"),
                       "preferred_employee_id": cust_by_loc.get(l["id"], {}).get("preferred_employee_id")}
                      for l in snap["locations"]],
    }


def reference_view(conn: Connection) -> dict:
    snap = read_snapshot(conn)
    return {k: snap[k] for k in ("customers", "items", "assets", "employees", "locations")} | {
        "jobs": [j for j in snap["jobs"] if j["kind"] != "PREP"],
    }


def asset_view(conn: Connection, asset_id: str) -> dict | None:
    snap = read_snapshot(conn)
    a = next((x for x in snap["assets"] if x["id"] == asset_id), None)
    if not a:
        return None
    return {**a,
            "rentals": [r for r in snap["rentals"] if r["asset_id"] == asset_id],
            "reservations": [r for r in snap["reservations"] if r["asset_id"] == asset_id],
            "jobs": [j for j in snap["jobs"] if asset_id in j["asset_ids"]]}


__all__ = ["operations_view", "reference_view", "asset_view", "row_to_dict"]
