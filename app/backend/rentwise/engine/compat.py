"""The unchanged B v1 EnginePort. No extended DTO/context or DB access.

Configuration reads only B's existing demo clock setting at construction.
Planning functions receive snapshots and return B's existing Pydantic models.
"""
from datetime import datetime, timezone
import json
from typing import Callable

from rentwise.contracts import types as c
from rentwise.contracts.v2.schema import ContractError, timestamp
from . import v1


class RealEngine:
    mode = 'real'
    solver_version = v1.VERSION

    def __init__(self, *, as_of: str | Callable[[], str] | None = None, interpreter=None):
        self.interpreter = interpreter
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
        if self.interpreter is not None:
            return self.interpreter.interpret(inp)
        return c.InterpretationResult(status='ERROR', payload=None,
            error=c.DomainError(code='AI_NOT_CONFIGURED', message='해석 모델이 연결되지 않았습니다. 조건을 직접 확인해 주세요.'),
            call=c.CallMetadata(origin='AI', model_id=None, prompt_version='not-configured',
                provider_call_id=None, attempts=0, usage=None, latency_ms=0))

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
