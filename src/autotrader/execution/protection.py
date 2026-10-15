from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from autotrader.execution.pricing import BPS


@dataclass(frozen=True)
class TrailingUpdate:
    stop: Decimal
    distance: Decimal
    breakeven_bid: Decimal


def trailing_update(*, previous_stop: Decimal, highest_bid: Decimal, basis: Decimal,
                    quantity: Decimal, distance: Decimal, atr: Decimal | None,
                    fee_bps: Decimal, slippage_bps: Decimal) -> TrailingUpdate:
    if quantity <= 0 or not 0 <= fee_bps < BPS or not 0 <= slippage_bps < BPS:
        raise ValueError("invalid_trailing_parameters")
    adjusted_distance = atr * Decimal("1.5") if atr is not None and atr.is_finite() and atr > 0 else distance
    if adjusted_distance <= 0:
        raise ValueError("invalid_trailing_distance")
    breakeven = basis / quantity / ((1 - fee_bps / BPS) * (1 - slippage_bps / BPS))
    return TrailingUpdate(max(previous_stop, breakeven, highest_bid - adjusted_distance), adjusted_distance, breakeven)
