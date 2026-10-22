"""Causal successor context; original indicator and frozen context functions remain intact."""
from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import pstdev
from typing import Any

from autotrader.domain import Candle, MarketFeatures
from autotrader.indicators import _ema

D = Decimal


def enrich(f: MarketFeatures, candles: list[Candle], as_of: datetime, *, cached_context: dict[str, Any] | None = None) -> MarketFeatures:
    closed = [c for c in candles if c.symbol == f.symbol and c.timestamp + timedelta(minutes=5) <= as_of]
    if not closed or closed[-1].timestamp != f.timestamp or any(b.timestamp - a.timestamp != timedelta(minutes=5) for a, b in itertools.pairwise(closed[-50:])):
        raise ValueError("successor_context_requires_contiguous_completed_5m_candles")
    metadata = dict(f.metadata)
    closes = [c.close for c in closed]
    for n in (5, 20, 60):
        metadata[f"return_{n}"] = str(closes[-1] / closes[-n - 1] - 1) if len(closes) > n else None
    returns = [b / a - 1 for a, b in zip(closes[-21:-1], closes[-20:])]
    metadata["return_volatility_20"] = str(pstdev(returns)) if len(returns) == 20 else None
    metadata["recent_returns"] = [str(v) for v in returns] if len(returns) == 20 else []
    context: dict[str, Any] = dict(cached_context or {})
    for minutes in (() if cached_context is not None else (15, 60)):
        groups: dict[int, list[Candle]] = defaultdict(list)
        for c in closed:
            groups[int(c.timestamp.timestamp()) // (minutes * 60) * minutes * 60].append(c)
        complete = [(bucket, cs) for bucket, cs in sorted(groups.items()) if bucket + minutes * 60 <= as_of.timestamp()
                    and [int(c.timestamp.timestamp()) for c in cs] == list(range(bucket, bucket + minutes * 60, 300))]
        continuous = all(b[0] - a[0] == minutes * 60 for a, b in zip(complete[-50:-1], complete[-49:]))
        ready = len(complete) >= 50 and continuous and as_of.timestamp() - complete[-1][0] - minutes * 60 < minutes * 60
        values = [cs[-1].close for _, cs in complete[-60:]]
        e21, e50 = _ema(values, 21) if ready else None, _ema(values, 50) if ready else None
        bars = complete[-15:]
        ranges = [max(max(c.high for c in cs) - min(c.low for c in cs),
                      abs(max(c.high for c in cs) - prior[-1].close), abs(min(c.low for c in cs) - prior[-1].close))
                  for (_, prior), (_, cs) in itertools.pairwise(bars)]
        context[f"{minutes}m"] = {"ready": ready, "available_at": datetime.fromtimestamp(complete[-1][0] + minutes * 60, tz=as_of.tzinfo).isoformat() if complete else None,
            "bull": bool(e21 and e50 and values[-1] >= e21 > e50), "bear": bool(e21 and e50 and values[-1] < e21 < e50),
            "atr": str(sum(ranges, D(0)) / len(ranges)) if ready and ranges else None,
            "resistance": str(max(c.high for _, cs in complete[-20:] for c in cs)) if ready else None}
    metadata["successor_context"] = context
    metadata["swing_low_5"] = str(min(c.low for c in closed[-5:]))
    metadata["prior_high_20"] = str(max(c.high for c in closed[-21:-1])) if len(closed)>20 else None
    metadata["previous_ema9_reclaim"] = bool(f.ema_9 and closed[-2].close <= f.ema_9 <= closed[-1].close) if len(closed)>1 else False
    metadata["last_open"] = str(closed[-1].open)
    return replace(f, metadata=metadata)
