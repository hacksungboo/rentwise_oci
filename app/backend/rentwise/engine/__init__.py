"""A planning engines, with B's unchanged v1 RealEngine entry point.

RealEngine uses B v1 DTOs and limits candidates to B's current write capability.
Direct solve/validate/availability functions retain the independent v2 core API.
See docs/handoffs/A.md for supported operations and remaining product limits.
"""

from .availability import availability
from .validate import validate
from .solver import solve
from .compat import RealEngine

__all__ = ["availability", "validate", "solve", "RealEngine"]
