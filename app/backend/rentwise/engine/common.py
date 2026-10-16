"""Shared deterministic time/reference checks. No implicit defaults or I/O."""

from datetime import timedelta

from rentwise.contracts.v2.schema import ContractError, check_contract, timestamp

TABLES = ("locations", "customers", "items", "assets", "rentals", "reservations",
          "employees", "shifts", "jobs", "plan_items", "dependencies")
FROZEN = {"IN_PROGRESS", "COMPLETED", "FAILED"}


def interval(start, end):
    return timestamp(start), timestamp(end) if end is not None else None


def overlaps(a, b):
    return (b[1] is None or a[0] < b[1]) and (a[1] is None or b[0] < a[1])


def duration(start, end):
    return (timestamp(end) - timestamp(start)).total_seconds() / 60


def index_rows(data, tables=TABLES):
    result, errors = {}, []
    for table in tables:
        rows = data[table]
        result[table] = {r["id"]: r for r in rows}
        if len(result[table]) != len(rows):
            errors.append(table + ".duplicate_id")
    if errors:
        raise ContractError(errors)
    return result


def check_references(data):
    """Schema first, then referential and basic temporal integrity."""
    check_contract("Snapshot", data, "snapshot")
    ix = index_rows(data)
    errors = []

    def fk(table, value, path):
        if value is not None and value not in ix[table]:
            errors.append(path)

    def span(a, b, path, allow_empty=False):
        if b is not None and (timestamp(b) < timestamp(a) or (not allow_empty and timestamp(a) == timestamp(b))):
            errors.append(path)

    span(data["horizon_start"], data["horizon_end"], "snapshot.horizon")
    for row in data["customers"]:
        fk("locations", row["location_id"], "customers.location_id")
        fk("employees", row["preferred_employee_id"], "customers.preferred_employee_id")
        for w in row["visit_windows"]:
            span(w["start"], w["end"], "customers.visit_windows")
    for row in data["assets"]:
        fk("items", row["item_id"], "assets.item_id")
        fk("locations", row["location_id"], "assets.location_id")
        fk("employees", row["custody_employee_id"], "assets.custody_employee_id")
        if (row["physical_state"] == "IN_TRANSIT") != (row["location_id"] is None):
            errors.append("assets.location_id")
        if row["physical_state"] == "IN_TRANSIT" and row["custody_employee_id"] is None:
            errors.append("assets.custody_employee_id")
    for row in data["rentals"]:
        fk("assets", row["asset_id"], "rentals.asset_id")
        fk("customers", row["customer_id"], "rentals.customer_id")
        if row["actual_start"] and row["actual_end"]:
            span(row["actual_start"], row["actual_end"], "rentals.actual_end", True)
        if row["status"] == "ACTIVE" and (row["actual_start"] is None or row["actual_end"] is not None):
            errors.append("rentals.actual_start/actual_end")
    for row in data["reservations"]:
        fk("assets", row["asset_id"], "reservations.asset_id")
        fk("rentals", row["rental_id"], "reservations.rental_id")
        fk("jobs", row["release_job_id"], "reservations.release_job_id")
        span(row["start_at"], row["end_at"], "reservations.interval")
    for row in data["shifts"]:
        fk("employees", row["employee_id"], "shifts.employee_id")
        fk("locations", row["start_location_id"], "shifts.start_location_id")
        fk("locations", row["end_location_id"], "shifts.end_location_id")
        span(row["start_at"], row["end_at"], "shifts.interval")
        for w in row["break_windows"]:
            span(w["start"], w["end"], "shifts.break_windows")
            if timestamp(w["start"]) < timestamp(row["start_at"]) or timestamp(w["end"]) > timestamp(row["end_at"]):
                errors.append("shifts.break_windows")
    for row in data["jobs"]:
        fk("items", row["item_id"], "jobs.item_id")
        fk("locations", row["from_id"], "jobs.from_id")
        fk("locations", row["to_id"], "jobs.to_id")
        for asset in row["asset_ids"]:
            fk("assets", asset, "jobs.asset_ids")
        span(row["window_start"], row["window_end"], "jobs.window", row["kind"] == "PREP")
        if row["kind"] == "TRANSFER":
            if row["destination_window_start"] is None or row["destination_window_end"] is None:
                errors.append("jobs.destination_window")
            else:
                span(row["destination_window_start"], row["destination_window_end"], "jobs.destination_window")
        elif row["destination_window_start"] is not None or row["destination_window_end"] is not None or row["direct_transfer_confirmed"]:
            errors.append("jobs.transfer_fields")
    for row in data["plan_items"]:
        fk("jobs", row["job_id"], "plan_items.job_id")
        fk("employees", row["employee_id"], "plan_items.employee_id")
        for asset in row["asset_ids"]:
            fk("assets", asset, "plan_items.asset_ids")
        span(row["start_at"], row["end_at"], "plan_items.interval", True)
        for s in row["segments_json"]:
            fk("locations", s["from_id"], "segments.from_id")
            fk("locations", s["to_id"], "segments.to_id")
            span(s["start_at"], s["end_at"], "segments.interval", True)
    for row in data["dependencies"]:
        fk("jobs", row["predecessor_job_id"], "dependencies.predecessor_job_id")
        fk("jobs", row["successor_job_id"], "dependencies.successor_job_id")
    locations = ix["locations"]
    travel = {}
    for r in data["travel_times"]:
        pair = r["from_id"], r["to_id"]
        if pair in travel or pair[0] not in locations or pair[1] not in locations or r["version"] != data["travel_version"]:
            errors.append("travel_times.pair/version")
        if pair[0] == pair[1] and r["minutes"] != 0:
            errors.append("travel_times.diagonal")
        travel[pair] = r["minutes"]
    if set(travel) != {(a, b) for a in locations for b in locations}:
        errors.append("travel_times.complete_directed_matrix")
    if len([r for r in locations.values() if r["kind"] == "WAREHOUSE"]) != 1:
        errors.append("locations.single_warehouse")
    if errors:
        raise ContractError(errors)
    return ix, travel


def route_fits(start, end, from_id, to_id, shift, travel):
    """Implicit relocation arrives just before the next block, outside breaks.

    Earlier travel plus waiting must be recorded as part of that job's block;
    otherwise hidden pre-break repositioning could bypass the employee calendar.
    """
    minutes = travel[from_id, to_id]
    if minutes == 0:
        return start <= end
    departure = end - timedelta(minutes=minutes)
    return departure >= start and not any(overlaps((departure, end), interval(w["start"], w["end"])) for w in shift["break_windows"])
