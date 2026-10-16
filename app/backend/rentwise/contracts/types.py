"""공용 계약 v1 — A·B·C가 함께 import 하는 타입.

기준: 노션 '일반 렌탈 운영 플랫폼 — MVP 실행 명세' §4~7, '공통 개발 계약' §4~5.
소유: B (변경 시 A·C 확인 → VERSION/CHANGELOG 갱신).
도메인 payload(intent, solver)는 명세의 JSON Schema와 같은 필드명을 쓴다. camelCase 변환 금지.
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

BUNDLE_VERSION = "rental.bundle.v1"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- 공통
class DomainError(Strict):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


TaskKind = Literal["DELIVERY", "PICKUP", "AS", "TRANSFER"]
JobKind = Literal["DELIVERY", "PICKUP", "AS", "TRANSFER", "PREP"]


# --------------------------------------------------------------------------- 해석 (명세 §5)
class Evidence(Strict):
    path: str
    quote: str


class Operation(Strict):
    operation: Literal["CREATE", "RESCHEDULE"]
    kind: TaskKind
    target_job_id: Optional[str]
    item_id: Optional[str]
    asset_ids: list[str]
    quantity: Optional[int] = Field(default=None, ge=1, le=12)
    source_customer_id: Optional[str]
    destination_customer_id: Optional[str]
    window_start: Optional[str]
    window_end: Optional[str]
    due_at: Optional[str]
    rental_end_at: Optional[str]
    priority_hint: Literal["NORMAL", "URGENT", "UNKNOWN"]
    evidence: list[Evidence]


class NeedsConfirmation(Strict):
    path: str
    reason: Literal["MISSING", "AMBIGUOUS", "OUT_OF_RANGE", "UNSUPPORTED"]
    question: str


class Intent(Strict):
    """rental.intent.v1"""
    schema_version: Literal["rental.intent.v1"] = "rental.intent.v1"
    operations: list[Operation] = Field(max_length=4)
    needs_confirmation: list[NeedsConfirmation]


class CandidateRef(Strict):
    id: str
    name: str


class InterpretationInput(Strict):
    request_id: str
    request_revision: int
    received_at: str
    timezone: str = "Asia/Seoul"
    text: str = Field(max_length=2000)
    source_customer_id: Optional[str]
    candidate_customers: list[CandidateRef]
    candidate_items: list[CandidateRef]
    existing_jobs: list[dict[str, Any]] = Field(default_factory=list, max_length=15)
    schema_version: str = "rental.intent.v1"
    prompt_version: str = "dev"


class Usage(Strict):
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: Optional[int]


class CallMetadata(Strict):
    origin: Literal["AI", "MOCK"]
    model_id: Optional[str]
    prompt_version: str
    provider_call_id: Optional[str]
    attempts: int
    usage: Optional[Usage]
    latency_ms: int


class InterpretationResult(Strict):
    schema_version: Literal["rental.interpretation-result.v1"] = "rental.interpretation-result.v1"
    status: Literal["OK", "ERROR"]
    payload: Optional[Intent]
    error: Optional[DomainError]
    call: CallMetadata


# --------------------------------------------------------------------------- 배정 (명세 §6)
class Segment(Strict):
    kind: Literal["TRAVEL", "SERVICE", "PREP"]
    from_id: str
    to_id: str
    start_at: str
    end_at: str


class PlanItem(Strict):
    id: Optional[str] = None
    plan_id: Optional[str] = None
    job_id: str
    employee_id: Optional[str]
    asset_ids: list[str]
    start_at: str
    end_at: str
    segments: list[Segment]
    reason_codes: list[str] = Field(default_factory=list)


class ReservationChange(Strict):
    action: Literal["REPLACE", "CREATE", "CANCEL"]
    old_id: Optional[str]
    reservation: Optional[dict[str, Any]]


class Violation(Strict):
    code: str
    job_ids: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    employee_ids: list[str] = Field(default_factory=list)
    interval: Optional[dict[str, Any]] = None
    expected: Optional[Any] = None
    actual: Optional[Any] = None


class ImpactEdge(Strict):
    from_job_id: str
    to_job_id: str
    reason: str
    old_time: Optional[str]
    new_time: Optional[str]


class Unresolved(Strict):
    job_id: Optional[str]
    code: str
    details: dict[str, Any] = Field(default_factory=dict)


class SearchStats(Strict):
    elapsed_ms: int
    candidates_examined: int
    limit_reached: bool


class NormalizedOperation(BaseModel):
    """사람 확인·기존 조건 상속이 끝난 배정 입력 (AI 원본 아님)."""
    model_config = ConfigDict(extra="allow")
    kind: TaskKind
    operation: Literal["CREATE", "RESCHEDULE"]
    target_job_id: Optional[str] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    due_at: Optional[str] = None


class SolverInput(Strict):
    schema_version: Literal["rental.solver.v1"] = "rental.solver.v1"
    bundle_version: str = BUNDLE_VERSION
    request_id: str
    interpretation_revision: int
    base_plan_id: Optional[str]
    base_state_revision: int
    horizon_start: str
    horizon_end: str
    dataset_version: str
    travel_version: str
    policy_version: str
    operations: list[NormalizedOperation]
    snapshot: dict[str, list[dict[str, Any]]]
    overrides: list[dict[str, Any]] = Field(default_factory=list)
    max_search_ms: int = 2000
    max_candidates: int = 1000
    input_hash: str


SolverStatus = Literal["FEASIBLE", "NEEDS_REVIEW", "PROVEN_INFEASIBLE", "NO_SOLUTION_FOUND", "DATA_MISSING"]


class SolverResult(Strict):
    status: SolverStatus
    candidate_items: list[PlanItem]
    reservation_changes: list[ReservationChange]
    affected_job_ids: list[str]
    impact_edges: list[ImpactEdge]
    violations: list[Violation]
    unresolved: list[Unresolved]
    objective: list[int]
    search_stats: SearchStats
    input_hash: str
    solver_version: str


class ValidationResult(Strict):
    schema_version: Literal["rental.validation.v1"] = "rental.validation.v1"
    status: Literal["VALID", "INVALID", "DATA_MISSING"]
    violations: list[Violation]
    missing_fields: list[str]


# --------------------------------------------------------------------------- 가용성 (공통 계약 §5)
class AvailabilityInput(Strict):
    bundle_version: str = BUNDLE_VERSION
    snapshot: dict[str, list[dict[str, Any]]]
    from_at: str
    to_at: str
    base_state_revision: int


class PhysicalCount(Strict):
    item_id: str
    physical_state: str
    count: int


class ConditionalAsset(Strict):
    asset_id: str
    expected_ready_at: Optional[str]
    dependency_job_ids: list[str]


class AvailabilityWindow(Strict):
    item_id: str
    from_at: str
    to_at: str
    ready_asset_ids: list[str]
    conditional_assets: list[ConditionalAsset]
    unavailable_asset_ids: list[str]


class AvailabilityResult(Strict):
    schema_version: Literal["rental.availability.v1"] = "rental.availability.v1"
    status: Literal["OK", "DATA_MISSING"]
    base_state_revision: int
    physical_counts: list[PhysicalCount]
    windows: list[AvailabilityWindow]
    missing_fields: list[str]


# --------------------------------------------------------------------------- 함수 계약
class EnginePort(Protocol):
    """B의 API가 호출하는 단일 주입 지점. A가 실제 구현, B가 dev_fakes에 mock 구현."""

    mode: str  # "mock" | "real"

    def interpret(self, inp: InterpretationInput) -> InterpretationResult: ...

    def availability(self, inp: AvailabilityInput) -> AvailabilityResult: ...

    def solve(self, inp: SolverInput) -> SolverResult: ...

    def validate(self, snapshot: dict[str, list[dict[str, Any]]],
                 complete_candidate_plan: list[PlanItem]) -> ValidationResult: ...
