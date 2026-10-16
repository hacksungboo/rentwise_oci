"""The unchanged B v1 EnginePort. No extended DTO/context or DB access.

Configuration reads B's demo clock and the AI environment at construction.
Planning is pure; interpretation requires a model and a server budget adapter.
"""
from datetime import datetime, timezone
import json
from typing import Callable

from rentwise.contracts import types as c
from rentwise.contracts.v2.schema import ContractError, timestamp
from . import v1
from .interpret import OpenAIInterpreter
from .b_review import prepare_review


class RealEngine:
    mode = 'real'
    solver_version = v1.VERSION

    def __init__(self, *, as_of: str | Callable[[], str] | None = None, interpreter=None, budget=None):
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

    def solve(self, inp: c.SolverInput) -> c.SolverResult:
        try:
            clock = self._clock()
        except (ContractError, TypeError, ValueError):
            return c.SolverResult(status='DATA_MISSING', candidate_items=[], reservation_changes=[],
                affected_job_ids=[], impact_edges=[], violations=[],
                unresolved=[c.Unresolved(job_id=None,code='CLOCK_UNAVAILABLE',details={})],objective=[],
                search_stats=c.SearchStats(elapsed_ms=0,candidates_examined=0,limit_reached=False),
                input_hash=inp.input_hash,solver_version=self.solver_version)
        return v1.solve(inp, clock)

    def validate(self, snapshot: dict, complete_candidate_plan: list[c.PlanItem]) -> c.ValidationResult:
        return v1.validate(snapshot, complete_candidate_plan)

    def availability(self, inp: c.AvailabilityInput) -> c.AvailabilityResult:
        try:
            clock = self._clock()
        except (ContractError, TypeError, ValueError):
            return c.AvailabilityResult(status='DATA_MISSING',base_state_revision=inp.base_state_revision,
                physical_counts=[],windows=[],missing_fields=['engine.clock_anchor'])
        return v1.availability(inp, clock)
