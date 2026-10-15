from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal
from itertools import pairwise
from typing import Any

from autotrader.domain import OrderBook, Side, quantize_down, utc_now

ZERO = Decimal(0)
SCALE = Decimal("0.000000000001")
BPS = Decimal(10000)


def exact(value: Decimal) -> Decimal:
    return value.quantize(SCALE, rounding=ROUND_DOWN)


@dataclass(frozen=True)
class ExecutionQuote:
    side: Side
    requested_quantity: Decimal
    fillable_quantity: Decimal
    unfilled_quantity: Decimal
    best_bid: Decimal
    best_ask: Decimal
    midpoint_mark: Decimal
    spread_bps: Decimal
    bid_depth: Decimal
    ask_depth: Decimal
    book_age_seconds: Decimal
    vwap: Decimal
    gross_notional: Decimal
    fee: Decimal
    net_cash_change: Decimal
    net_unit_proceeds: Decimal
    depth_impact_bps: Decimal
    slippage_bps: Decimal
    participation: Decimal
    allocations: tuple[tuple[int, Decimal], ...]

    def payload(self) -> dict[str, Any]:
        return {key: ([[i, str(q)] for i, q in value] if key == "allocations" else str(value))
                for key, value in asdict(self).items()}


def quote_execution(book: OrderBook, side: Side, quantity: Decimal, *,
                    quantity_step: Decimal = Decimal("0.00000001"),
                    fee_bps: Decimal = Decimal(10), slippage_bps: Decimal = Decimal(8),
                    limit_price: Decimal | None = None, quote_budget: Decimal | None = None,
                    participation: Decimal = Decimal(1),
                    consumed: dict[int, Decimal] | None = None,
                    max_age_seconds: int = 90) -> ExecutionQuote:
    """IOC depth walk. No queue priority, replenishment, or fill probability is invented.

    `consumed` is the durable per-side consumption of this exact observation.
    Net SELL proceeds include closing fees; opening fees remain in position basis.
    """
    values = (quantity, quantity_step, fee_bps, slippage_bps, participation)
    if not all(v.is_finite() for v in values) or quantity < 0 or quantity_step <= 0:
        raise ValueError("invalid_execution_parameters")
    if not ZERO <= fee_bps < BPS or not ZERO <= slippage_bps < BPS or not ZERO < participation <= 1:
        raise ValueError("invalid_execution_costs_or_participation")
    if any(v is not None and (not v.is_finite() or v <= 0) for v in (limit_price, quote_budget)):
        raise ValueError("invalid_execution_limit_or_budget")
    if not book.bids or not book.asks:
        raise ValueError("missing_book_side")
    if any(not l.price.is_finite() or not l.quantity.is_finite() or l.price <= 0 or l.quantity <= 0
           for l in (*book.bids, *book.asks)):
        raise ValueError("invalid_book_levels")
    bid, ask = book.bids[0].price, book.asks[0].price
    if bid > ask:
        raise ValueError("crossed_order_book")
    if any(a.price < b.price for a, b in pairwise(book.bids)) or any(a.price > b.price for a, b in pairwise(book.asks)):
        raise ValueError("unordered_book_levels")
    timestamp = book.timestamp.replace(tzinfo=UTC) if book.timestamp.tzinfo is None else book.timestamp
    age = Decimal(str((utc_now() - timestamp).total_seconds()))
    if age > max_age_seconds or age < -5:
        raise ValueError("stale_or_future_order_book")
    used = consumed or {}
    if any(not q.is_finite() or q < 0 for q in used.values()):
        raise ValueError("invalid_consumed_liquidity")
    filled, notional, raw_notional = ZERO, ZERO, ZERO
    allocations: list[tuple[int, Decimal]] = []
    fee_rate, slip = fee_bps / BPS, slippage_bps / BPS
    for index, level in enumerate(book.asks if side is Side.BUY else book.bids):
        price = exact(level.price * (1 + slip if side is Side.BUY else 1 - slip))
        if price <= 0:
            continue
        if limit_price is not None and ((side is Side.BUY and price > limit_price) or (side is Side.SELL and price < limit_price)):
            continue
        available = max(level.quantity * participation - used.get(index, ZERO), ZERO)
        qty = min(quantity - filled, available)
        if side is Side.BUY and quote_budget is not None:
            qty = min(qty, max((quote_budget / (1 + fee_rate) - notional) / price, ZERO))
        qty = quantize_down(qty, quantity_step)
        if qty <= 0:
            continue
        filled += qty
        notional += qty * price
        raw_notional += qty * level.price
        allocations.append((index, qty))
        if filled >= quantity:
            break
    vwap = exact(notional / filled) if filled else ZERO
    notional = exact(vwap * filled)
    fee = exact(notional * fee_rate)
    net = notional - fee if side is Side.SELL else -(notional + fee)
    best = ask if side is Side.BUY else bid
    raw_vwap = raw_notional / filled if filled else best
    impact = (raw_vwap / best - 1 if side is Side.BUY else 1 - raw_vwap / best) * BPS
    return ExecutionQuote(side, quantity, filled, quantity - filled, bid, ask, (bid + ask) / 2,
        (ask - bid) / ((bid + ask) / 2) * BPS,
        sum((l.quantity for l in book.bids), ZERO), sum((l.quantity for l in book.asks), ZERO),
        age, vwap, notional, fee, net, net / filled if filled and side is Side.SELL else ZERO,
        impact, slippage_bps, participation, tuple(allocations))


def target_gross_floor(net_target: Decimal, fee_bps: Decimal) -> Decimal:
    if not fee_bps.is_finite() or not ZERO <= fee_bps < BPS or not net_target.is_finite() or net_target <= 0:
        raise ValueError("invalid_target_costs")
    return (net_target / (1 - fee_bps / BPS)).quantize(SCALE, rounding=ROUND_CEILING)
