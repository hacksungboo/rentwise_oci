"""Independent full-candidate validator. It never repairs or saves a plan."""

from collections import defaultdict
from datetime import timedelta

from rentwise.contracts.v2.schema import ContractError, check_contract, timestamp
from rentwise.contracts.v2.types import CandidatePlan, JSONRecord, ValidationResult

from . import execution
from .common import FROZEN, check_references, duration, interval, overlaps, route_fits


def validate(snapshot: JSONRecord, complete_candidate_plan: CandidatePlan) -> ValidationResult:
    result = dict(schema_version="rental.validation.v1", status="VALID", violations=[], missing_fields=[])
    try:
        base, _ = check_references(snapshot)
        check_contract("CandidatePlan", complete_candidate_plan, "candidate")
        candidate = complete_candidate_plan
        # The effective view replaces these arrays; physical assets remain from B's snapshot.
        effective = {**snapshot, **{k: candidate[k] for k in ("jobs", "plan_items", "reservations", "rentals", "dependencies")}}
        ix, travel = check_references(effective)
    except ContractError as exc:
        result.update(status="DATA_MISSING", missing_fields=exc.paths)
        return result

    violations = result["violations"]

    def fail(code, *, jobs=(), assets=(), employees=(), span=None, expected=None, actual=None):
        violations.append(dict(code=code, job_ids=list(jobs), asset_ids=list(assets),
                               employee_ids=list(employees), interval=span, expected=expected, actual=actual))

    for code, jid, eid in execution.violations(snapshot, candidate["plan_items"], snapshot["as_of"], segments="segments_json"):
        fail(code, jobs=[jid], employees=[eid] if eid else [])

    if candidate["base_state_revision"] != snapshot["state_revision"]:
        fail("STALE_SNAPSHOT", expected=snapshot["state_revision"], actual=candidate["base_state_revision"])
    approved = set(candidate["approved_job_ids"])
    if not approved <= ix["jobs"].keys():
        fail("UNKNOWN_APPROVAL")
    for j in candidate["jobs"]:
        if j["id"] not in base["jobs"] and j["kind"] != "PREP" and j["id"] not in approved:
            fail("CUSTOMER_APPROVAL_REQUIRED", jobs=[j["id"]])
        if j["id"] not in base["jobs"] and j["status"] not in ("UNASSIGNED", "ASSIGNED"):
            fail("EXECUTION_STATE_CHANGED", jobs=[j["id"]])
    by_job = defaultdict(list)
    for p in candidate["plan_items"]:
        by_job[p["job_id"]].append(p)
        if p["plan_id"] != candidate["plan_id"]:
            fail("PLAN_ID_MISMATCH", jobs=[p["job_id"]])
    old_plans = {p["job_id"]: p for p in snapshot["plan_items"]}
    for job_id, old in base["jobs"].items():
        new = ix["jobs"].get(job_id)
        if new is None:
            fail("EXISTING_JOB_MISSING", jobs=[job_id])
            continue
        changed = any(old[k] != new[k] for k in ("kind", "item_id", "quantity", "from_id", "to_id", "window_start", "window_end", "due_at", "rental_end_at", "destination_window_start", "destination_window_end", "direct_transfer_confirmed"))
        if changed and job_id not in approved:
            fail("CUSTOMER_APPROVAL_REQUIRED", jobs=[job_id])
        if old["status"] != new["status"]:
            fail("EXECUTION_STATE_CHANGED", jobs=[job_id])
        if old["status"] in FROZEN:
            old_plan = old_plans.get(job_id)
            new_plan = by_job[job_id][0] if len(by_job[job_id]) == 1 else None
            fixed_keys = ("employee_id", "asset_ids", "start_at", "end_at", "segments_json")
            if old != new or (old_plan is not None and (new_plan is None or any(old_plan[k] != new_plan[k] for k in fixed_keys))):
                fail("FIXED_JOB_CHANGED", jobs=[job_id])
    for job_id, old_p in old_plans.items():
        new_ps = by_job[job_id]
        if job_id in base["jobs"] and base["jobs"][job_id]["status"] not in FROZEN and len(new_ps) == 1:
            old_services = [(timestamp(s["start_at"]), timestamp(s["end_at"])) for s in old_p["segments_json"] if s["kind"] == "SERVICE"]
            new_services = [(timestamp(s["start_at"]), timestamp(s["end_at"])) for s in new_ps[0]["segments_json"] if s["kind"] == "SERVICE"]
            if old_services != new_services and job_id not in approved:
                fail("CUSTOMER_APPROVAL_REQUIRED", jobs=[job_id])
    for rid, old in base["rentals"].items():
        new = ix["rentals"].get(rid)
        if new is None or any(old[k] != new[k] for k in ("actual_start", "actual_end", "status")):
            fail("RENTAL_ACTUAL_CHANGED")
        elif old["status"] != "PLANNED" and any(old[k] != new[k] for k in ("asset_id", "customer_id")):
            fail("RENTAL_CUSTODY_CHANGED", assets=[old["asset_id"]])
    for rid, new in ix["rentals"].items():
        if rid not in base["rentals"] and (new["status"] != "PLANNED" or new["actual_start"] is not None or new["actual_end"] is not None):
            fail("RENTAL_ACTUAL_CHANGED")

    from . import quick
    services = {}
    warehouse = next(loc["id"] for loc in snapshot["locations"] if loc["kind"] == "WAREHOUSE")
    customers_at = {c["location_id"]: c for c in snapshot["customers"]}

    def visit_ok(service, start, end, location, job_id):
        a, b = interval(service["start_at"], service["end_at"])
        if not (timestamp(start) <= a and b <= timestamp(end)):
            fail("VISIT_WINDOW", jobs=[job_id], span=[service["start_at"], service["end_at"]])
        c = customers_at.get(location)
        if c is None or not any(timestamp(w["start"]) <= a and b <= timestamp(w["end"]) for w in c["visit_windows"]):
            fail("CUSTOMER_VISIT_WINDOW", jobs=[job_id])

    for j in candidate["jobs"]:
        jid, kind = j["id"], j["kind"]
        ps = by_job[jid]
        if j["status"] == "CANCELLED":
            if ps:
                fail("CANCELLED_JOB_SCHEDULED", jobs=[jid])
            continue
        if len(ps) != 1:
            fail("INCOMPLETE_PLAN", jobs=[jid], expected=1, actual=len(ps))
            continue
        p = ps[0]
        if not quick.allowed(p["employee_id"], kind, jid):
            fail("QUICK_RESOURCE_SCOPE", jobs=[jid])
        if len(set(p["asset_ids"])) != j["quantity"] or sorted(p["asset_ids"]) != sorted(j["asset_ids"]):
            fail("ASSET_QUANTITY", jobs=[jid], assets=p["asset_ids"])
        if any(ix["assets"][a]["item_id"] != j["item_id"] for a in p["asset_ids"]):
            fail("ASSET_ITEM_MISMATCH", jobs=[jid], assets=p["asset_ids"])
        segments = p["segments_json"]
        if not segments or p["start_at"] != segments[0]["start_at"] or p["end_at"] != segments[-1]["end_at"]:
            fail("SEGMENT_BOUNDS", jobs=[jid])
            continue
        for previous, current in zip(segments, segments[1:]):
            if timestamp(current["start_at"]) < timestamp(previous["end_at"]) or previous["to_id"] != current["from_id"]:
                fail("SEGMENT_CONTINUITY", jobs=[jid])
        for s in segments:
            if s["kind"] == "TRAVEL":
                if duration(s["start_at"], s["end_at"]) < travel[s["from_id"], s["to_id"]]:
                    fail("TRAVEL_TOO_SHORT", jobs=[jid])
            elif s["from_id"] != s["to_id"]:
                fail("SERVICE_LOCATION", jobs=[jid])
        item = ix["items"][j["item_id"]]
        if kind == "PREP":
            if p["employee_id"] is not None or len(segments) != 1 or segments[0]["kind"] != "PREP" or j["from_id"] != warehouse or j["to_id"] != warehouse or segments[0]["from_id"] != warehouse:
                fail("PREP_STRUCTURE", jobs=[jid])
            if duration(p["start_at"], p["end_at"]) < item["prep_minutes"]:
                fail("PREPARATION_TOO_SHORT", jobs=[jid])
            if timestamp(p["start_at"]) < timestamp(j["window_start"]) or timestamp(p["end_at"]) > min(timestamp(j["window_end"]), timestamp(j["due_at"])):
                fail("PREP_WINDOW", jobs=[jid])
            continue
        if ((j["from_id"] not in customers_at and kind != "DELIVERY")
                or (j["to_id"] not in customers_at and kind != "PICKUP")):
            fail("JOB_CUSTOMER_LOCATION", jobs=[jid])
        if p["employee_id"] is None:
            fail("EMPLOYEE_REQUIRED", jobs=[jid])
        else:
            employee = ix["employees"][p["employee_id"]]
            if not employee["active"] or {"task_kind": kind, "item_category": item["category"]} not in employee["skills"]:
                fail("EMPLOYEE_SKILL", jobs=[jid], employees=[employee["id"]])
        sv = [s for s in segments if s["kind"] == "SERVICE"]
        services[jid] = sv
        if any(s["kind"] == "PREP" for s in segments) or len(sv) != (2 if kind == "TRANSFER" else 1):
            fail("SERVICE_STRUCTURE", jobs=[jid])
            continue
        if kind == "TRANSFER":
            if not item["direct_transfer_allowed"] or not j["direct_transfer_confirmed"]:
                fail("DIRECT_TRANSFER_UNCONFIRMED", jobs=[jid])
            expected_locations = [j["from_id"], j["to_id"]]
            required_minutes = [item["transfer_service_minutes"]["pickup"], item["transfer_service_minutes"]["delivery"]]
            visit_ok(sv[1], j["destination_window_start"], j["destination_window_end"], j["to_id"], jid)
        else:
            if (kind == "DELIVERY" and j["from_id"] != warehouse) or (kind == "PICKUP" and j["to_id"] != warehouse) or (kind == "AS" and j["from_id"] != j["to_id"]):
                fail("JOB_ROUTE", jobs=[jid])
            expected_locations = [j["to_id"] if kind == "DELIVERY" else j["from_id"]]
            required_minutes = [item["service_minutes_by_kind"][kind]]
        visit_ok(sv[0], j["window_start"], j["window_end"], expected_locations[0], jid)
        if any(s["from_id"] != loc or duration(s["start_at"], s["end_at"]) < minutes for s, loc, minutes in zip(sv, expected_locations, required_minutes)):
            fail("SERVICE_DURATION_OR_LOCATION", jobs=[jid])
        # Pickup must reach the warehouse before due; delivery/AS/transfer complete at customer.
        completion = p["end_at"] if kind == "PICKUP" else sv[-1]["end_at"]
        if kind == "PICKUP" and segments[-1]["to_id"] != warehouse:
            fail("PICKUP_RETURN_REQUIRED", jobs=[jid])
        if timestamp(completion) > timestamp(j["due_at"]):
            fail("DUE_AT", jobs=[jid])
        if kind in ("DELIVERY", "TRANSFER") and j["rental_end_at"] is not None and timestamp(j["rental_end_at"]) <= timestamp(sv[-1]["end_at"]):
            fail("RENTAL_END_BEFORE_DELIVERY", jobs=[jid])

    # Whole-day employee paths, not only changed job blocks.
    for eid, employee in ix["employees"].items():
        shifts = sorted((s for s in snapshot["shifts"] if s["employee_id"] == eid), key=lambda s: timestamp(s["start_at"]))
        if any(overlaps(interval(a["start_at"], a["end_at"]), interval(b["start_at"], b["end_at"])) for a, b in zip(shifts, shifts[1:])):
            fail("SHIFT_OVERLAP", employees=[eid])
        assigned = sorted((p for p in candidate["plan_items"] if p["employee_id"] == eid), key=lambda p: timestamp(p["start_at"]))
        for a, b in zip(assigned, assigned[1:]):
            if overlaps(interval(a["start_at"], a["end_at"]), interval(b["start_at"], b["end_at"])):
                fail("EMPLOYEE_OVERLAP", jobs=[a["job_id"], b["job_id"]], employees=[eid])
        for p in assigned:
            matching = [s for s in shifts if timestamp(s["start_at"]) <= timestamp(p["start_at"]) and timestamp(p["end_at"]) <= timestamp(s["end_at"])]
            if not matching:
                fail("OUTSIDE_SHIFT", jobs=[p["job_id"]], employees=[eid])
            elif any(overlaps(interval(p["start_at"], p["end_at"]), interval(w["start"], w["end"])) for w in matching[0]["break_windows"]):
                fail("EMPLOYEE_BREAK", jobs=[p["job_id"]], employees=[eid])
        for shift in shifts:
            ps = [p for p in assigned if timestamp(shift["start_at"]) <= timestamp(p["start_at"]) and timestamp(p["end_at"]) <= timestamp(shift["end_at"]) and p["segments_json"]]
            cursor, loc = timestamp(shift["start_at"]), shift["start_location_id"]
            for p in ps:
                if not route_fits(cursor, timestamp(p["start_at"]), loc, p["segments_json"][0]["from_id"], shift, travel):
                    fail("EMPLOYEE_TRAVEL_GAP", jobs=[p["job_id"]], employees=[eid])
                cursor, loc = timestamp(p["end_at"]), p["segments_json"][-1]["to_id"]
            if not route_fits(cursor, timestamp(shift["end_at"]), loc, shift["end_location_id"], shift, travel):
                fail("SHIFT_RETURN", employees=[eid])

    plans = {j: ps[0] for j, ps in by_job.items() if len(ps) == 1}
    graph = defaultdict(list)
    for d in candidate["dependencies"]:
        a, b = d["predecessor_job_id"], d["successor_job_id"]
        graph[a].append(b)
        if a not in plans or b not in plans or timestamp(plans[a]["end_at"]) + timedelta(minutes=d["minimum_gap_minutes"]) > timestamp(plans[b]["start_at"]):
            fail("DEPENDENCY_ORDER", jobs=[a, b])
    # Iterative Kahn traversal avoids recursion limits on untrusted graphs.
    indegree = {j: 0 for j in ix["jobs"]}
    for successors in graph.values():
        for j in successors:
            indegree[j] += 1
    stack = [j for j, count in indegree.items() if count == 0]
    visited = 0
    while stack:
        j = stack.pop()
        visited += 1
        for following in graph[j]:
            indegree[following] -= 1
            if indegree[following] == 0:
                stack.append(following)
    if visited != len(indegree):
        fail("DEPENDENCY_CYCLE")

    _check_reservations(snapshot, candidate, ix, plans, services, fail)
    _check_asset_paths(snapshot, candidate, ix, plans, services, warehouse, fail)
    if violations:
        result["status"] = "INVALID"
    return result


