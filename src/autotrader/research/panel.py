from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from autotrader.clock import at
from autotrader.domain import Candle, DataQuality, MarketFeatures
from autotrader.indicators import calculate_features, higher_timeframe_context
from autotrader.research.data import TIMEFRAMES, HistoricalBar


def build_panel(bars: list[HistoricalBar], *, experimental_context: bool = False) -> tuple[dict[datetime, list[Candle]], dict[datetime, dict[str, MarketFeatures]], dict[str, Any]]:
    frames: dict[datetime, list[Candle]] = defaultdict(list)
    flags = {(bar.symbol, bar.start): bar.quality_flags for bar in bars}
    for bar in bars:
        candle = bar.candle()
        frames[candle.timestamp].append(candle)
    histories: dict[str, list[Candle]] = defaultdict(list)
    features: dict[datetime, dict[str, MarketFeatures]] = {}
    for timestamp, frame in sorted(frames.items()):
        seconds = TIMEFRAMES[frame[0].timeframe]
        available_at = timestamp + timedelta(seconds=seconds)
        current = {}
        for candle in sorted(frame, key=lambda c: c.symbol):
            history = histories[candle.symbol]
            history.append(candle)
            if len(history) > (720 if experimental_context else 240):
                history.pop(0)
            if len(history) < 50:
                continue
            f = calculate_features(history[-240:], Decimal(0), Decimal(10))
            # Full-range quality is knowable only at this candle's close. Never
            # remove the current open/execution event using its later high/low.
            if "SUSPICIOUS_RANGE" in flags[(candle.symbol, candle.timestamp.isoformat())]:
                f = replace(f, data_quality=DataQuality.INVALID)
                f.metadata["quality_review_required"] = "completed_suspicious_range"
            f.metadata.update({"available_at": available_at.isoformat(),
                "_feature_timestamp": candle.timestamp.isoformat(),
                "history_contiguous": all((right.timestamp - left.timestamp).total_seconds() == seconds for left, right in zip(history[-50:-1], history[-49:], strict=True)),
                "last_price": candle.close, "historical_spread_assumption_bps": "10"})
            # Existing confirmation expects a minute label; preserve values and
            # actual UTC duration while normalizing only that parser boundary.
            normalized = [Candle(c.symbol, c.timestamp, c.open, c.high, c.low, c.close, c.volume,
                timeframe=f"{seconds // 60}m", source=c.source) for c in history[-240:]]
            with at(available_at):
                f.metadata["higher_timeframe_confirmation"] = higher_timeframe_context(normalized)
            if experimental_context:
                from autotrader.research.context import completed_context
                f.metadata["experimental_context"] = completed_context(history, available_at)
            current[candle.symbol] = f
        features[available_at] = current
    return dict(frames), features, {"feature_version": "v4-completed-240", "history_window": 240,
        "warmup_bars": 50, "higher_timeframe_minimum": "50 complete four-bar groups", "gap_policy": "last 50 primary bars must be contiguous"}
