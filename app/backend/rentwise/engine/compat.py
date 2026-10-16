"""B v1 EnginePort with opt-in server confirmation preparation.

Configuration reads B's demo clock and the AI environment at construction.
Planning is pure; interpretation requires a model and a server budget adapter.
"""
from datetime import datetime, timezone
import json
from typing import Callable

from rentwise.contracts import types as c
from rentwise.contracts.v2.schema import ContractError, timestamp
from . import v1, delivery, recovery
from .interpret import OpenAIInterpreter
from .b_review import prepare_review


class RealEngine:
    mode = 'real'
    solver_version = v1.VERSION

    def __init__(self, *, as_of: str | Callable[[], str] | None = None, interpreter=None, budget=None, delivery_enabled=False, recovery_enabled=False):
        self.delivery_enabled = delivery_enabled
        self.recovery_enabled = recovery_enabled
        self.interpreter = interpreter if interpreter is not None else OpenAIInterpreter.from_environment(budget=budget)
        self.as_of = as_of
        self._clock_error = False
        if as_of is None:
            from rentwise.config import settings
            if settings.auto_seed and settings.seed_path.exists():
                try:
                    self.as_of = json.loads(settings.seed_path.read_text(encoding='utf-8'))['manifest']['clock_anchor']
                    timestamp(self.as_of)
                except (OSError, KeyError, TypeError, ValueError):
                    self._clock_error = True
            else:
                self.as_of = lambda: datetime.now(timezone.utc).isoformat()

    def _clock(self):
        if self._clock_error:
            raise ContractError(['engine.clock_anchor'])
        value = self.as_of() if callable(self.as_of) else self.as_of
        timestamp(value)
        return value

    def interpret(self, inp: c.InterpretationInput) -> c.InterpretationResult:
        return prepare_review(inp, self.interpreter.interpret(inp))

    def explain_plan(self, plan):
        from .explain import OpenAIPlanExplainer
        return OpenAIPlanExplainer(client=getattr(self.interpreter, 'client', None), budget=getattr(self.interpreter, 'budget', None),
            model_id=getattr(self.interpreter, 'model_id', 'gpt-5.6-luna')).explain(plan)

    def solve(self, inp: c.SolverInput) -> c.SolverResult:
        try:
            clock = self._clock()
        except (ContractError, TypeError, ValueError):
            return c.SolverResult(status='DATA_MISSING', candidate_items=[], reservation_changes=[],
                affected_job_ids=[], impact_edges=[], violations=[],
                unresolved=[c.Unresolved(job_id=None,code='CLOCK_UNAVAILABLE',details={})],objective=[],
                search_stats=c.SearchStats(elapsed_ms=0,candidates_examined=0,limit_reached=False),
                input_hash=inp.input_hash,solver_version=self.solver_version)
        if self.delivery_enabled and any(op.operation == 'CREATE' for op in inp.operations):
            return delivery.solve(inp, clock)
        if self.recovery_enabled and any(op.kind == 'PICKUP' for op in inp.operations):
            return recovery.solve(inp, clock)
        return v1.solve(inp, clock)

    def prepare_delivery_confirmation(self, snapshot, operations, candidate_items, reservation_changes, *, request_id, input_hash) -> delivery.DeliveryConfirmation:
        """Pure creates for B's existing locked confirmation transaction."""
        if not self.delivery_enabled:
            return delivery.rejected('DELIVERY_NOT_ENABLED')
        try:
            clock = self._clock()
        except (ContractError, TypeError, ValueError):
            return delivery.rejected('CLOCK_UNAVAILABLE', 'DATA_MISSING')
        return delivery.prepare_confirmation(snapshot, operations, candidate_items, reservation_changes,
            request_id=request_id, input_hash=input_hash, as_of=clock)

    def prepare_confirmation(self, snapshot, operations, candidate_items, reservation_changes, *, input_hash):
        """Optional native v1 recovery; existing B v2 pickup path is independent."""
        if not self.recovery_enabled:
            return recovery.ConfirmationChanges(c.ValidationResult(status='INVALID',
                violations=[c.Violation(code='RECOVERY_NOT_ENABLED')], missing_fields=[]))
        try:
            clock = self._clock()
        except (ContractError, TypeError, ValueError):
            return recovery.ConfirmationChanges(c.ValidationResult(status='DATA_MISSING',
                violations=[], missing_fields=['engine.clock_anchor']))
        return recovery.prepare_confirmation(snapshot, operations, candidate_items,
            reservation_changes, input_hash=input_hash, as_of=clock)

    def validate(self, snapshot: dict, complete_candidate_plan: list[c.PlanItem]) -> c.ValidationResult:
        try:
            clock = self._clock()
        except (ContractError, TypeError, ValueError):
            return c.ValidationResult(status='DATA_MISSING', violations=[], missing_fields=['engine.clock_anchor'])
        return v1.validate(snapshot, complete_candidate_plan, as_of=clock)

    def availability(self, inp: c.AvailabilityInput) -> c.AvailabilityResult:
        try:
            clock = self._clock()
        except (ContractError, TypeError, ValueError):
            return c.AvailabilityResult(status='DATA_MISSING',base_state_revision=inp.base_state_revision,
                physical_counts=[],windows=[],missing_fields=['engine.clock_anchor'])
        return v1.availability(inp, clock)
