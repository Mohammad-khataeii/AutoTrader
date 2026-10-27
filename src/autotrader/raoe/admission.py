"""Locked admission rechecks immutable plans against the actual entry book."""
from decimal import Decimal
from typing import Any

from autotrader.domain import OrderBook, TradingPair
from autotrader.opportunity.economics import CostAssumptions, CostAwareOpportunityEngine

D=Decimal


def validate(pair: TradingPair, book: OrderBook, quote: Decimal, stop: Decimal | None,
             targets: list[Decimal], evidence: dict[str,Any], fee: Decimal, slip: Decimal,
             maximum_loss: Decimal) -> str | None:
    plan=evidence.get('entry_plan',{})
    if stop is None or str(stop)!=plan.get('stop') or [str(t) for t in targets]!=plan.get('targets'):
        return 'raoe_immutable_entry_plan_mismatch'
    result=CostAwareOpportunityEngine(CostAssumptions(fee,fee,slip)).evaluate(pair,book,
        quote_budget=quote,stop=stop,targets=tuple(targets),atr=D(evidence['raoe_regime']['atr']),
        plausible_target=D(plan['ceiling']),holding_bars=72,exit_fractions=(D('.3'),D('.4'),D('.3')))
    if not result.feasible:return 'raoe_fresh_economics:'+','.join(result.reasons)
    m=result.measurements
    cost=D(m['estimated_total_round_trip_cost_eur'])
    if cost<=0 or D(m['conditional_target_net_eur'][0])<2*cost:return 'raoe_fresh_cost_headroom'
    if D(m['expected_net_stop_loss_eur'])>maximum_loss:return 'raoe_fresh_loss_budget'
    return None
