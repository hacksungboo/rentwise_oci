"""B-like request/ID issuance for A tests only. No real persistence or gold."""

from copy import deepcopy

from rentwise.contracts.v2.normalize import normalize_operation
from rentwise.contracts.v2.serialization import solver_input_hash
from .sample import job, t


def normal_operation(snapshot, *, start="11:00", end="11:15", due="11:15"):
    delivery = job("NEW-DEL", "DELIVERY", [], "W", "H", start, end, due)
    delivery.update(quantity=1, status="UNASSIGNED", request_id="REQ-TEST")
    return normalize_operation(snapshot, "CREATE", None, delivery, confirmed=True,
                               rental_id="R-NEW", return_policy="OPEN_ENDED")


def delay_operation(snapshot, *, start="14:00", end="14:10", due="17:00"):
    pickup = next(j for j in snapshot["jobs"] if j["kind"] == "PICKUP")
    rental = next(r for r in snapshot["rentals"] if r["status"] == "ACTIVE" and r["asset_id"] in pickup["asset_ids"])
    return normalize_operation(snapshot, "RESCHEDULE", pickup["id"],
                               dict(window_start=t(start), window_end=t(end), due_at=t(due)),
                               confirmed=True, rental_id=rental["id"], return_policy="NOT_APPLICABLE")


def solver_input(snapshot, operations, **changes):
    jobs = {j["id"]: j for j in snapshot["jobs"]}
    for op in operations:
        jobs[op["job"]["id"]] = op["job"]
        if op["prep_job"] is not None:
            jobs[op["prep_job"]["id"]] = op["prep_job"]
    rentals = {r["rental_id"] for r in snapshot["reservations"] if r["status"] == "ACTIVE"}
    rentals.update(op["rental_id"] for op in operations if op["operation"] == "CREATE" and op["rental_id"] is not None)
    plan_ids = {p["plan_id"] for p in snapshot["plan_items"]}
    result = dict(schema_version="rental.solver.v2", bundle_version=snapshot["bundle_version"],
                  request_id="REQ-TEST", request_revision=1, interpretation_revision=2,
                  plan_id="PL-REQUEST", base_plan_id=next(iter(plan_ids)) if plan_ids else None,
                  base_state_revision=snapshot["state_revision"],
                  **{k: snapshot[k] for k in ("horizon_start", "horizon_end", "dataset_version", "travel_version", "policy_version")},
                  snapshot=deepcopy(snapshot), operations=deepcopy(operations),
                  approved_job_ids=[op["job"]["id"] for op in operations], overrides=[],
                  id_allocations=dict(plan_items=[dict(job_id=jid, id="NEW-PI-" + jid) for jid in sorted(jobs)],
                                      reservations=[dict(rental_id=rid, id="NEW-RS-" + rid) for rid in sorted(rentals)],
                                      dependencies=[dict(job_id=jid, id="NEW-DEP-" + jid) for jid in sorted(jobs) if jobs[jid]["kind"] == "DELIVERY"]),
                  max_search_ms=2000, max_candidates=1000)
    result.update(changes)
    result["input_hash"] = solver_input_hash(result)
    return result
