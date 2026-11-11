"""Separate causal, long-only post-selloff recovery candidate.

Research by default. This module cannot submit paper/live orders. Candidate
scoring only uses completed, non-quarantined hourly candles.
"""
from __future__ import annotations
import math

def assess(hourly, atr, rsi):
    checks={"meaningful_prior_selloff":False,"two_rising_closes":False,
            "positive_trade_volume":False,"recovered_short_average":False,
            "not_chasing_rebound":False,"rsi_recovers":False}
    if len(hourly)<24 or not math.isfinite(float(atr)) or atr<=0:
        return {"passed":False,"checks":checks}
    prices=[float(b["c"]) for b in hourly[-24:]]
    vols=[float(b["v"]) for b in hourly[-4:]]
    close=prices[-1]
    low=min(float(b["l"]) for b in hourly[-12:])
    peak=max(float(b["h"]) for b in hourly[-24:-4])
    short_avg=sum(prices[-6:])/6
    checks["meaningful_prior_selloff"]=(peak-low)/peak>=0.025 and peak-low>=2*atr
    checks["two_rising_closes"]=prices[-1]>prices[-2]>prices[-3]
    checks["positive_trade_volume"]=vols[-1]>0 and vols[-2]>0 and sum(v>0 for v in vols)>=3
    checks["recovered_short_average"]=close>short_avg
    checks["not_chasing_rebound"]=0.35*atr<=close-low<=2.25*atr
    checks["rsi_recovers"]=43<=rsi<=64
    return {"passed":all(checks.values()),"checks":checks}
