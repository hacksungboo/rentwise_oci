"""Shared v2 contracts, maintained by the B integrator after initialization."""

from .schema import ContractError, check_contract
from .types import BUNDLE_VERSION

__all__ = ["BUNDLE_VERSION", "ContractError", "check_contract"]
