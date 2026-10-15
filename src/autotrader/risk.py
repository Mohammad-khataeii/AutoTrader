from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from autotrader.domain import RiskEvaluation, TradingPair, new_id
from autotrader.portfolio import Portfolio


@dataclass(frozen=True)
class RiskLimits:
    max_allocated_capital: Decimal = Decimal("500")
    max_total_open_exposure: Decimal = Decimal("350")
    min_uncommitted_reserve: Decimal = Decimal("150")
    max_position_size: Decimal = Decimal("100")
    max_simultaneous_positions: int = 3
    max_planned_loss_per_trade: Decimal = Decimal("5")
    daily_loss_threshold: Decimal = Decimal("15")
    weekly_loss_threshold: Decimal = Decimal("35")
    max_new_entries_per_day: int = 6
    planned_loss_cost_bps: Decimal = Decimal("25")


class RiskEngine:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def evaluate_entry(
        self,
        portfolio: Portfolio,
        pair: TradingPair,
        quote_amount: Decimal,
        entry_price: Decimal,
        stop_loss: Decimal,
        entries_today: int,
        daily_pnl: Decimal = Decimal("0"),
        weekly_pnl: Decimal = Decimal("0"),
    ) -> RiskEvaluation:
        checks: dict[str, bool] = {}
        reasons: list[str] = []

        entry_price_valid = entry_price > 0
        stop_loss_valid = stop_loss > 0
        long_stop_valid = entry_price_valid and stop_loss_valid and stop_loss < entry_price
        planned_loss_ratio = ((entry_price - stop_loss) / entry_price) if long_stop_valid else Decimal("0")
        execution_cost_allowance = quote_amount * self.limits.planned_loss_cost_bps / Decimal("10000")
        planned_loss = (quote_amount * planned_loss_ratio) + execution_cost_allowance
        open_positions = len([position for position in portfolio.positions.values() if position.closed_at is None])
        projected_cash = portfolio.cash - quote_amount
        projected_exposure = portfolio.open_exposure + quote_amount

        checks["paper_only"] = True
        checks["quote_amount_positive"] = quote_amount > 0
        checks["entry_price_positive"] = entry_price_valid
        checks["stop_loss_positive"] = stop_loss_valid
        checks["long_stop_below_entry"] = long_stop_valid
        checks["minimum_order_size"] = quote_amount >= pair.min_order_quote
        checks["position_size"] = quote_amount <= self.limits.max_position_size
        checks["cash_available"] = portfolio.cash >= quote_amount
        checks["reserve_preserved"] = projected_cash >= self.limits.min_uncommitted_reserve
        checks["total_exposure"] = projected_exposure <= self.limits.max_total_open_exposure
        checks["allocated_capital"] = projected_exposure <= self.limits.max_allocated_capital
        checks["position_count"] = open_positions < self.limits.max_simultaneous_positions
        checks["planned_loss"] = planned_loss <= self.limits.max_planned_loss_per_trade
        checks["daily_loss_budget"] = abs(min(daily_pnl, Decimal("0"))) < self.limits.daily_loss_threshold
        checks["weekly_loss_budget"] = abs(min(weekly_pnl, Decimal("0"))) < self.limits.weekly_loss_threshold
        checks["entry_frequency"] = entries_today < self.limits.max_new_entries_per_day

        for check, passed in checks.items():
            if not passed:
                reasons.append(check)

        max_affordable = max(portfolio.cash - self.limits.min_uncommitted_reserve, Decimal("0"))
        max_by_limits = min(max_affordable, self.limits.max_position_size, self.limits.max_total_open_exposure - portfolio.open_exposure)
        max_quote_by_risk = (
            (self.limits.max_planned_loss_per_trade - execution_cost_allowance) / planned_loss_ratio
            if planned_loss_ratio > 0 and self.limits.max_planned_loss_per_trade > execution_cost_allowance
            else Decimal("0")
        )
        max_by_limits = min(max_by_limits, max_quote_by_risk) if long_stop_valid else Decimal("0")
        max_quantity = max(max_by_limits / entry_price, Decimal("0")) if entry_price_valid else Decimal("0")
        return RiskEvaluation(
            evaluation_id=new_id("risk"),
            accepted=not reasons,
            checks=checks,
            reasons=reasons,
            max_quantity=max_quantity,
            reserved_quote=quote_amount if not reasons else Decimal("0"),
        )
