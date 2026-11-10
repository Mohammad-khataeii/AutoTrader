"""Fail-closed quality gates for Alpaca crypto midpoint bars and paper BUY sizing.

Pure functions only: no broker calls, database writes, scheduling, or real orders.
"""
from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation, ROUND_DOWN


def untraded_quote_outlier(hourly, lookback=21):
    """Identify a large zero-trade quote excursion contaminating entry indicators.

    Zero volume alone does NOT invalidate Alpaca midpoint bars; a large
    untraded excursion does. Inspect only finalized candles already supplied.
    """
    for bar in hourly[-lookback:]:
        try:
            o, h, l, c, v = (float(bar[key]) for key in ("o", "h", "l", "c", "v"))
            if not all(math.isfinite(x) for x in (o, h, l, c, v)):
                return {"reason": "nonfinite_candle", "bar_at": bar.get("ts")}
            if min(o, h, l, c) <= 0 or h < max(o, c, l) or l > min(o, c, h) or v < 0:
                return {"reason": "invalid_candle", "bar_at": bar.get("ts")}
            if v == 0 and (h / l - 1 > 0.12 or abs(c / o - 1) > 0.08):
                return {"reason": "untraded_quote_outlier", "bar_at": bar.get("ts")}
        except (KeyError, ValueError, TypeError, ZeroDivisionError, OverflowError):
            return {"reason": "invalid_candle", "bar_at": bar.get("ts")}
    return None


def depth_limited_notional(desired, ask, bid, ask_size, bid_size,
                           *, min_usd="25", participation="0.20"):
    """Bound a BUY to 20% of BOTH sides of the visible top-of-book depth.

    Top of book does not guarantee execution. This is a conservative cap, not
    an order-book sweep simulator, and must still pass all existing risk gates.
    """
    try:
        d, a, b, az, bz, lower, ratio = (
            Decimal(str(x)) for x in
            (desired, ask, bid, ask_size, bid_size, min_usd, participation)
        )
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return None, "crypto_entry_depth_invalid"
    if any(not x.is_finite() for x in (d, a, b, az, bz, lower, ratio)):
        return None, "crypto_entry_depth_invalid"
    if min(d, a, b, az, bz, lower, ratio) <= 0 or b >= a or ratio > Decimal("0.20"):
        return None, "crypto_entry_depth_invalid"
    cap = min(d, a * az * ratio, b * bz * ratio)
    capped = cap.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if capped < lower:
        return None, "crypto_entry_depth_below_minimum"
    return capped, ("crypto_entry_depth_capped" if capped < d else "crypto_entry_depth_ok")
