"""Causal, read-only early-rebound research for Alpaca quote-midpoint bars.

This module never emits a trading signal or sends a broker order. It is a
shadow hypothesis to be assessed with out-of-sample replay, real quote/depth
checks, and cautious paper execution before any separate activation decision.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

CHECK_NAMES = (
    "consecutive_completed_hours",
    "prior_selloff",
    "rising_close_and_higher_low",
    "reclaimed_six_hour_average",
    "positive_trade_volume",
    "bounded_rebound",
    "recovering_rsi",
    "bounded_stop_distance",
)


def assess(hourly, atr, rsi):
    """Assess ONLY the 24 most recent completed, already-quality-checked bars.

    In particular, a zero-volume Alpaca midpoint quote is not trade evidence.
    An isolated price jump, a falling knife, or a missing hour fails closed.
    """
    checks = {key: False for key in CHECK_NAMES}
    result = {"passed": False, "checks": checks, "score": 0.0,
              "stop": None, "target": None}
    if len(hourly) < 24:
        return result
    try:
        bars = hourly[-24:]
        closes = [float(b["c"]) for b in bars]
        lows = [float(b["l"]) for b in bars]
        volumes = [float(b["v"]) for b in bars]
        atr, rsi = float(atr), float(rsi)
        if (not all(math.isfinite(x) for x in closes + lows + volumes + [atr, rsi])
                or any(x <= 0 for x in closes + lows) or any(x < 0 for x in volumes)
                or atr <= 0):
            return result
        dates = [datetime.fromisoformat(str(b["ts"]).replace("Z", "+00:00"))
                 for b in bars[-4:]]
        checks["consecutive_completed_hours"] = (
            all(d.tzinfo is not None for d in dates) and
            all(dates[i] - dates[i - 1] == timedelta(hours=1) for i in range(1, 4))
        )
        # The prior peak is frozen before the most recent four observations;
        # the trough is frozen before the signal bar to prevent lookahead.
        peak = max(closes[:-4])
        trough = min(closes[-12:-1])
        close = closes[-1]
        checks["prior_selloff"] = (
            peak > trough and (peak - trough) / peak >= 0.03 and
            peak - trough >= 2 * atr
        )
        checks["rising_close_and_higher_low"] = (
            close > closes[-2] >= closes[-3] and lows[-1] >= lows[-2]
        )
        checks["reclaimed_six_hour_average"] = close > sum(closes[-6:]) / 6
        checks["positive_trade_volume"] = (
            all(v > 0 for v in volumes[-2:]) and
            sum(v > 0 for v in volumes[-4:]) >= 3
        )
        checks["bounded_rebound"] = (
            trough + 0.35 * atr <= close <= trough + 2.5 * atr
        )
        checks["recovering_rsi"] = 36 <= rsi <= 62
        stop = trough - 0.25 * atr
        risk = close - stop
        checks["bounded_stop_distance"] = (
            stop > 0 and 0.002 <= risk / close <= 0.045
        )
        passed = all(checks.values())
        result.update({
            "passed": passed,
            "score": round(sum(checks.values()) / len(checks), 3),
            "stop": round(stop, 10) if passed else None,
            "target": round(close + 2 * risk, 10) if passed else None,
        })
    except (TypeError, ValueError, KeyError, OverflowError, ZeroDivisionError):
        return {"passed": False, "checks": {key: False for key in CHECK_NAMES},
                "score": 0.0, "stop": None, "target": None}
    return result


def market_breadth(usd_signals, gates_by_symbol):
    """Compact explanation of the USD-only model's entry bottlenecks.

    Rows marked WAIT contribute to data blocks, not to trend denominators.
    This is diagnostic market breadth, not a market prediction or BUY advice.
    """
    ready = [s for s in usd_signals if s.get("action") in ("HOLD", "BUY")]
    waiting = len(usd_signals) - len(ready)
    checks = ("hourly_uptrend", "daily_above_ema200", "20_hour_breakout",
              "rsi_volatility_healthy")
    fail_counts = {key: sum(not bool(gates_by_symbol.get(s["symbol"], {}).get(key))
                            for s in ready) for key in checks}
    confirmed = sum(bool(gates_by_symbol.get(s["symbol"], {}).get("shadow_rebound_watch"))
                    for s in ready)
    n = len(ready)
    if not n:
        regime = "INSUFFICIENT_CURRENT_SIGNALS"
    elif (fail_counts["hourly_uptrend"] / n >= 0.75 and
          fail_counts["daily_above_ema200"] / n >= 0.65):
        regime = "BROAD_DOWNTREND"
    elif fail_counts["hourly_uptrend"] / n < 0.40 and fail_counts["daily_above_ema200"] / n < 0.50:
        regime = "BROAD_UPTREND"
    else:
        regime = "MIXED_OR_TRANSITIONING"
    return {
        "mode": "RESEARCH_ONLY_NOT_ORDER_PERMISSION",
        "regime": regime,
        "usd_ready": n,
        "usd_waiting": waiting,
        "failed_gates": fail_counts,
        "shadow_rebound_watch_count": confirmed,
        "no_new_entry_is_valid": True,
    }
