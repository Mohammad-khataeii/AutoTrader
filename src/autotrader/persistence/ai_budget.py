"""Durable reservations around billable requests; unknown outcomes retain their hold."""
from __future__ import annotations

import json
from decimal import ROUND_CEILING, Decimal
from typing import Any

from sqlalchemy import select

from autotrader.domain import new_id, utc_now
from autotrader.persistence.models import AIBudgetModel, AIUsageModel


def dollars(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_CEILING)


class AIBudgetRepositoryMixin:
    session_factory: Any

    async def _lock_account(self, session: Any) -> Any:
        raise NotImplementedError

    async def reserve_ai_budget(self, amount: Decimal, model: str, symbol: str,
                                prices: dict[str, str], limit: Decimal = Decimal("10")) -> str | None:
        if not amount.is_finite() or amount <= 0 or limit > 10 or limit < 0:
            raise ValueError("Invalid AI budget policy.")
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            month = utc_now().strftime("%Y-%m")
            budget = await session.get(AIBudgetModel, month, with_for_update=True)
            if budget is None:
                budget = AIBudgetModel(month=month, spent=Decimal(0), reserved=Decimal(0))
                session.add(budget)
                await session.flush()
            if budget.spent + budget.reserved + dollars(amount) > limit:
                return None
            budget.reserved += dollars(amount)
            request_id = new_id("req")
            session.add(AIUsageModel(request_id=request_id, month=month, model=model, status="RESERVED",
                reserved_cost=dollars(amount), input_tokens=0, output_tokens=0, cached_input_tokens=0,cache_write_tokens=0,
                candidate_symbol=symbol, provider="openai", pricing_json=json.dumps(prices), created_at=utc_now()))
            return request_id

    async def ai_request_sent(self, request_id: str) -> None:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            usage = await session.get(AIUsageModel, request_id, with_for_update=True)
            if usage is None or usage.status != "RESERVED":
                raise ValueError("Request is not reserved; automatic retry forbidden.")
            usage.status = "SENT"

    async def finish_ai_request(self, request_id: str, *, input_tokens: int = 0,
                                output_tokens: int = 0, cached_tokens: int = 0,
                                cache_write_tokens:int=0,
                                cost: Decimal | None = None, error: str | None = None) -> None:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            usage = await session.get(AIUsageModel, request_id, with_for_update=True)
            if usage is None:
                raise ValueError("Unknown AI request.")
            if usage.status in {"COMPLETED", "FAILED_CHARGED"}:
                return
            usage.error = error
            if cost is None:
                usage.status = "UNKNOWN"
                return  # Keep the reservation until an audited billing reconciliation.
            if cost < 0 or not cost.is_finite() or min(input_tokens,output_tokens,cached_tokens,cache_write_tokens) < 0 or cached_tokens+cache_write_tokens > input_tokens:
                raise ValueError("Invalid provider usage.")
            budget = await session.get(AIBudgetModel, usage.month, with_for_update=True)
            budget.reserved -= usage.reserved_cost
            budget.spent += dollars(cost)
            usage.actual_cost = dollars(cost)
            usage.input_tokens, usage.output_tokens, usage.cached_input_tokens = input_tokens, output_tokens, cached_tokens
            usage.cache_write_tokens=cache_write_tokens
            usage.status = "FAILED_CHARGED" if error else "COMPLETED"
            if cost > usage.reserved_cost:
                usage.error = "Configured price/token bound violated; paid requests require operator review."
                # Retain a prohibitive hold, without changing the recorded actual charge.
                budget.reserved += Decimal("10")

    async def ai_budget_status(self, limit: Decimal = Decimal("10")) -> dict[str, Any]:
        async with self.session_factory() as session:
            month = utc_now().strftime("%Y-%m")
            budget = await session.get(AIBudgetModel, month)
            rows = (await session.scalars(select(AIUsageModel).where(AIUsageModel.month == month))).all()
            spent, reserved = (budget.spent, budget.reserved) if budget else (Decimal(0),Decimal(0))
            return {"month":month, "spent_usd":str(spent), "reserved_usd":str(reserved),
                "remaining_usd":str(max(limit-spent-reserved,Decimal(0))), "requests":len(rows),
                "input_tokens":sum(r.input_tokens for r in rows), "output_tokens":sum(r.output_tokens for r in rows),
                "cached_input_tokens":sum(r.cached_input_tokens for r in rows),
                "cache_write_tokens":sum(r.cache_write_tokens for r in rows),
                "errors":[{"request_id":r.request_id,"status":r.status,"error":r.error} for r in rows if r.error or r.status=="UNKNOWN"]}
