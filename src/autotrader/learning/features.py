"""Features from immutable decision evidence, never from future outcome records."""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from autotrader.learning import FEATURE_SCHEMA
from autotrader.research.data import canonical, digest

STRATEGIES = ('A3_COST_AWARE_CONTINUATION', 'B3_STATEFUL_BREAKOUT',
              'E3_ADAPTIVE_RELATIVE_STRENGTH', 'RAOE_EARLY_RECOVERY',
              'RAOE_TREND_PULLBACK', 'RAOE_BREAKOUT_RETEST', 'RAOE_BREAKOUT_CONTINUATION')
NUMERIC = ('return_30m', 'relative_return_30m', 'atr_fraction', 'spread_bps',
           'volume_ratio', 'benchmark_return_30m', 'ema9_distance_atr',
           'stop_distance_atr', 'target_return', 'net_reward_risk', 'roundtrip_fraction',
           'extension_atr', 'log_near_liquidity', 'hour_sin', 'hour_cos', 'return_15m', 'asset_hour_ema_separation')
NAMES = (*NUMERIC, *(f'strategy:{s}' for s in STRATEGIES),
         'macro_risk_off', 'macro_mixed', 'asset_hour_bearish', 'asset_15m_bullish',
         'profile_v471', 'profile_v490', 'profile_v491', 'profile_v492')


def stamp(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    if t.tzinfo is None:
        raise ValueError('timezone_required')
    return t


def finite(value: Any) -> float:
    n = float(value)
    if not math.isfinite(n):
        raise ValueError('nonfinite_feature')
    return n


def build(e: dict[str, Any], strategy: str, observed_at: str) -> dict[str, Any]:
    """Saved evidence is authoritative; incomplete snapshots are not imputed bullish.

    A causal snapshot attests to the producing pipeline's data hash and completed
    cutoff. Retrospectively backfilled candles cannot repair missing entry inputs.
    """
    observed, candle = stamp(observed_at), stamp(e['as_of'])
    cutoff = candle + timedelta(minutes=5)
    if not cutoff <= observed < cutoff + timedelta(minutes=5):
        raise ValueError('stale_or_future_entry_snapshot')
    snapshot = e.get('learning_context') or {}
    source_hash = e.get('data_hash') or snapshot.get('data_hash')
    if not source_hash or strategy not in STRATEGIES:
        raise ValueError('unbound_feature_snapshot')
    r = e.get('raoe_regime') or snapshot.get('regime') or {}
    m = (e.get('economics') or {}).get('measurements') or {}
    entry_quote = m.get('entry') or {}
    plan = e['entry_plan']
    price, atr = finite(entry_quote['vwap']), finite(m.get('atr') or r['atr'])
    cost, stop, target = finite(m['cost_basis_eur']), finite(plan['stop']), finite(plan['targets'][0])
    if min(price, atr, cost, stop) <= 0 or not stop < price < target:
        raise ValueError('invalid_geometry')
    peers = r['benchmarks']
    if set(peers) != {'BTC-EUR', 'ETH-EUR'}:
        raise ValueError('missing_benchmark_features')
    for frame in [*r['timeframes'].values(), *peers.values()]:
        if frame.get('unknown_reason') or stamp(frame['last_closed_at']) > candle:
            raise ValueError('unavailable_context')
    returns = [finite(peers[s]['return_30m']) for s in ('BTC-EUR', 'ETH-EUR')]
    mean = sum(returns)/2
    relative = finite(r['relative_return_30m'])
    primary = (e.get('primary_admission') or {}).get('inputs') or {}
    # The RAOE regime carries the same completed EMA in isolated shadow evidence.
    ema = finite(primary.get('ema9') or r['timeframes']['5']['ema9'])
    close = finite(primary.get('close') or price)
    liquidity = r.get('near_liquidity') or {}
    # Missing volume is an explicit missingness indicator; public mid OHLCV is
    # not executed demand. Retained as zero plus a named missing-feature field.
    volume = (e.get('learning_context') or {}).get('volume_ratio')
    missing = ['volume_ratio'] if volume is None else []
    c15, p15 = primary.get('close15'), primary.get('previous_close15')
    if c15 is None or p15 is None:
        missing.append('return_15m')
    hour = r['timeframes']['60']
    values = [mean+relative, relative, atr/price, finite(entry_quote['spread_bps']),
              finite(volume) if volume is not None else 0., mean, (close-ema)/atr,
              (price-stop)/atr, target/price-1, finite(m['net_reward_risk']),
              finite(m['estimated_total_round_trip_cost_eur'])/cost,
              finite(e.get('pattern_state', {}).get('extension_atr', 0)),
              math.log1p(min(finite(liquidity.get('bid_quote', 0)), finite(liquidity.get('ask_quote', 0)))),
              math.sin(observed.hour*math.pi/12), math.cos(observed.hour*math.pi/12),
              finite(c15)/finite(p15)-1 if c15 and p15 else 0.,
              (finite(hour.get('ema9', ema))-finite(hour.get('ema21', ema)))/price]
    profile = str(e.get('execution_profile', ''))
    values += [float(strategy == s) for s in STRATEGIES]
    values += [float(r['benchmark'] == 'RISK_OFF'), float(r['benchmark'] == 'MIXED'),
               float(r['timeframes']['60']['trend'] == 'BEARISH'),
               float(r['timeframes']['15']['trend'] == 'BULLISH')]
    values += [float(profile.startswith(v)) for v in ('4.7.1', '4.9.0', '4.9.1', '4.9.2')]
    values = [finite(v) for v in values]
    return {'schema': FEATURE_SCHEMA, 'names': list(NAMES), 'values': values,
            'known_at': observed_at, 'completed_cutoff': cutoff.isoformat(),
            'source_data_hash': source_hash, 'source_evidence_hash': digest(canonical(e)),
            'missing_features': missing, 'source': 'IMMUTABLE_DECISION_SNAPSHOT',
            'profile': profile, 'strategy': strategy, 'regime': r['benchmark']}
