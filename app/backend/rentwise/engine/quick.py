"""Reserved, per-delivery planning resources. No provider booking or payment."""
import hashlib

PREFIX = 'QK-'


def resource_id(job_id: str) -> str:
    return PREFIX + hashlib.sha256(job_id.encode()).hexdigest()[:24]


def is_quick(employee_id: str | None) -> bool:
    return bool(employee_id and employee_id.startswith(PREFIX))


def allowed(employee_id: str | None, kind: str, job_id: str) -> bool:
    return not is_quick(employee_id) or (kind == 'DELIVERY' and employee_id == resource_id(job_id))
