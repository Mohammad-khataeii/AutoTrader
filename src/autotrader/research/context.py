"""Completed UTC 15m/1h joins for 5m experiments, shared by replay and worker."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from autotrader.domain import Candle
from autotrader.indicators import _bollinger, _ema


def completed_context(candles: list[Candle], as_of: datetime) -> dict[str, Any]:
    # Reject duplicates/mixed feeds; never silently turn a gap into a full bar.
    ordered = sorted(candles, key=lambda c: c.timestamp)
    if len({c.timestamp for c in ordered}) != len(ordered) or len({c.symbol for c in ordered}) > 1:
        raise ValueError("ambiguous_context_feed")
    ordered = [c for c in ordered if c.timestamp + timedelta(minutes=5) <= as_of]
    if any(c.timeframe != "5m" for c in ordered):
        return {"ready": False, "reason": "experimental_primary_timeframe_requires_5m"}
    result: dict[str, Any] = {"as_of": as_of.isoformat()}
    for minutes in (15, 60):
        seconds = minutes * 60
        groups: dict[int, list[Candle]] = defaultdict(list)
        for candle in ordered:
            groups[int(candle.timestamp.timestamp()) // seconds * seconds].append(candle)
        aggregated = []
        for bucket, members in sorted(groups.items()):
            if bucket + seconds > as_of.timestamp():
                continue
            if [int(c.timestamp.timestamp()) for c in members] != list(
                range(bucket, bucket + seconds, 300)
            ):
                continue
            # Only complete group close and timestamp enter the EMA trend.
            # Avoid recomputing unused OHLCV indicators for every 5m join.
            aggregated.append((datetime.fromtimestamp(bucket, UTC), members[-1].close))
        fresh = bool(
            aggregated
            and as_of - aggregated[-1][0] - timedelta(seconds=seconds)
            < timedelta(seconds=seconds)
        )
        continuous = all(
            (b[0] - a[0]).total_seconds() == seconds
            for a, b in zip(aggregated[-50:-1], aggregated[-49:])
        )
        ready = len(aggregated) >= 50 and fresh and continuous
        closes = [c[1] for c in aggregated[-60:]]
        ema21 = _ema(closes, 21) if ready else None
        ema50 = _ema(closes, 50) if ready else None
        result[f"{minutes}m"] = {
            "ready": ready,
            "complete_bars": len(aggregated),
            "available_at": (aggregated[-1][0] + timedelta(seconds=seconds)).isoformat()
            if aggregated
            else None,
            "bull": bool(
                ema21 and ema50 and aggregated[-1][1] >= ema21 > ema50
            ),
            "bear": bool(
                ema21 and ema50 and aggregated[-1][1] < ema21 < ema50
            ),
        }
    result["ready"] = all(result[k]["ready"] for k in ("15m", "60m"))
    if len(ordered) >= 22:
        bands = _bollinger([c.close for c in ordered[-22:-2]])
        result["prebreak_width"] = (
            str((bands[0] - bands[2]) / bands[1]) if bands and bands[1] else "1"
        )
        reference = sum((c.volume for c in ordered[-22:-2]), Decimal(0)) / 20
        result["breakout_relative_volume"] = (
            str(ordered[-2].volume / reference) if reference else "0"
        )
        result["current_volume"] = str(ordered[-1].volume)
        result["previous_volume"] = str(ordered[-2].volume)
        result["previous_high"] = str(ordered[-2].high)
        result["last_open"] = str(ordered[-1].open)
    return result
