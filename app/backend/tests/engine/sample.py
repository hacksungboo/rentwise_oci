"""Small synthetic A-only test data, not C's official seed or independent gold."""

from copy import deepcopy

from rentwise.contracts.v2.types import BUNDLE_VERSION


def t(clock):
    return f"2026-10-16T{clock}:00+09:00"


def job(jid, kind, assets, source, destination, a="09:00", b="18:00", due="17:00"):
    return dict(id=jid, request_id=None, kind=kind, operation="CREATE", asset_ids=assets,
                item_id="PR-A", quantity=len(assets), from_id=source, to_id=destination,
                window_start=t(a), window_end=t(b), due_at=t(due), rental_end_at=None,
                priority="NORMAL", status="ASSIGNED", revision=1,
                destination_window_start=None, destination_window_end=None,
                direct_transfer_confirmed=False)


def segment(kind, source, destination, a, b):
    return dict(kind=kind, from_id=source, to_id=destination, start_at=t(a), end_at=t(b))


def plan(jid, employee, assets, segments):
    return dict(id="PI-" + jid, plan_id="PL-007", job_id=jid, employee_id=employee,
                asset_ids=assets, start_at=segments[0]["start_at"], end_at=segments[-1]["end_at"],
                segments_json=segments, reason_codes=[])


def rental(rid, aid, customer, active=False):
    return dict(id=rid, asset_id=aid, customer_id=customer,
                actual_start="2026-10-15T12:00:00+09:00" if active else None,
                actual_end=None, expected_return_at=None, status="ACTIVE" if active else "PLANNED")


def reservation(rid, aid, rental_id, start, end, release=None):
    return dict(id=rid, asset_id=aid, rental_id=rental_id, start_at=start, end_at=end,
                release_job_id=release, plan_id="PL-007", status="ACTIVE", review_required=False)


def snapshot():
    locations = [dict(id=lid, name=lid, kind="WAREHOUSE" if lid == "W" else "CUSTOMER",
                      address="synthetic", lat=37.5, lon=127.0) for lid in ("W", "H", "S")]
    customers = [dict(id="C-" + lid, name=lid, location_id=lid, preferred_employee_id="E1",
                      visit_windows=[dict(start=t("09:00"), end=t("18:00"))]) for lid in ("H", "S")]
    employees = [dict(id=e, name=e, active=True, skills=[dict(task_kind=k, item_category="PRINTER") for k in ("DELIVERY", "PICKUP", "AS", "TRANSFER")]) for e in ("E1", "E2")]
    shifts = [dict(id="SH-" + e, employee_id=e, start_at=t("09:00"), end_at=t("18:00"),
                   start_location_id="W", end_location_id="W",
                   break_windows=[dict(start=t(a), end=t(b))]) for e, a, b in (("E1", "13:00", "14:00"), ("E2", "12:30", "13:30"))]
    jobs = [job("PICK", "PICKUP", ["P01"], "H", "W", "10:00", "10:10"),
            job("PREP", "PREP", ["P01"], "W", "W"),
            job("DEL", "DELIVERY", ["P01"], "W", "S", "12:00", "12:15", "12:15")]
    plans = [plan("PICK", "E1", ["P01"], [segment("TRAVEL", "W", "H", "09:40", "10:00"), segment("SERVICE", "H", "H", "10:00", "10:10"), segment("TRAVEL", "H", "W", "10:10", "10:30")]),
             plan("PREP", None, ["P01"], [segment("PREP", "W", "W", "10:30", "11:00")]),
             plan("DEL", "E1", ["P01"], [segment("TRAVEL", "W", "S", "11:40", "12:00"), segment("SERVICE", "S", "S", "12:00", "12:15"), segment("TRAVEL", "S", "W", "12:15", "12:35")])]
    assets = [dict(id=aid, item_id="PR-A", physical_state=state, location_id=loc,
                   custody_employee_id=None, last_event_at="2026-10-15T12:00:00+09:00", revision=1)
              for aid, state, loc in (("P01", "AT_CUSTOMER", "H"), ("P02", "READY_WAREHOUSE", "W"))]
    return dict(schema_version="rental.snapshot.v2", bundle_version=BUNDLE_VERSION,
                state_revision=7, as_of=t("09:00"), dataset_version="a-test-only-v1",
                policy_version="policy-v2", travel_version="travel-test-v1",
                horizon_start=t("00:00"), horizon_end="2026-10-23T00:00:00+09:00",
                locations=locations, customers=customers, employees=employees, shifts=shifts,
                items=[dict(id="PR-A", category="PRINTER", model="DEMO-A", prep_minutes=30,
                            service_minutes_by_kind=dict(DELIVERY=15, PICKUP=10, AS=30, TRANSFER=10),
                            transfer_service_minutes=dict(pickup=10, delivery=15), direct_transfer_allowed=True)],
                assets=assets, rentals=[rental("R-H", "P01", "C-H", True), rental("R-S", "P01", "C-S")],
                reservations=[reservation("RS-H", "P01", "R-H", "2026-10-15T11:00:00+09:00", t("11:00"), "PREP"), reservation("RS-S", "P01", "R-S", t("11:40"), None)],
                jobs=jobs, plan_items=plans,
                dependencies=[dict(id="D1", predecessor_job_id="PICK", successor_job_id="PREP", minimum_gap_minutes=0, reason="RETURN_PREP"), dict(id="D2", predecessor_job_id="PREP", successor_job_id="DEL", minimum_gap_minutes=0, reason="READY_DELIVERY")],
                travel_times=[dict(from_id=a, to_id=b, minutes=0 if a == b else 20, source="synthetic", version="travel-test-v1") for a in ("W", "H", "S") for b in ("W", "H", "S")])


