"""Period availability, keeping physical counts separate from future promises."""

from collections import Counter, defaultdict
from copy import deepcopy

from rentwise.contracts.v2.schema import ContractError, check_contract, timestamp
from rentwise.contracts.v2.types import AvailabilityResult, JSONRecord

from .common import check_references, duration, interval, overlaps
from .validate import validate

STATES = ("READY_WAREHOUSE", "IN_TRANSIT", "AT_CUSTOMER", "PREP_REQUIRED", "REPAIR", "UNAVAILABLE")


def availability(input: JSONRecord) -> AvailabilityResult:
    result = dict(schema_version="rental.availability.v1", status="OK", base_state_revision=0,
                  physical_counts=[], windows=[], missing_fields=[])
    try:
        check_contract("AvailabilityInput", input)
        snapshot = input["snapshot"]
        ix, _ = check_references(snapshot)
        result["base_state_revision"] = input["base_state_revision"]
        start, end = interval(input["from_at"], input["to_at"])
        if start >= end or start < timestamp(snapshot["as_of"]):
            raise ContractError(["input.from_at/to_at"])
        if input["base_state_revision"] != snapshot["state_revision"]:
            raise ContractError(["input.base_state_revision"])
    except ContractError as exc:
        result.update(status="DATA_MISSING", missing_fields=exc.paths)
        return result

    assets_by_item = defaultdict(list)
    counts = Counter()
    for asset in snapshot["assets"]:
        if asset["physical_state"] != "RETIRED":
            assets_by_item[asset["item_id"]].append(asset)
            counts[asset["item_id"], asset["physical_state"]] += 1
    for item in sorted(ix["items"]):
        result["physical_counts"].extend(dict(item_id=item, physical_state=s, count=counts[item, s]) for s in STATES)

    reservations = defaultdict(list)
    cuts = {start, end}
    for r in snapshot["reservations"]:
        if r["status"] != "ACTIVE":
            continue
        reservations[r["asset_id"]].append(r)
        for value in (r["start_at"], r["end_at"]):
            if value is not None and start < timestamp(value) < end:
                cuts.add(timestamp(value))
    for p in snapshot["plan_items"]:
        if ix["jobs"][p["job_id"]]["kind"] == "PREP" and start < timestamp(p["end_at"]) < end:
            cuts.add(timestamp(p["end_at"]))
    boundaries = sorted(cuts)
    plans = {p["job_id"]: p for p in snapshot["plan_items"]}
    # A conditional promise must also pass the independent full-plan validator.
    # Invalid employee routes, malformed preparation, missing coverage, etc. must
    # not appear as a usable conditional asset merely because an end date exists.
    baseline = {k: deepcopy(snapshot[k]) for k in ("jobs", "plan_items", "reservations", "rentals", "dependencies")}
    baseline.update(schema_version="rental.candidate.v2", bundle_version=snapshot["bundle_version"],
                    base_state_revision=snapshot["state_revision"], plan_id="AVAILABILITY-CHECK", approved_job_ids=[])
    baseline["reservations"] = [r for r in baseline["reservations"] if r["status"] == "ACTIVE"]
    for p in baseline["plan_items"]:
        p["plan_id"] = baseline["plan_id"]
    validation = validate(snapshot, baseline)
    blocked = set()
    if validation["status"] == "DATA_MISSING":
        blocked.update(ix["assets"])
    for v in validation["violations"]:
        blocked.update(v["asset_ids"])
        for jid in v["job_ids"]:
            if jid in ix["jobs"]:
                blocked.update(ix["jobs"][jid]["asset_ids"])
        if not v["job_ids"] and not v["asset_ids"]:
            blocked.update(ix["assets"])
    for a, b in zip(boundaries, boundaries[1:]):
        for item_id in sorted(ix["items"]):
            window = dict(item_id=item_id, from_at=a.isoformat(), to_at=b.isoformat(),
                          ready_asset_ids=[], conditional_assets=[], unavailable_asset_ids=[])
            for asset in sorted(assets_by_item[item_id], key=lambda a: a["id"]):
                rows = reservations[asset["id"]]
                occupied = any(overlaps((a, b), interval(r["start_at"], r["end_at"])) for r in rows)
                if asset["id"] in blocked or occupied or any(r["review_required"] for r in rows) or asset["physical_state"] in ("REPAIR", "UNAVAILABLE", "IN_TRANSIT"):
                    window["unavailable_asset_ids"].append(asset["id"])
                    continue
                earlier_returns = [r for r in rows if r["end_at"] is not None and timestamp(snapshot["as_of"]) < timestamp(r["end_at"]) <= a]
                # An initially READY asset may already have left and returned in the future.
                if asset["physical_state"] == "READY_WAREHOUSE" and not earlier_returns and ix["locations"][asset["location_id"]]["kind"] == "WAREHOUSE":
                    window["ready_asset_ids"].append(asset["id"])
                    continue
                estimates = _preparations(asset, snapshot, ix, plans)
                estimates = [e for e in estimates if timestamp(e["expected_ready_at"]) <= a]
                if estimates:
                    latest = max(estimates, key=lambda e: timestamp(e["expected_ready_at"]))
                    if earlier_returns and timestamp(latest["expected_ready_at"]) < max(timestamp(r["end_at"]) for r in earlier_returns):
                        window["unavailable_asset_ids"].append(asset["id"])
                    else:
                        window["conditional_assets"].append(latest)
                else:
                    window["unavailable_asset_ids"].append(asset["id"])
            result["windows"].append(window)
    return result


