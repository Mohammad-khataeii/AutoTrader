"""Executable side-aware economics; no added spread or invented hit probability."""
from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any

from autotrader.domain import OrderBook, Side, TradingPair, quantize_down
from autotrader.execution.pricing import BPS, quote_execution
from autotrader.market_data.service import MarketDataService

D = Decimal


@dataclass(frozen=True)
class CostAssumptions:
    entry_fee_bps: Decimal = Decimal(10)
    exit_fee_bps: Decimal = Decimal(10)
    slippage_bps: Decimal = Decimal(8)
    minimum_net_reward_risk: Decimal = Decimal("1.2")
    maximum_spread_bps: Decimal = Decimal(25)

    def __post_init__(self) -> None:
        if (not all(v.is_finite() for v in asdict(self).values()) or self.minimum_net_reward_risk <= 0
            or self.maximum_spread_bps <= 0 or not all(0 <= v < BPS for v in (self.entry_fee_bps, self.exit_fee_bps, self.slippage_bps))):
            raise ValueError("invalid_opportunity_cost_assumptions")


@dataclass(frozen=True)
class OpportunityEconomics:
    feasible: bool
    reasons: tuple[str, ...]
    measurements: dict[str, Any]
    expected_value_status: str = "NOT_ESTIMATED_NO_CALIBRATED_EDGE"

    def payload(self) -> dict[str, Any]:
        return asdict(self)


class CostAwareOpportunityEngine:
    def __init__(self, assumptions: CostAssumptions | None = None):
        self.assumptions = assumptions or CostAssumptions()

    def evaluate(self, pair: TradingPair, book: OrderBook, *, quote_budget: Decimal,
                 stop: Decimal, targets: tuple[Decimal, ...], atr: Decimal,
                 plausible_target: Decimal | None, holding_bars: int, exit_fractions: tuple[Decimal, ...] | None = None) -> OpportunityEconomics:
        p = self.assumptions
        validator = MarketDataService(None)  # type: ignore[arg-type]
        reasons = validator.validate_pair(pair)
        invalid_book, _ = validator.validate_order_book(book)
        reasons.extend(invalid_book)
        if (not all(v.is_finite() for v in (quote_budget, stop, atr, *targets)) or quote_budget <= 0 or atr <= 0
            or not targets or not 0 < stop < (book.best_ask or D(0)) or holding_bars < 1
            or any(a >= b for a, b in itertools.pairwise(targets))):
            reasons.append("invalid_economic_plan")
        if reasons:
            return OpportunityEconomics(False, tuple(dict.fromkeys(reasons)), {"estimates_available": False})
        assert book.best_ask is not None and book.best_bid is not None
        quantity = quantize_down(quote_budget / (book.best_ask * (1 + (p.entry_fee_bps + p.slippage_bps) / BPS)), pair.quantity_step)
        try:
            entry = quote_execution(book, Side.BUY, quantity, quantity_step=pair.quantity_step,
                fee_bps=p.entry_fee_bps, slippage_bps=p.slippage_bps, quote_budget=quote_budget)
            exit_quote = quote_execution(book, Side.SELL, entry.fillable_quantity, quantity_step=pair.quantity_step,
                fee_bps=p.exit_fee_bps, slippage_bps=p.slippage_bps)
        except ValueError as exc:
            return OpportunityEconomics(False, (str(exc),), {"estimates_available": False})
        q = entry.fillable_quantity
        if q <= 0:
            return OpportunityEconomics(False, ("no_executable_entry_depth",), {"estimates_available": False})
        if exit_quote.fillable_quantity < q:
            reasons.append("insufficient_observed_exit_depth")
        if entry.gross_notional < pair.min_order_quote or q < pair.min_order_base:
            reasons.append("minimum_order_not_met")
        if pair.max_order_base is not None and q > pair.max_order_base:
            reasons.append("maximum_order_exceeded")
        if exit_fractions is not None:
            if len(exit_fractions)!=len(targets) or sum(exit_fractions)!=1 or any(v<=0 for v in exit_fractions):
                reasons.append('invalid_partial_exit_schedule')
            else:
                parts = [quantize_down(q*f,pair.quantity_step) for f in exit_fractions[:-1]]
                parts.append(q-sum(parts))
                if any(amount<pair.min_order_base or amount*target<pair.min_order_quote for amount,target in zip(parts,targets,strict=True)):
                    reasons.append('partial_exit_below_instrument_minimum')
        if entry.spread_bps > p.maximum_spread_bps:
            reasons.append("spread_too_wide")
        # Observed exit depth impact is reused conservatively for hypothetical
        # future prices. It is an assumption, not a promise of future liquidity.
        factor = (1 - p.exit_fee_bps / BPS) * (1 - p.slippage_bps / BPS) * (1 - exit_quote.depth_impact_bps / BPS)
        unit_cost = -entry.net_cash_change / q
        net_targets = tuple(q * (t * factor - unit_cost) for t in targets)
        loss = q * (unit_cost - stop * factor)
        reward_risk = net_targets[0] / loss if loss > 0 else None
        breakeven = unit_cost / factor if factor > 0 else D("Infinity")
        floor = (breakeven + (p.minimum_net_reward_risk * loss / q / factor if factor > 0 else D("Infinity")))
        if floor.is_finite():
            floor = (floor / pair.price_step).to_integral_value(rounding=ROUND_CEILING) * pair.price_step
        if net_targets[0] <= 0:
            reasons.append("first_target_destroyed_by_execution_costs")
        if reward_risk is None or reward_risk < p.minimum_net_reward_risk:
            reasons.append("net_reward_risk_below_research_minimum")
        if plausible_target is None or targets[0] > plausible_target:
            reasons.append("target_not_supported_by_observed_structure_or_volatility")
        return OpportunityEconomics(not reasons, tuple(reasons), {
            "estimates_available": True, "gross_target_return": str(targets[0] / book.best_ask - 1),
            "estimated_total_round_trip_cost_eur": str(-(entry.net_cash_change + exit_quote.net_cash_change)),
            "cost_basis_eur": str(-entry.net_cash_change), "net_target_return": str(net_targets[0] / -entry.net_cash_change),
            "conditional_target_net_eur": [str(v) for v in net_targets], "expected_net_stop_loss_eur": str(loss),
            "net_reward_risk": str(reward_risk) if reward_risk is not None else None,
            "breakeven_bid": str(breakeven), "minimum_economically_feasible_target": str(floor),
            "binary_target_stop_breakeven_probability": str(loss / (loss + net_targets[0])) if loss > 0 and net_targets[0] > 0 else None,
            "probability_limit": "Binary conditional payoff threshold only; no forecast, calibrated probability or partial-exit distribution",
            "quote_budget_eur": str(quote_budget), "size_scope": "Conditional estimate at stated size; account admission is separate",
            "partial_entry": q < quantity, "proposed_quantity": str(quantity), "fillable_quantity": str(q), "entry": entry.payload(), "exit_now": exit_quote.payload(),
            "spread_counted": "Once through actual ask-side entry and bid-side exit; never added again",
            "future_depth": "Assumed current depth-impact fraction; future depth and gap loss can be worse",
            "atr": str(atr), "stop": str(stop), "targets": [str(t) for t in targets],
            "plausible_target_ceiling": str(plausible_target) if plausible_target is not None else None,
            "holding_bars": holding_bars, "partial_exit_fractions": [str(v) for v in exit_fractions] if exit_fractions else None, "assumptions": {k: str(v) for k, v in asdict(p).items()}})
