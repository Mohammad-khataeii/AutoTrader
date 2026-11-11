"""Causal crypto midpoint-bar hygiene without altering raw historical evidence."""
from __future__ import annotations
import math

def quarantine_untraded_spikes(hourly, *, min_bars=220, max_bars=260):
    """Drop only demonstrably untraded quote CLOSE spikes from indicator input.

    A bogus close can distort the 200-hour EMA for days; it must not silently
    veto every later genuine setup. Recent zero-volume bogus WICKS still block
    entry because they contaminate breakout/ATR. If data becomes insufficient,
    block instead of fabricating a trade price or candle.
    """
    source=hourly[-max_bars:]
    cleaned=[]
    bad=[]
    for index,bar in enumerate(source):
        try:
            o,h,l,c,v=(float(bar[k]) for k in ("o","h","l","c","v"))
            if not all(math.isfinite(x) for x in (o,h,l,c,v)):
                return [], {"reason":"nonfinite_candle","bar_at":bar.get("ts")}
            if min(o,h,l,c)<=0 or v<0 or h<max(o,c,l) or l>min(o,c,h):
                return [], {"reason":"invalid_candle","bar_at":bar.get("ts")}
            bogus_close=(v==0 and abs(c/o-1)>0.08)
            bogus_wick=(v==0 and h/l-1>0.12)
            if bogus_close:
                bad.append(bar.get("ts"))
                if index >= len(source)-21:
                    return [], {"reason":"recent_untraded_close_spike","bar_at":bar.get("ts")}
                continue
            if bogus_wick and index>=len(source)-21:
                return [], {"reason":"recent_untraded_wick_spike","bar_at":bar.get("ts")}
            cleaned.append(bar)
        except (KeyError,TypeError,ValueError,ZeroDivisionError,OverflowError):
            return [], {"reason":"invalid_candle","bar_at":bar.get("ts")}
    if len(cleaned)<min_bars:
        return [], {"reason":"insufficient_clean_hourly_bars","quarantined":len(bad)}
    return cleaned, {"reason":"OK","quarantined":len(bad),"quarantined_at":bad[-5:]}