def _preparations(asset, snapshot, ix, plans):
    """Only explicit, uncompleted PREP with a valid return chain is conditional.

    It is a promise, never a physical READY transition. Execution rechecks in B
    are still mandatory before departure. No fallback from expected_return_at.
    """
    result = []
    warehouse = next(loc["id"] for loc in snapshot["locations"] if loc["kind"] == "WAREHOUSE")
    for job in snapshot["jobs"]:
        if job["kind"] != "PREP" or job["status"] not in ("ASSIGNED", "UNASSIGNED") or asset["id"] not in job["asset_ids"] or job["id"] not in plans:
            continue
        p = plans[job["id"]]
        if p["employee_id"] is not None or len(p["segments_json"]) != 1:
            continue
        segment = p["segments_json"][0]
        if segment["kind"] != "PREP" or segment["from_id"] != warehouse or segment["to_id"] != warehouse or p["start_at"] != segment["start_at"] or p["end_at"] != segment["end_at"]:
            continue
        if timestamp(p["start_at"]) < timestamp(snapshot["as_of"]) or duration(p["start_at"], p["end_at"]) < ix["items"][asset["item_id"]]["prep_minutes"]:
            continue
        dependencies = [job["id"]]
        valid_return = asset["physical_state"] == "PREP_REQUIRED" and asset["location_id"] == warehouse
        for d in snapshot["dependencies"]:
            if d["successor_job_id"] != job["id"]:
                continue
            pickup = ix["jobs"][d["predecessor_job_id"]]
            pp = plans.get(pickup["id"])
            if pickup["kind"] != "PICKUP" or pp is None or asset["id"] not in pickup["asset_ids"] or pickup["to_id"] != warehouse or pickup["status"] != "ASSIGNED":
                continue
            if timestamp(pp["end_at"]) > timestamp(p["start_at"]) or duration(pp["end_at"], p["start_at"]) < d["minimum_gap_minutes"]:
                continue
            returns = [r for r in snapshot["reservations"] if r["status"] == "ACTIVE" and r["asset_id"] == asset["id"] and not r["review_required"] and r["release_job_id"] == job["id"] and r["end_at"] is not None and timestamp(r["end_at"]) == timestamp(p["end_at"])]
            if not returns:
                continue
            valid_return = True
            dependencies.append(pickup["id"])
        if valid_return:
            result.append(dict(asset_id=asset["id"], expected_ready_at=p["end_at"], dependency_job_ids=sorted(dependencies)))
    return result
