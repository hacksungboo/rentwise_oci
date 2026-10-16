from __future__ import annotations

from functools import lru_cache

from rentwise.config import settings


@lru_cache
def get_engine():
    """EnginePort 단일 주입 지점. ENGINE_MODE=mock|real"""
    if settings.engine_mode == "real":
        from rentwise.engine import RealEngine  # A 구현
        from rentwise.services.ai_ledger import LedgerBudget  # B 영속 비용 장부
        return RealEngine(budget=LedgerBudget())
    from rentwise.dev_fakes.mock_engine import MockEngine
    return MockEngine()
