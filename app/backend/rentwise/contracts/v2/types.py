"""JSON DTOs. Runtime field requirements live in schemas/bundle.json.

Use JSON objects at the API boundary; do not introduce role-specific copies.
EnginePort is the target interface; solve/validate/availability are implemented.
Interpretation and full service integration remain pending.
"""

from typing import Any, Literal, Protocol, TypedDict

BUNDLE_VERSION = "rental.bundle.v2"
JSONRecord = dict[str, Any]


class CandidatePlan(TypedDict):
    schema_version: Literal["rental.candidate.v2"]
    bundle_version: Literal["rental.bundle.v2"]
    base_state_revision: int
    plan_id: str
    approved_job_ids: list[str]
    jobs: list[JSONRecord]
    plan_items: list[JSONRecord]
    reservations: list[JSONRecord]
    rentals: list[JSONRecord]
    dependencies: list[JSONRecord]


class NormalizedOperation(TypedDict):
    schema_version: Literal["rental.operation.v2"]
    operation: Literal["CREATE", "RESCHEDULE"]
    target_job_id: str | None
    job: JSONRecord
    prep_job: JSONRecord | None
    rental_id: str | None
    return_policy: Literal["FIXED", "OPEN_ENDED", "NOT_APPLICABLE"]
    confirmed: bool


class ValidationResult(TypedDict):
    schema_version: Literal["rental.validation.v1"]
    status: Literal["VALID", "INVALID", "DATA_MISSING"]
    violations: list[JSONRecord]
    missing_fields: list[str]


class AvailabilityResult(TypedDict):
    schema_version: Literal["rental.availability.v1"]
    status: Literal["OK", "DATA_MISSING"]
    base_state_revision: int
    physical_counts: list[JSONRecord]
    windows: list[JSONRecord]
    missing_fields: list[str]


class SolverInput(TypedDict):
    schema_version: Literal["rental.solver.v2"]
    bundle_version: Literal["rental.bundle.v2"]
    input_hash: str
    request_id: str
    request_revision: int
    interpretation_revision: int
    plan_id: str
    base_plan_id: str | None
    base_state_revision: int
    horizon_start: str
    horizon_end: str
    dataset_version: str
    travel_version: str
    policy_version: str
    operations: list[NormalizedOperation]
    approved_job_ids: list[str]
    snapshot: JSONRecord
    overrides: list[JSONRecord]
    id_allocations: JSONRecord
    max_search_ms: int
    max_candidates: int


class SolverResult(TypedDict):
    schema_version: Literal["rental.solver-result.v2"]
    status: Literal["FEASIBLE", "NEEDS_REVIEW", "PROVEN_INFEASIBLE", "NO_SOLUTION_FOUND", "DATA_MISSING"]
    candidate_plan: CandidatePlan | None
    candidate_items: list[JSONRecord]
    reservation_changes: list[JSONRecord]
    affected_job_ids: list[str]
    impact_edges: list[JSONRecord]
    violations: list[JSONRecord]
    unresolved: list[JSONRecord]
    objective: list[int]
    search_stats: JSONRecord
    input_hash: str
    solver_version: str


class EnginePort(Protocol):
    def interpret(self, input: JSONRecord) -> JSONRecord: ...
    def solve(self, input: SolverInput) -> SolverResult: ...
    def availability(self, input: JSONRecord) -> AvailabilityResult: ...
    def validate(self, snapshot: JSONRecord, complete_candidate_plan: CandidatePlan) -> ValidationResult: ...
