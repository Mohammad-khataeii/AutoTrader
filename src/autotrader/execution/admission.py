"""One quantity-aware BUY projection for every simulated financial account."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any

from autotrader.domain import OrderBook, Side, TradingPair
from autotrader.execution.pricing import BPS, ExecutionQuote, exact, quote_execution

D = Decimal


@dataclass(frozen=True)
class BuyAdmission:
    entry: ExecutionQuote
    planned_loss: Decimal
    stop_net_unit: Decimal
    uncertainty_buffer: Decimal
    observed_exit_depth_complete: bool

    def payload(self) -> dict[str, Any]:
        return {'version': 'quantity-aware-admission/4.9.0', 'entry': self.entry.payload(),
                'planned_loss_eur': str(self.planned_loss), 'stop_net_unit': str(self.stop_net_unit),
                'unmodeled_risk_buffer_eur': str(self.uncertainty_buffer),
                'observed_exit_depth_complete': self.observed_exit_depth_complete,
                'future_exit_depth': 'Current observed impact is an assumption, not future liquidity',
                'cost_policy': 'Entry VWAP includes entry slippage once; fees and stop-side slippage once; spread is not added again'}


def project_buy(pair: TradingPair, book: OrderBook, quantity: Decimal, quote_budget: Decimal,
                stop: Decimal | None, fee_bps: Decimal, slippage_bps: Decimal, *,
                consumed: dict[int, Decimal] | None = None, limit_price: Decimal | None = None,
                participation: Decimal = D(1), risk_cost_floor_bps: Decimal = D(25)) -> BuyAdmission:
    entry = quote_execution(book, Side.BUY, quantity, quantity_step=pair.quantity_step,
                            fee_bps=fee_bps, slippage_bps=slippage_bps, quote_budget=quote_budget,
                            consumed=consumed, limit_price=limit_price, participation=participation)
    closing = quote_execution(book, Side.SELL, entry.fillable_quantity,
                              quantity_step=pair.quantity_step, fee_bps=fee_bps,
                              slippage_bps=slippage_bps, participation=participation)
    factor = (1-fee_bps/BPS)*(1-slippage_bps/BPS)*(1-closing.depth_impact_bps/BPS)
    net_stop = (stop or D(0))*factor
    spend = -entry.net_cash_change
    # The configured minimum cost allowance is a FLOOR. Quoted entry slippage
    # and the ask/bid geometry already enter the loss; never charge them twice.
    covered_bps = 2*fee_bps+2*slippage_bps+entry.spread_bps+entry.depth_impact_bps+closing.depth_impact_bps
    buffer = spend*max(D(0), risk_cost_floor_bps-covered_bps)/BPS
    loss = max(D(0), spend-entry.fillable_quantity*net_stop)+buffer
    return BuyAdmission(entry, loss.quantize(D('1e-12'), rounding=ROUND_CEILING), net_stop, exact(buffer),
                        closing.fillable_quantity == entry.fillable_quantity)
