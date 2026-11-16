"""Opt-in, small-risk, long-only exploratory Alpaca PAPER signal.

Closed, quality-checked hourly midpoint bars only. The caller still enforces
Alpaca paper identity, fresh executable quotes/depth and portfolio risk caps.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta


def assess(hourly, ema20, ema50, atr, rsi):
    names = (
        "eight_contiguous_closed_hours", "positive_traded_volume",
        "reclaimed_rising_ema20", "upward_price_confirmation",
        "six_hour_breakout_or_higher_lows", "not_extended",
        "bounded_volatility_and_rsi", "valid_exit_levels",
    )
    checks = {k: False for k in names}
    out = {"passed": False, "checks": checks, "stop": None, "target": None}
    try:
        if len(hourly) < 24:
            return out
        recent = hourly[-8:]
        closes = [float(b["c"]) for b in recent]
        lows = [float(b["l"]) for b in recent]
        highs = [float(b["h"]) for b in recent]
        opens = [float(b["o"]) for b in recent]
        volumes = [float(b["v"]) for b in recent]
        ema20, ema50, atr, rsi = map(float, (ema20, ema50, atr, rsi))
        vals = closes + lows + highs + opens + volumes + [ema20, ema50, atr, rsi]
        if (not all(math.isfinite(x) for x in vals) or
                min(closes + lows + highs + opens + [ema20, ema50, atr]) <= 0 or
                min(volumes) < 0):
            return out
        stamps = [datetime.fromisoformat(str(b["ts"]).replace("Z", "+00:00")) for b in recent]
        checks["eight_contiguous_closed_hours"] = (
            all(t.tzinfo is not None for t in stamps) and
            all(stamps[i]-stamps[i-1] == timedelta(hours=1) for i in range(1, 8)))
        close, previous = closes[-1], closes[-2]
        k = 2.0 / 21.0
        ema20_before = (ema20-k*close)/(1-k)
        checks["positive_traded_volume"] = (volumes[-1] > 0 and sum(v > 0 for v in volumes[-6:]) >= 2)
        checks["reclaimed_rising_ema20"] = (
            close > ema20 and ema20 >= ema20_before and close > ema50*0.98)
        checks["upward_price_confirmation"] = (
            close > previous and close > opens[-1] and
            close - closes[-4] >= 0.25*atr)
        checks["six_hour_breakout_or_higher_lows"] = (
            close > max(highs[-7:-1]) or
            (lows[-1] > lows[-2] > lows[-3] and
             closes[-1] > closes[-2] > closes[-3]))
        checks["not_extended"] = (close - ema20 <= 1.5*atr)
        checks["bounded_volatility_and_rsi"] = (0.0015 <= atr/close <= 0.065 and 40 <= rsi <= 74)
        stop = close - 1.8*atr
        target = close + 2.7*atr
        checks["valid_exit_levels"] = stop > 0 and target > close > stop
        out["passed"] = all(checks.values())
        if out["passed"]:
            out["stop"] = round(stop, 10)
            out["target"] = round(target, 10)
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        pass
    return out


def benchmark_ok(btc_bars, signal_at):
    """Avoid non-BTC entry while BTC is in a sharp three-hour liquidation."""
    try:
        bars = list(btc_bars)[-4:]
        if len(bars) != 4 or bars[-1]["ts"] != signal_at:
            return False
        ts = [datetime.fromisoformat(str(b["ts"]).replace("Z", "+00:00")) for b in bars]
        close = [float(b["c"]) for b in bars]
        volume = [float(b["v"]) for b in bars]
        return (all(t.tzinfo is not None for t in ts)
                and all(ts[i]-ts[i-1] == timedelta(hours=1) for i in range(1,4))
                and all(math.isfinite(x) and x > 0 for x in close)
                and all(math.isfinite(x) and x >= 0 for x in volume)
                and volume[-1] > 0
                and close[-1] >= close[0]*0.99)
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        return False
