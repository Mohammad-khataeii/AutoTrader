from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from autotrader.domain import (
    DecisionAction,
    OrderBook,
    OrderBookLevel,
    TradingDecision,
    TradingPair,
    new_id,
    utc_now,
)
from autotrader.execution_gateway import ExecutionResult
from autotrader.worker.runner import execute_ranked_candidates

PAIR_A = TradingPair("BTC-EUR", "BTC", "EUR")
PAIR_B = TradingPair("ETH-EUR", "ETH", "EUR")


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def cycle_key(self, prefix: str, symbol: str) -> str:
        return f"{prefix}-{symbol}"

    async def execute_entry_decision(
        self,
        pair: TradingPair,
        _decision: TradingDecision,
        _order_book: OrderBook,
        _idempotency_key: str,
    ) -> ExecutionResult:
        self.calls.append(pair.symbol)
        return ExecutionResult(True, "FILLED", None)


def candidate(pair: TradingPair, accepted: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        market=SimpleNamespace(
            pair=pair,
            order_book=OrderBook(
                pair.symbol,
                utc_now(),
                bids=(OrderBookLevel(Decimal("99"), Decimal("1")),),
                asks=(OrderBookLevel(Decimal("101"), Decimal("1")),),
                source="fixture",
            ),
        ),
        decision=TradingDecision(
            decision_id=new_id("dec"),
            symbol=pair.symbol,
            timestamp=utc_now(),
            action=DecisionAction.BUY if accepted else DecisionAction.WAIT,
            signal_ids=[],
            ai_assessment_id=None,
            proposed_quote_amount=Decimal("75"),
            proposed_quantity=Decimal("0.75"),
            entry_price=Decimal("100"),
            stop_loss=Decimal("95"),
            take_profit_targets=(Decimal("105"), Decimal("110"), Decimal("115")),
            accepted=accepted,
            rejected_reason=None if accepted else "fixture_rejected",
            explanation="fixture",
        ),
    )


@pytest.mark.asyncio
async def test_worker_allocates_across_ranked_candidates_until_cycle_capacity() -> None:
    gateway = FakeGateway()

    executions = await execute_ranked_candidates(  # type: ignore[arg-type]
        [candidate(PAIR_A), candidate(PAIR_B), candidate(PAIR_A, accepted=False)],
        gateway,  # type: ignore[arg-type]
        max_entries=1,
    )

    assert gateway.calls == ["BTC-EUR"]
    assert [execution.reason for execution in executions] == [
        "FILLED",
        "cycle_capacity_reached",
        "cycle_capacity_reached",
    ]
