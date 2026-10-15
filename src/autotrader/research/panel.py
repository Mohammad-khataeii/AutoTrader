from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from autotrader.clock import at
from autotrader.domain import Candle, MarketFeatures
from autotrader.indicators import calculate_features, higher_timeframe_context
from autotrader.research.data import TIMEFRAMES, HistoricalBar


def build_panel(bars: list[HistoricalBar]) -> tuple[dict[datetime, list[Candle]], dict[datetime, dict[str, MarketFeatures]], dict[str, Any]]:
    frames: dict[datetime, list[Candle]] = defaultdict(list)
    for bar in bars:
        if "SUSPICIOUS_RANGE" in bar.quality_flags:
            continue
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
            if len(history) > 240:
                history.pop(0)
            if len(history) < 50:
                continue
            f = calculate_features(history, Decimal(0), Decimal(10))
            f.metadata.update({"available_at": available_at.isoformat(),
                "_feature_timestamp": candle.timestamp.isoformat(),
                "history_contiguous": all((right.timestamp - left.timestamp).total_seconds() == seconds for left, right in zip(history[-50:-1], history[-49:], strict=True)),
                "last_price": candle.close, "historical_spread_assumption_bps": "10"})
            # Existing confirmation expects a minute label; preserve values and
            # actual UTC duration while normalizing only that parser boundary.
            normalized = [Candle(c.symbol, c.timestamp, c.open, c.high, c.low, c.close, c.volume,
                timeframe=f"{seconds // 60}m", source=c.source) for c in history]
            with at(available_at):
                f.metadata["higher_timeframe_confirmation"] = higher_timeframe_context(normalized)
            current[candle.symbol] = f
        features[available_at] = current
    return dict(frames), features, {"feature_version": "v4-completed-240", "history_window": 240,
        "warmup_bars": 50, "higher_timeframe_minimum": "50 complete four-bar groups", "gap_policy": "last 50 primary bars must be contiguous"}
