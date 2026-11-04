"""Timestamped public-depth estimates. This module never posts or accepts a fill. Untested and unvalidated."""
from __future__ import annotations

import hashlib
from decimal import Decimal

from autotrader.perpetuals.micro.types import Book, DepthEstimate, Intent

D = Decimal
BOOK_MAX_AGE_MS = 1500
INTENT_TTL_MS = 3000
SLIPPAGE_FLOOR = D('.0005')


def vwap(levels: tuple[tuple[Decimal, Decimal], ...], quantity: Decimal) -> Decimal:
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError('invalid_quote_quantity')
    remaining, value = quantity, D(0)
    for price, size in levels:
        take = min(size, remaining)
        value += take * price
        remaining -= take
        if remaining == 0:
            return value / quantity
    raise ValueError('insufficient_observed_depth')


def estimate(intent: Intent, book: Book, now: int) -> DepthEstimate:
    """Use a book produced AFTER the decision, never a later candle's opening price.

    Both entry and exit-now depth must cover the size. A public snapshot can
    disappear before an order reaches a venue; this remains an indicative quote.
    A future experiment still needs durable intent reservation and atomic fills.
    """
    if (intent.side not in {-1, 1} or intent.expires_at > intent.decision_at + INTENT_TTL_MS
            or not intent.decision_at <= book.exchange_at <= book.received_at <= now <= intent.expires_at
            or now - book.exchange_at > BOOK_MAX_AGE_MS):
        raise ValueError('stale_predecision_or_expired_depth')
    if not book.bids or not book.asks or book.bids[0][0] >= book.asks[0][0]:
        raise ValueError('crossed_or_empty_depth')
    for levels, descending in ((book.bids, True), (book.asks, False)):
        if (any(not p.is_finite() or not q.is_finite() or p <= 0 or q <= 0 for p, q in levels)
                or any((levels[i][0] <= levels[i + 1][0]) if descending else
                       (levels[i][0] >= levels[i + 1][0]) for i in range(len(levels) - 1))):
            raise ValueError('invalid_depth_levels')
    side = intent.side
    buy, sell = vwap(book.asks, intent.quantity), vwap(book.bids, intent.quantity)
    # The residual slippage floor is applied once, in addition to the observed
    # spread/depth. Spread is already in VWAP versus mid, never added twice.
    entry = (buy if side == 1 else sell) * (1 + side * SLIPPAGE_FLOOR)
    exit_now = (sell if side == 1 else buy) * (1 - side * SLIPPAGE_FLOOR)
    entry_cost = side * (entry / book.mid - 1)
    exit_cost = side * (1 - exit_now / book.mid)
    evidence = repr((intent, book)).encode()
    return DepthEstimate(intent.key, intent.quantity, book.mid, entry, exit_now,
                         entry_cost, exit_cost, book.spread, book.received_at,
                         hashlib.sha256(evidence).hexdigest())
