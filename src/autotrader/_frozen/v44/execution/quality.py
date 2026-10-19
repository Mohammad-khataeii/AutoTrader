from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from autotrader.domain import OrderBook, Side, TradingPair
from autotrader.execution.pricing import BPS, ExecutionQuote, quote_execution


@dataclass(frozen=True)
class ExecutionQuality:
    entry: ExecutionQuote
    rejection_reasons: tuple[str, ...]
    breakeven_bid: Decimal
    immediate_round_trip_net: Decimal
    target_net_scenarios: tuple[Decimal, ...]

    def payload(self) -> dict[str, Any]:
        return {"entry": self.entry.payload(), "rejection_reasons": list(self.rejection_reasons),
                "breakeven_bid": str(self.breakeven_bid),
                "immediate_round_trip_net": str(self.immediate_round_trip_net),
                "target_net_scenarios": [str(v) for v in self.target_net_scenarios],
                "policy": "execution-quality-4.0.0", "probability_estimate": None}


class ExecutionQualityEngine:
    """Cost feasibility, not an invented probability or a predictive edge estimate."""
    def __init__(self, max_spread_bps: Decimal = Decimal(75)) -> None:
        self.max_spread_bps = max_spread_bps

    def evaluate(self, pair: TradingPair, book: OrderBook, quantity: Decimal, quote_budget: Decimal,
                 fee_bps: Decimal, slippage_bps: Decimal, targets: list[Decimal]) -> ExecutionQuality:
        entry = quote_execution(book, Side.BUY, quantity, quantity_step=pair.quantity_step,
            fee_bps=fee_bps, slippage_bps=slippage_bps, quote_budget=quote_budget)
        closing = quote_execution(book, Side.SELL, entry.fillable_quantity, quantity_step=pair.quantity_step,
            fee_bps=fee_bps, slippage_bps=slippage_bps)
        reasons: list[str] = []
        if entry.spread_bps > self.max_spread_bps:
            reasons.append("spread_exceeds_entry_limit")
        if entry.gross_notional < pair.min_order_quote or entry.fillable_quantity < pair.min_order_base:
            reasons.append("insufficient_executable_entry_notional")
        if closing.fillable_quantity < entry.fillable_quantity:
            reasons.append("insufficient_observed_exit_depth")
        unit_cost = -entry.net_cash_change / entry.fillable_quantity if entry.fillable_quantity else Decimal(0)
        exit_factor = (1 - fee_bps / BPS) * (1 - slippage_bps / BPS)
        breakeven = unit_cost / exit_factor
        scenarios = tuple(entry.fillable_quantity * (target * exit_factor - unit_cost) for target in targets)
        if scenarios and scenarios[0] <= 0:
            reasons.append("first_target_destroyed_by_execution_costs")
        return ExecutionQuality(entry, tuple(reasons), breakeven,
            closing.net_cash_change + entry.net_cash_change, scenarios)