def _check_reservations(snapshot, candidate, ix, plans, services, fail):
    def approved_planned_delivery_move(old, replacements):
        rental = next(r for r in snapshot['rentals'] if r['id'] == old['rental_id'])
        if (rental['status'] != 'PLANNED' or rental['actual_start'] is not None or rental['actual_end'] is not None
                or timestamp(old['start_at']) < max(timestamp(snapshot['as_of']), timestamp(snapshot['horizon_start']))):
            return False
        for old_job in snapshot['jobs']:
            jid = old_job['id']
            old_plan = next((p for p in snapshot['plan_items'] if p['job_id'] == jid), None)
            new_job, new_plan = ix['jobs'].get(jid), plans.get(jid)
            if (jid not in candidate['approved_job_ids'] or old_job['kind'] != 'DELIVERY'
                    or old_job['status'] in FROZEN | {'CANCELLED'} or not old_plan or not new_job or not new_plan
                    or old['asset_id'] not in old_job['asset_ids']
                    or timestamp(old_plan['start_at']) != timestamp(old['start_at'])
                    or any(old_job[k] != new_job[k] for k in ('kind', 'from_id', 'to_id', 'item_id', 'quantity'))
                    or ix['customers'][rental['customer_id']]['location_id'] != old_job['to_id']):
                continue
            if any(timestamp(r['start_at']) == timestamp(new_plan['start_at'])
                   and r['asset_id'] in new_job['asset_ids'] for r in replacements):
                return True
        return False

    grouped = defaultdict(list)
    for r in candidate["reservations"]:
        if r["status"] != "ACTIVE":
            fail("RESERVATION_VIEW_NOT_ACTIVE", assets=[r["asset_id"]])
        if r["review_required"]:
            fail("RESERVATION_REVIEW_REQUIRED", assets=[r["asset_id"]])
        rental = ix["rentals"][r["rental_id"]]
        if rental["asset_id"] != r["asset_id"]:
            fail("RESERVATION_RENTAL_ASSET", assets=[r["asset_id"]])
        grouped[r["asset_id"]].append(r)
        release = r["release_job_id"]
        if release is not None:
            j, p = ix["jobs"][release], plans.get(release)
            expected = None
            if p is not None and j["kind"] == "PREP":
                expected = p["end_at"]
            elif p is not None and j["kind"] == "TRANSFER" and len(services.get(release, [])) == 2:
                expected = services[release][0]["end_at"]
            if expected is None or r["asset_id"] not in j["asset_ids"] or r["end_at"] is None or timestamp(r["end_at"]) != timestamp(expected):
                fail("RESERVATION_RELEASE", jobs=[release], assets=[r["asset_id"]])
        elif r["end_at"] is not None:
            fail("RESERVATION_RELEASE_MISSING", assets=[r["asset_id"]])
    for asset, rows in grouped.items():
        rows.sort(key=lambda r: timestamp(r["start_at"]))
        for a, b in zip(rows, rows[1:]):
            if overlaps(interval(a["start_at"], a["end_at"]), interval(b["start_at"], b["end_at"])):
                fail("ASSET_RESERVATION_OVERLAP", assets=[asset])
    for old in snapshot["reservations"]:
        if old["status"] != "ACTIVE":
            continue
        # Historical/period-external occupancy cannot disappear in a new plan.
        replacements = [r for r in candidate["reservations"] if r["rental_id"] == old["rental_id"]]
        if not replacements:
            fail("EXISTING_RESERVATION_MISSING", assets=[old["asset_id"]])
        elif (not any(timestamp(r["start_at"]) <= timestamp(old["start_at"]) for r in replacements)
              and not approved_planned_delivery_move(old, replacements)):
            fail("RESERVATION_START_TRUNCATED", assets=[old["asset_id"]])
        if not overlaps(interval(old["start_at"], old["end_at"]), interval(snapshot["horizon_start"], snapshot["horizon_end"])):
            keys = ("asset_id", "rental_id", "start_at", "end_at", "release_job_id", "review_required")
            if not any(all(r[k] == old[k] for k in keys) for r in replacements):
                fail("OUTSIDE_RESERVATION_CHANGED", assets=[old["asset_id"]])
    for rental in candidate["rentals"]:
        if rental["status"] in ("ACTIVE", "PLANNED") and not any(r["rental_id"] == rental["id"] for r in candidate["reservations"]):
            fail("RENTAL_RESERVATION_MISSING", assets=[rental["asset_id"]])
    for j in candidate["jobs"]:
        p = plans.get(j["id"])
        if p is None or j["status"] in FROZEN or j["status"] == "CANCELLED" or j["kind"] not in ("DELIVERY", "TRANSFER"):
            continue
        sv = services.get(j["id"], [])
        if len(sv) != (2 if j["kind"] == "TRANSFER" else 1):
            continue
        start = sv[0]["end_at"] if j["kind"] == "TRANSFER" else p["start_at"]
        destination = j["to_id"]
        for aid in j["asset_ids"]:
            matches = [r for r in grouped[aid] if timestamp(r["start_at"]) == timestamp(start) and ix["customers"][ix["rentals"][r["rental_id"]]["customer_id"]]["location_id"] == destination]
            if not matches or not any(r["end_at"] is None or (j["rental_end_at"] is not None and timestamp(r["end_at"]) >= timestamp(j["rental_end_at"])) for r in matches):
                fail("DELIVERY_RESERVATION_COVERAGE", jobs=[j["id"]], assets=[aid])