def candidate(s):
    result = {k: deepcopy(s[k]) for k in ("jobs", "plan_items", "reservations", "rentals", "dependencies")}
    result.update(schema_version="rental.candidate.v2", bundle_version=BUNDLE_VERSION,
                  base_state_revision=s["state_revision"], plan_id="PL-NEW", approved_job_ids=[])
    result["reservations"] = [r for r in result["reservations"] if r["status"] == "ACTIVE"]
    for p in result["plan_items"]:
        p["plan_id"] = result["plan_id"]
    return result


def delayed(s):
    c = candidate(s)
    c["approved_job_ids"] = ["PICK"]
    c["jobs"][0].update(window_start=t("14:00"), window_end=t("14:10"), operation="RESCHEDULE")
    c["jobs"][2]["asset_ids"] = ["P02"]
    c["plan_items"][0] = plan("PICK", "E2", ["P01"], [segment("TRAVEL", "W", "H", "13:40", "14:00"), segment("SERVICE", "H", "H", "14:00", "14:10"), segment("TRAVEL", "H", "W", "14:10", "14:30")])
    c["plan_items"][1] = plan("PREP", None, ["P01"], [segment("PREP", "W", "W", "14:30", "15:00")])
    c["plan_items"][2]["asset_ids"] = ["P02"]
    for p in c["plan_items"]:
        p["plan_id"] = c["plan_id"]
    c["reservations"][0]["end_at"] = t("15:00")
    c["reservations"][1]["asset_id"] = "P02"
    c["rentals"][1]["asset_id"] = "P02"
    c["dependencies"] = c["dependencies"][:1]
    return c


def transfer_case():
    s = snapshot()
    s.update(jobs=[], plan_items=[], dependencies=[], rentals=s["rentals"][:1], reservations=s["reservations"][:1])
    s["reservations"][0].update(end_at=None, release_job_id=None)
    c = candidate(s)
    j = job("TRANSFER", "TRANSFER", ["P01"], "H", "S", "10:00", "10:10", "10:45")
    j.update(destination_window_start=t("10:30"), destination_window_end=t("10:45"), direct_transfer_confirmed=True)
    c["jobs"] = [j]
    c["approved_job_ids"] = [j["id"]]
    p = plan(j["id"], "E1", ["P01"], [segment("TRAVEL", "W", "H", "09:40", "10:00"), segment("SERVICE", "H", "H", "10:00", "10:10"), segment("TRAVEL", "H", "S", "10:10", "10:30"), segment("SERVICE", "S", "S", "10:30", "10:45")])
    p["plan_id"] = c["plan_id"]
    c["plan_items"] = [p]
    c["rentals"].append(rental("R-T", "P01", "C-S"))
    c["reservations"][0].update(end_at=t("10:10"), release_job_id=j["id"])
    c["reservations"].append(reservation("RS-T", "P01", "R-T", t("10:10"), None))
    return s, c


def availability_input(s, start="09:00", end="18:00"):
    return dict(schema_version="rental.availability-input.v2", bundle_version=BUNDLE_VERSION,
                snapshot=s, from_at=t(start), to_at=t(end), base_state_revision=s["state_revision"])
