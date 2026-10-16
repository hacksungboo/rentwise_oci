"""AI 비용 장부 (A 의 BudgetPort 구현) + AI 호출 기록.

- reserve/settle/mark_unknown 은 요청 처리 트랜잭션과 별개의 짧은 트랜잭션으로 커밋한다.
  해석이 실패해 요청 처리가 롤백돼도 비용 기록은 남는다. 네트워크 대기 중에는 잠금을 잡지 않는다.
- 한도 = AI_BUDGET_USD. 사용액 = 정산액 + (예약 중·불명 건의 예약액). 불명(timeout 등)은 0으로 되돌리지 않는다.
- 원문·연락처·키는 저장하지 않는다.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import func, insert, select, update

from rentwise.config import settings
from rentwise.db import tables as T
from rentwise.db.database import get_db_engine
from rentwise.timeutil import iso, now

log = logging.getLogger("rentwise.ai")
BUDGET_ROW = "AI"


def _q(x) -> Decimal:
    return Decimal(str(x or 0)).quantize(Decimal("0.000001"))


def sync_limit() -> None:
    """서버 시작 시 .env 의 AI_BUDGET_USD 를 장부 한도로 반영."""
    with get_db_engine().begin() as c:
        row = c.execute(select(T.ai_budget).where(T.ai_budget.c.id == BUDGET_ROW)).first()
        if row is None:
            c.execute(insert(T.ai_budget).values(id=BUDGET_ROW, limit_usd=_q(settings.ai_budget_usd), updated_at=now()))
        elif _q(row.limit_usd) != _q(settings.ai_budget_usd):
            c.execute(update(T.ai_budget).where(T.ai_budget.c.id == BUDGET_ROW)
                      .values(limit_usd=_q(settings.ai_budget_usd), updated_at=now()))


def _spent(c) -> Decimal:
    settled = c.execute(select(func.coalesce(func.sum(T.ai_ledger.c.settled_usd), 0))
                        .where(T.ai_ledger.c.status == "SETTLED")).scalar_one()
    held = c.execute(select(func.coalesce(func.sum(T.ai_ledger.c.reserved_usd), 0))
                     .where(T.ai_ledger.c.status.in_(("RESERVED", "UNKNOWN")))).scalar_one()
    return _q(settled) + _q(held)


class LedgerBudget:
    """rentwise.engine.interpret.BudgetPort"""

    def reserve(self, attempt_key: str, max_cost_usd: Decimal) -> str:
        from rentwise.engine.interpret import BudgetExceeded
        with get_db_engine().begin() as c:
            prev = c.execute(select(T.ai_ledger.c.id).where(T.ai_ledger.c.attempt_key == attempt_key)).first()
            if prev:
                return prev.id
            q = select(T.ai_budget).where(T.ai_budget.c.id == BUDGET_ROW)
            if c.dialect.name != "sqlite":
                q = q.with_for_update()          # 한도 검사·예약 직렬화 (짧은 트랜잭션)
            budget = c.execute(q).first()
            limit = _q(budget.limit_usd) if budget else Decimal(0)
            if _spent(c) + _q(max_cost_usd) > limit:
                log.warning("ai.budget exceeded limit=%s spent=%s need=%s", limit, _spent(c), _q(max_cost_usd))
                raise BudgetExceeded()
            rid = "AIR-" + uuid.uuid4().hex[:16]
            ts = now()
            c.execute(insert(T.ai_ledger).values(id=rid, attempt_key=attempt_key[:200], status="RESERVED",
                                                 reserved_usd=_q(max_cost_usd), created_at=ts, updated_at=ts))
            return rid

    def settle(self, reservation_id: str, usage, price_version: str) -> None:
        from rentwise.engine.interpret import PRICES
        with get_db_engine().begin() as c:
            row = c.execute(select(T.ai_ledger).where(T.ai_ledger.c.id == reservation_id)).first()
            if row is None or row.status == "SETTLED":
                return                                    # 중복 정산은 이중 차감하지 않음
            model = settings.openai_model
            rate_in, rate_cached, rate_out = PRICES.get(model, PRICES[next(iter(PRICES))])
            uncached = max(0, usage.input_tokens - usage.cached_input_tokens)
            # 캐시 쓰기 1.25배까지 보수적으로 (A 문서 기준)
            cost = (Decimal(uncached) * rate_in * Decimal("1.25") + Decimal(usage.cached_input_tokens) * rate_cached
                    + Decimal(usage.output_tokens) * rate_out) / Decimal(1_000_000)
            c.execute(update(T.ai_ledger).where(T.ai_ledger.c.id == reservation_id).values(
                status="SETTLED", settled_usd=_q(cost), input_tokens=usage.input_tokens,
                cached_input_tokens=usage.cached_input_tokens, output_tokens=usage.output_tokens,
                price_version=price_version, updated_at=now()))

    def mark_unknown(self, reservation_id: str, reason: str) -> None:
        with get_db_engine().begin() as c:
            c.execute(update(T.ai_ledger).where((T.ai_ledger.c.id == reservation_id)
                                                & (T.ai_ledger.c.status == "RESERVED"))
                      .values(status="UNKNOWN", reason=(reason or "")[:60], updated_at=now()))


# --------------------------------------------------------------------------- 호출 기록
def record_call(request_id: str | None, engine_mode: str, result) -> None:
    """해석 1회 결과를 로그 한 줄 + rw_ai_calls 에 남긴다 (별도 트랜잭션)."""
    call, err = result.call, result.error
    usage = call.usage
    status = "OK" if result.status == "OK" and result.payload is not None else "ERROR"
    log.info("ai.interpret request=%s mode=%s model=%s status=%s code=%s attempts=%s tokens_in=%s cached=%s "
             "tokens_out=%s latency_ms=%s provider_id=%s",
             request_id, engine_mode, call.model_id, status, err.code if err else "-", call.attempts,
             usage.input_tokens if usage else "-", usage.cached_input_tokens if usage else "-",
             usage.output_tokens if usage else "-", call.latency_ms, call.provider_call_id or "-")
    try:
        with get_db_engine().begin() as c:
            c.execute(insert(T.ai_calls).values(
                id="AIC-" + uuid.uuid4().hex[:16], request_id=request_id, engine_mode=engine_mode,
                model_id=call.model_id, prompt_version=call.prompt_version, status=status,
                error_code=err.code if err else None, attempts=call.attempts,
                input_tokens=usage.input_tokens if usage else None,
                cached_input_tokens=usage.cached_input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                latency_ms=call.latency_ms, provider_call_id=call.provider_call_id, created_at=now()))
    except Exception:  # 기록 실패가 해석 응답을 막지 않게
        log.exception("ai.interpret record failed")


def summary(limit: int = 10) -> dict:
    with get_db_engine().connect() as c:
        budget = c.execute(select(T.ai_budget).where(T.ai_budget.c.id == BUDGET_ROW)).first()
        settled = c.execute(select(func.coalesce(func.sum(T.ai_ledger.c.settled_usd), 0))
                            .where(T.ai_ledger.c.status == "SETTLED")).scalar_one()
        spent = _spent(c)
        counts = dict(c.execute(select(T.ai_calls.c.status, func.count()).group_by(T.ai_calls.c.status)).all())
        rows = c.execute(select(T.ai_calls).order_by(T.ai_calls.c.created_at.desc()).limit(limit)).all()
    return {
        "limit_usd": float(_q(budget.limit_usd)) if budget else 0.0,
        "settled_usd": float(_q(settled)),
        "committed_usd": float(spent),               # 정산 + 예약 중/불명
        "calls": {"ok": counts.get("OK", 0), "error": counts.get("ERROR", 0)},
        "recent": [{
            "at": iso(r.created_at), "request_id": r.request_id, "mode": r.engine_mode, "model_id": r.model_id,
            "status": r.status, "error_code": r.error_code, "attempts": r.attempts,
            "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "latency_ms": r.latency_ms,
            "provider_call_id": r.provider_call_id} for r in rows],
    }
