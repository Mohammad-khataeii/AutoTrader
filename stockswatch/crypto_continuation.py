"""Causal, long-only crypto trend continuation gate.

Reads only finalized Alpaca candles already supplied by the caller. This module
has no broker, network, database or order-submission access.
"""
from __future__ import annotations

import math


def evaluate_pullback(hourly, ema20, atr, rsi):
    """Return a transparent decision for a confirmed 1h pullback/reclaim.

    Caller must independently require hourly EMA trend, daily EMA200, and
    validated volatility. Earlier hours are never read from the future.
    """
    failed = []
    evidence = {
        "pullback_touched_ema20": False,
        "prior_close_near_ema20": False,
        "reclaim_confirmed": False,
        "not_extended": False,
        "rsi_continuation_range": False,
        "positive_reported_volume": False,
    }
    if len(hourly) < 21 or not all(math.isfinite(float(x)) and float(x) > 0
                                  for x in (ema20, atr, rsi)):
        return {"passed": False, "checks": evidence}
    last, prior = hourly[-1], hourly[-2]
    close, previous = float(last["c"]), float(prior["c"])
    k = 2.0 / 21.0
    previous_ema20 = (float(ema20) - k * close) / (1 - k)
    e = previous_ema20
    for i in range(len(hourly) - 2, max(0, len(hourly) - 8), -1):
        bar = hourly[i]
        low, high = float(bar["l"]), float(bar["h"])
        if low <= e + 0.25 * atr and high >= e - 0.5 * atr:
            evidence["pullback_touched_ema20"] = True
        e = (e - k * float(bar["c"])) / (1 - k)

    evidence["prior_close_near_ema20"] = previous <= previous_ema20 + 0.5 * atr
    evidence["reclaim_confirmed"] = (
        close > float(ema20)
        and close > previous + 0.15 * atr
        and close >= float(last["o"])
        and close >= float(prior["h"]) - 0.25 * atr
    )
    evidence["not_extended"] = (
        0 < close - float(ema20) <= min(1.0 * atr, 0.025 * close)
    )
    evidence["rsi_continuation_range"] = 50 <= rsi <= 68
    evidence["positive_reported_volume"] = float(last["v"]) > 0
    return {"passed": all(evidence.values()), "checks": evidence}
