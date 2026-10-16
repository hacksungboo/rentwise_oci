"""B-side normalization boundary; requires already reviewed, explicit values.

This helper neither interprets language nor grants approval. The caller must
resolve IDs, copy only unmentioned values from existing jobs, and issue stable
new IDs before calling. An explicit null is retained, never treated as omitted.
"""

from copy import deepcopy

from .schema import ContractError, check_contract, timestamp
from .types import JSONRecord, NormalizedOperation


def normalize_operation(snapshot: JSONRecord, operation: str, target_job_id: str | None,
                        fields: JSONRecord, *, confirmed: bool, rental_id: str | None,
                        return_policy: str, prep_job: JSONRecord | None = None) -> NormalizedOperation:
    check_contract("Snapshot", snapshot, "snapshot")
    jobs = {j["id"]: j for j in snapshot["jobs"]}
    if operation == "RESCHEDULE":
        if target_job_id not in jobs:
            raise ContractError(["operation.target_job_id"])
        job = deepcopy(jobs[target_job_id])
        job.update(deepcopy(fields))
        if job["id"] != target_job_id or job["kind"] != jobs[target_job_id]["kind"]:
            raise ContractError(["operation.job.id", "operation.job.kind"])
    elif operation == "CREATE" and target_job_id is None:
        job = deepcopy(fields)
        if job.get("id") in jobs:
            raise ContractError(["operation.job.id"])
    else:
        raise ContractError(["operation.operation", "operation.target_job_id"])
    job["operation"] = operation
    result = dict(schema_version="rental.operation.v2", operation=operation,
                  target_job_id=target_job_id, job=job, prep_job=deepcopy(prep_job),
                  rental_id=rental_id, return_policy=return_policy, confirmed=confirmed)
    check_contract("NormalizedOperation", result, "operation")
    for value in (job, prep_job):
        if value is None:
            continue
        assets = {a["id"]: a for a in snapshot["assets"]}
        if value["item_id"] not in {i["id"] for i in snapshot["items"]} or any(value[k] not in {loc["id"] for loc in snapshot["locations"]} for k in ("from_id", "to_id")):
            raise ContractError(["operation.job.item_id/from_id/to_id"])
        selected = value["asset_ids"]
        if ((selected or value["kind"] != "DELIVERY") and len(set(selected)) != value["quantity"]
                or any(a not in assets or assets[a]["item_id"] != value["item_id"] for a in selected)):
            raise ContractError(["operation.job.asset_ids/quantity"])
    if timestamp(job["window_end"]) <= timestamp(job["window_start"]):
        raise ContractError(["operation.job.window_end"])
    if job["kind"] == "TRANSFER":
        if (job["destination_window_start"] is None or job["destination_window_end"] is None
                or timestamp(job["destination_window_end"]) <= timestamp(job["destination_window_start"])
                or not job["direct_transfer_confirmed"]):
            raise ContractError(["operation.job.destination_window", "operation.job.direct_transfer_confirmed"])
    elif (job["destination_window_start"] is not None or job["destination_window_end"] is not None
          or job["direct_transfer_confirmed"]):
        raise ContractError(["operation.job.transfer_fields"])
    if job["kind"] in ("DELIVERY", "TRANSFER"):
        expected = "OPEN_ENDED" if job["rental_end_at"] is None else "FIXED"
        if return_policy != expected or rental_id is None:
            raise ContractError(["operation.return_policy", "operation.rental_id"])
    elif return_policy != "NOT_APPLICABLE":
        raise ContractError(["operation.return_policy"])
    if prep_job is not None and (prep_job["kind"] != "PREP" or prep_job["id"] == job["id"]):
        raise ContractError(["operation.prep_job"])
    return result
