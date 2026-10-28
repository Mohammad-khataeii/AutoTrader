"""Completed-bar dimensions, independent asset and BTC/ETH context."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any

from autotrader.domain import Candle
from autotrader.indicators import _ema

D = Decimal


def aggregate(candles: list[Candle], minutes: int, as_of: datetime) -> list[Candle]:
    if minutes not in (5, 15, 60, 240):
        raise ValueError("unsupported_raoe_timeframe")
    groups: dict[int, list[Candle]] = defaultdict(list)
    for c in candles:
        if c.timeframe == '5m' and c.timestamp + timedelta(minutes=5) <= as_of:
            groups[int(c.timestamp.timestamp()) // (minutes*60) * minutes*60].append(c)
    result = []
    for stamp, rows in sorted(groups.items()):
        rows.sort(key=lambda c: c.timestamp)
        if (stamp+minutes*60 > as_of.timestamp()
                or [int(c.timestamp.timestamp()) for c in rows] != list(range(stamp, stamp+minutes*60, 300))
                or len({c.symbol for c in rows}) != 1):
            continue
        result.append(Candle(rows[0].symbol, datetime.fromtimestamp(stamp, tz=as_of.tzinfo),
            rows[0].open, max(c.high for c in rows), min(c.low for c in rows), rows[-1].close,
            sum((c.volume for c in rows), D(0)), f'{minutes}m', rows[-1].source))
    return result


def atr(candles: list[Candle]) -> Decimal:
    ranges = [max(b.high-b.low, abs(b.high-a.close), abs(b.low-a.close)) for a, b in pairwise(candles[-15:])]
    return sum(ranges, D(0))/len(ranges) if ranges else D(0)


def dimension(candles: list[Candle]) -> dict[str, Any]:
    if len(candles) < 21:
        return {'trend': 'UNKNOWN', 'bars': len(candles)}
    e9, e21 = _ema([c.close for c in candles[-60:]], 9), _ema([c.close for c in candles[-60:]], 21)
    assert e9 is not None and e21 is not None
    return {'trend': 'BULLISH' if candles[-1].close > e9 > e21 else 'BEARISH' if candles[-1].close < e9 < e21 else 'RANGING',
        'bars': len(candles), 'ema9': str(e9), 'ema21': str(e21), 'atr': str(atr(candles)),
        'last_closed_at': candles[-1].timestamp.isoformat()}


def assess(candles: list[Candle], as_of: datetime, benchmarks: dict[str, list[Candle]] | None = None) -> dict[str, Any]:
    closed = aggregate(candles, 5, as_of)
    errors = []
    if len(closed) < 60 or len({c.symbol for c in candles}) != 1:
        errors.append('insufficient_same_asset_history')
    if any(b.timestamp-a.timestamp != timedelta(minutes=5) for a, b in pairwise(closed[-240:])):
        errors.append('gapped_completed_history')
    if not closed or not 0 <= (as_of-closed[-1].timestamp-timedelta(minutes=5)).total_seconds() <= 300:
        errors.append('stale_completed_history')
    if len({c.timestamp for c in candles if c.timestamp+timedelta(minutes=5)<=as_of}) != len([c for c in candles if c.timestamp+timedelta(minutes=5)<=as_of]):
        errors.append('duplicate_candle_history')
    timeframes = {str(m): dimension(aggregate(candles, m, as_of)) for m in (5, 15, 60, 240)}
    peers = {}
    asset_return = closed[-1].close/closed[-7].close-1 if len(closed)>=7 else None
    for name in ('BTC-EUR', 'ETH-EUR'):
        bars = aggregate((benchmarks or {}).get(name, []), 5, as_of)
        if len(bars)>=21 and closed and bars[-1].timestamp==closed[-1].timestamp and all(b.timestamp-a.timestamp==timedelta(minutes=5) for a,b in pairwise(bars[-21:])):
            peers[name] = {**dimension(bars), 'return_30m': str(bars[-1].close/bars[-7].close-1)}
    broad = 'UNKNOWN' if len(peers)<2 else 'RISK_OFF' if all(p['trend']=='BEARISH' for p in peers.values()) else 'SUPPORTIVE' if all(p['trend']=='BULLISH' for p in peers.values()) else 'MIXED'
    distance = atr(closed)
    impulse = bool(len(closed)>=4 and closed[-1].close>closed[-2].close>closed[-3].close
        and closed[-1].low>closed[-3].low and closed[-1].close>closed[-1].open)
    expansion = bool(distance and closed and closed[-1].high-closed[-1].low > D('1.5')*distance)
    labels = []
    if impulse and timeframes['60']['trend']!='BULLISH': labels.append('EMERGING_BULLISH_RECOVERY')
    if timeframes['15']['trend']=='BULLISH': labels.append('ESTABLISHED_BULLISH_TREND')
    if timeframes['5']['trend']=='RANGING': labels.append('SIDEWAYS_RANGING')
    if expansion: labels.append('VOLATILITY_EXPANSION')
    if broad=='RISK_OFF' or timeframes['5']['trend']=='BEARISH': labels.append('BEARISH_RISK_OFF')
    return {'version': 'raoe-regime/1', 'as_of': as_of.isoformat(), 'ready': not errors,
        'errors': errors, 'labels': labels or ['UNKNOWN'], 'timeframes': timeframes,
        'impulse': impulse, 'volatility': 'EXPANDING' if expansion else 'NORMAL' if distance else 'UNKNOWN',
        'atr': str(distance), 'benchmark': broad, 'benchmarks': peers,
        'relative_return_30m': str(asset_return-sum((D(p['return_30m']) for p in peers.values()), D(0))/len(peers)) if asset_return is not None and peers else None,
        'volume_evidence': 'Public mid-price OHLCV; volume is not assumed to be executed demand',
        'completed_at': (closed[-1].timestamp+timedelta(minutes=5)).isoformat() if closed else None}
