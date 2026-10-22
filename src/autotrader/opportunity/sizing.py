"""An explicit size proposal, never authority to spend or override portfolio risk."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from autotrader.domain import OrderBook, TradingPair
from autotrader.risk import RiskLimits

D = Decimal


def quote_for_plan(pair: TradingPair, book: OrderBook, stop: Decimal, *, cash: Decimal,
                   exposure: Decimal = D(0), preferred: Decimal = D(75),
                   fee_bps: Decimal = D(10), slippage_bps: Decimal = D(8),
                   limits: RiskLimits | None = None) -> tuple[Decimal, dict[str, Any]]:
    policy = limits or RiskLimits()
    ask = book.best_ask or D(0)
    if ask <= 0 or stop <= 0 or stop >= ask or not all(v.is_finite() for v in (stop,cash,exposure,preferred)):
        return D(0), {'scope': 'SIZE_PROPOSAL_ONLY', 'reason': 'invalid_sizing_inputs'}
    allowance = max(policy.planned_loss_cost_bps, 2*(fee_bps+slippage_bps)) / 10000
    loss_fraction = (ask-stop)/ask+allowance
    instrument_exit_budget = pair.min_order_quote/D('.3')*D('1.01')
    preferred = max(preferred, instrument_exit_budget)
    constraints = {'preferred': preferred, 'position_cap': policy.max_position_size,
        'cash_after_reserve': max(D(0), cash-policy.min_uncommitted_reserve),
        'exposure_room': max(D(0), policy.max_total_open_exposure-exposure),
        'allocation_room': max(D(0), policy.max_allocated_capital-exposure),
        'planned_loss_budget': policy.max_planned_loss_per_trade/loss_fraction}
    if pair.max_order_base is not None:
        constraints['instrument_maximum'] = pair.max_order_base*ask
    quote = max(D(0), min(constraints.values()))
    return quote, {'scope': 'SIZE_PROPOSAL_ONLY', 'quote_budget_eur': str(quote),
        'constraints_eur': {k:str(v) for k,v in constraints.items()},
        'binding_constraint': min(constraints,key=lambda k:constraints[k]),
        'minimum_order_quote_eur': str(pair.min_order_quote), 'partial_exit_minimum_budget_eur': str(instrument_exit_budget), 'financial_risk_admission_required': True}
