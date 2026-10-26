"""Discretionary exits use the position's plan and completed observations only.

Protective bid stops, emergency controls and time expiry run independently first.
Missing context declines a discretionary exit; it never disables protection.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from autotrader.domain import Candle, DataQuality
from autotrader.indicators import calculate_features
from autotrader.opportunity.features import enrich
from autotrader.opportunity.regime import assess_regime, number
from autotrader.personal_paper.selection import POLICY
from autotrader.research.data import canonical, digest

D = Decimal


def assess_exit(strategy: str, opened_at: datetime, entry_evidence: dict[str, Any],
                candles: list[Candle], as_of: datetime, *, genuine: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {'policy': POLICY['version'], 'strategy_id': strategy,
        'as_of': as_of.isoformat(), 'reason': None, 'status': 'INSUFFICIENT_CONTEXT',
        'entry_as_of': entry_evidence.get('as_of')}
    closed = sorted([c for c in candles if c.timeframe=='5m' and c.timestamp+timedelta(minutes=5)<=as_of], key=lambda c:c.timestamp)[-720:]
    if not closed or not 0 <= (as_of-closed[-1].timestamp-timedelta(minutes=5)).total_seconds() <= 300:
        result['status'] = 'STALE_OR_MISSING_COMPLETED_CONTEXT'
        return result
    if (len(closed)<151 or len({c.symbol for c in closed})!=1
            or any(b.timestamp-a.timestamp != timedelta(minutes=5) for a,b in itertools.pairwise(closed))
            or (genuine and any(not c.source.startswith('revolut-x') for c in closed))):
        return result
    if strategy not in {'A3_COST_AWARE_CONTINUATION','B3_STATEFUL_BREAKOUT','E3_ADAPTIVE_RELATIVE_STRENGTH'}:
        result['status'] = 'UNKNOWN_ENTRY_STRATEGY'
        return result
    result['candle_at'] = closed[-1].timestamp.isoformat()
    result['data_hash'] = digest(canonical([[c.timestamp.isoformat(), str(c.open), str(c.high), str(c.low), str(c.close), str(c.volume), c.source] for c in closed]))
    f = enrich(calculate_features(closed), closed, as_of)
    prior = calculate_features(closed[:-1])
    post_entry = closed[-2].timestamp >= opened_at
    def bearish(feature: Any) -> bool:
        close = number(feature.metadata.get('last_close'))
        return bool(feature.data_quality is DataQuality.GOOD and feature.ema_21 and feature.ema_50
                    and close and close < feature.ema_21 < feature.ema_50)
    h15 = f.metadata['successor_context']['15m']
    reversal = bool(post_entry and bearish(f) and bearish(prior) and h15.get('ready') and h15.get('bear'))
    level = number((entry_evidence.get('pattern_state') or {}).get('level'))
    failed = bool(strategy.startswith('B3') and post_entry and level and f.atr and
                  all(c.close < level-D('.25')*f.atr for c in closed[-2:]))
    result.update(status='ASSESSED', local_trend=assess_regime(f).trend,
        higher_15m=h15, two_post_entry_bars=post_entry, confirmed_reversal=reversal,
        entry_breakout_level=str(level) if level is not None else None, failed_entry_breakout=failed,
        reason='failed_breakout' if failed else 'regime_exit' if reversal else None)
    return result
