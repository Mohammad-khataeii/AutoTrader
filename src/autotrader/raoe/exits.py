"""Convert supported bid scenarios to the broker's minimum-net unit exits.

The original structural bid targets remain immutable in entry evidence. Only
new RAOE plans use this conversion. Future depth is explicitly an assumption.
"""
from decimal import Decimal
from typing import Any

from autotrader.domain import OrderBook, Side, quantize_down
from autotrader.execution.pricing import quote_execution

D=Decimal


def net_exit_targets(targets: list[Decimal], book: OrderBook, quantity: Decimal,
                     quantity_step: Decimal, fee_bps: Decimal, slippage_bps: Decimal) -> tuple[list[Decimal],dict[str,Any]]:
    closing=quote_execution(book,Side.SELL,quantity,quantity_step=quantity_step,
        fee_bps=fee_bps,slippage_bps=slippage_bps)
    if closing.fillable_quantity<quantity:raise ValueError('raoe_exit_depth_unavailable_at_plan_creation')
    factor=(1-fee_bps/10000)*(1-slippage_bps/10000)*(1-closing.depth_impact_bps/10000)
    converted=[quantize_down(t*factor,D('1e-12')) for t in targets]
    return converted,{'target_semantics':'MINIMUM_NET_UNIT_EXIT_PROCEEDS',
        'original_bid_targets':[str(t) for t in targets], 'net_unit_targets':[str(t) for t in converted],
        'assumed_exit_factor':str(factor),'exit_fee_bps':str(fee_bps),'exit_slippage_bps':str(slippage_bps),
        'depth_impact_bps':str(closing.depth_impact_bps),
        'limitation':'Current observed depth impact is assumed at future bid targets; future liquidity may differ'}
