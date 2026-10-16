"""A's deterministic v2 JSON core; no DB, network, or input mutation.

Import solve/validate/availability for v2 callers. B's v1 EnginePort and
RealEngine registry integration remain pending; keep ENGINE_MODE=mock.
See docs/handoffs/A.md before wiring the service's confirmation path.
"""

from .availability import availability
from .validate import validate
from .solver import solve

__all__ = ["availability", "validate", "solve"]