def _check_asset_paths(snapshot, candidate, ix, plans, services, warehouse, fail):
    as_of = timestamp(snapshot["as_of"])
    for aid, asset in ix["assets"].items():
        actions = []
        in_progress = []
        for j in candidate["jobs"]:
            if aid not in j["asset_ids"] or j["status"] in ("CANCELLED", "COMPLETED", "FAILED") or j["id"] not in plans:
                continue
            p = plans[j["id"]]
            if j["status"] == "IN_PROGRESS":
                in_progress.append(j["id"])
                continue
            sv = services.get(j["id"], [])
            if j["kind"] == "PREP":
                start = p["start_at"]
            elif not sv:
                continue
            else:
                start = p["start_at"] if j["kind"] == "DELIVERY" else sv[0]["start_at"]
            actions.append((timestamp(start), j["id"], j, p, sv))
        state, location, free_at = asset["physical_state"], asset["location_id"], as_of
        for start, jid, j, p, sv in sorted(actions):
            if in_progress:
                # Preserve unrelated ongoing work, but do not infer its actual release.
                fail("EXECUTION_IN_PROGRESS", jobs=in_progress + [jid], assets=[aid])
            kind = j["kind"]
            if start < free_at:
                fail("ASSET_NOT_READY_OR_OVERLAP", jobs=[jid], assets=[aid])
            if state in ("REPAIR", "UNAVAILABLE", "RETIRED", "IN_TRANSIT"):
                fail("ASSET_UNAVAILABLE", jobs=[jid], assets=[aid])
            if kind == "PREP":
                if location != warehouse or state != "PREP_REQUIRED":
                    fail("PREP_REQUIRES_RETURN", jobs=[jid], assets=[aid])
                state, location, free_at = "READY_WAREHOUSE", warehouse, timestamp(p["end_at"])
            elif kind == "DELIVERY":
                if state != "READY_WAREHOUSE" or location != j["from_id"] or p["segments_json"][0]["from_id"] != j["from_id"]:
                    fail("DELIVERY_REQUIRES_READY", jobs=[jid], assets=[aid])
                state, location, free_at = "AT_CUSTOMER", j["to_id"], timestamp(sv[-1]["end_at"])
            elif kind in ("PICKUP", "TRANSFER", "AS"):
                if state != "AT_CUSTOMER" or location != j["from_id"]:
                    fail("ASSET_LOCATION", jobs=[jid], assets=[aid])
                if kind == "PICKUP":
                    state, location, free_at = "PREP_REQUIRED", warehouse, timestamp(p["end_at"])
                elif kind == "TRANSFER":
                    state, location, free_at = "AT_CUSTOMER", j["to_id"], timestamp(sv[-1]["end_at"])
                else:
                    free_at = timestamp(sv[0]["end_at"])
