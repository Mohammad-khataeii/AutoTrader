"""Primary-only causal context guard. Original shadow control recipes are unchanged."""
from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from autotrader.domain import Candle, StrategySignal, utc_now
from autotrader.indicators import _ema
from autotrader.market_data.synchronization import alignment, cutoff
from autotrader.raoe.regime import aggregate, dimension

D = Decimal
POLICY = {
    'version': '4.9.1-primary-admission.1',
    'scope': 'PRIMARY_ONLY_ORIGINAL_SHADOW_CONTROLS_UNCHANGED',
    'freshness': 'Current completed 5m candle at both locked admission and dispatch',
    'macro': 'No long when both completed BTC and ETH hourly EMA9/21 trends are bearish',
    'reaction': 'Completed asset close reclaims nonfalling EMA9',
    'recovery': 'Early recovery also reclaims completed 15m EMA21 with a rising close',
    'periods': {'micro_ema': 9, 'higher_ema': 21, 'benchmark_minutes': 60},
    'estimated_edge': 'UNKNOWN',
}
GATES = frozenset({'primary_context_ready', 'primary_current_candle', 'primary_macro_context',
                  'primary_local_reclaim', 'primary_recovery_reclaim'})


def number(value: Any) -> Decimal | None:
    try:
        n = D(str(value))
        return n if n.is_finite() and n > 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _stamp(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _valid(bars: list[Candle], genuine: bool) -> bool:
    return bool(bars) and all(
        all(v.is_finite() for v in (b.open, b.high, b.low, b.close, b.volume))
        and min(b.open, b.high, b.low, b.close) > 0 and b.volume >= 0
        and b.low <= b.open <= b.high and b.low <= b.close <= b.high
        and (not genuine or b.source.startswith('revolut-x')) for b in bars)


def completed_context(candles: list[Candle], benchmarks: dict[str, list[Candle]],
                      as_of: datetime, *, genuine: bool = True) -> dict[str, Any]:
    closed = aggregate(candles, 5, as_of)
    micro = closed[-61:]
    higher = aggregate(candles, 15, as_of)
    h15 = dimension(higher, 15, as_of)
    own_ready = bool(len(micro) == 61 and alignment(closed, as_of)['alignment_status'] == 'ALIGNED'
                     and all(b.timestamp-a.timestamp == timedelta(minutes=5) for a, b in itertools.pairwise(micro))
                     and len({b.symbol for b in candles}) == 1
                     and _valid(closed[-252:], genuine) and h15['unknown_reason'] is None)
    peers = {}
    for symbol in ('BTC-EUR', 'ETH-EUR'):
        raw = benchmarks.get(symbol, [])
        hourly = aggregate(raw, 60, as_of)
        d = dimension(hourly, 60, as_of)
        ready = (alignment(raw, as_of)['alignment_status'] == 'ALIGNED'
                 and d['unknown_reason'] is None and all(b.symbol == symbol for b in raw)
                 and _valid([b for b in raw if b.timestamp+timedelta(minutes=5) <= as_of][-264:], genuine))
        peers[symbol] = {'ready': bool(ready), 'trend': d['trend'] if ready else 'UNKNOWN',
                         'available_at': d['last_closed_at'], 'contiguous_bars': d['contiguous_bars']}
    ema = _ema([b.close for b in micro[-60:]], 9) if len(micro) >= 60 else None
    prior = _ema([b.close for b in micro[:-1]], 9) if len(micro) == 61 else None
    return {'ready': own_ready and all(p['ready'] for p in peers.values()), 'peers': peers,
            'close': str(micro[-1].close) if micro else None,
            'ema9': str(ema) if ema is not None else None,
            'previous_ema9': str(prior) if prior is not None else None,
            'close15': str(higher[-1].close) if higher else None,
            'previous_close15': str(higher[-2].close) if len(higher) > 1 else None,
            'ema21_15': h15.get('ema21'), 'higher_ready': h15['unknown_reason'] is None}


def checks(strategy: str, inputs: dict[str, Any], candle_at: Any, evaluation_cutoff: Any,
           now: datetime) -> dict[str, bool]:
    candle, reference = _stamp(candle_at), _stamp(evaluation_cutoff)
    current = bool(candle and reference and now.tzinfo is not None
                   and candle+timedelta(minutes=5) == reference == cutoff(now))
    raw_peers = inputs.get('peers')
    peers: dict[str, Any] = raw_peers if isinstance(raw_peers, dict) else {}
    known = all(isinstance(peers.get(s), dict) and peers[s].get('ready') is True
                and peers[s].get('trend') in {'BULLISH', 'BEARISH', 'RANGING'}
                for s in ('BTC-EUR', 'ETH-EUR'))
    ready = inputs.get('ready') is True and known
    joint_bear = known and all(peers[s]['trend'] == 'BEARISH' for s in ('BTC-EUR', 'ETH-EUR'))
    close, ema, prior = [number(inputs.get(k)) for k in ('close', 'ema9', 'previous_ema9')]
    reclaim = bool(close and ema and prior and close >= ema >= prior)
    c15, p15, e15 = [number(inputs.get(k)) for k in ('close15', 'previous_close15', 'ema21_15')]
    recovery = strategy != 'RAOE_EARLY_RECOVERY' or bool(
        inputs.get('higher_ready') is True and c15 and p15 and e15 and c15 >= e15 and c15 > p15)
    return {'primary_context_ready': ready, 'primary_current_candle': current,
            'primary_macro_context': known and not joint_bear, 'primary_local_reclaim': reclaim,
            'primary_recovery_reclaim': recovery}


def apply(signal: StrategySignal, inputs: dict[str, Any], as_of: datetime) -> StrategySignal:
    evidence = dict(signal.evidence)
    gates = checks(signal.strategy_id, inputs, signal.timestamp.isoformat(), as_of.isoformat(), utc_now())
    base = bool(evidence.get('entry_eligible'))
    evidence['primary_admission'] = {'version': POLICY['version'], 'policy': POLICY,
        'strategy_id': signal.strategy_id, 'candle_at': signal.timestamp.isoformat(),
        'evaluation_cutoff': as_of.isoformat(), 'inputs': inputs, 'gates': gates,
        'base_entry_eligible': base, 'estimated_edge': 'UNKNOWN'}
    failed = [k for k, passed in gates.items() if not passed]
    evidence['entry_eligible'] = evidence['qualified'] = base and not failed
    evidence['reasons'] = list(dict.fromkeys([*evidence.get('reasons', []), *failed]))
    if base and failed:
        evidence['qualification_state'] = 'PRIMARY_ADMISSION_BLOCKED'
    evidence['pipeline'] = [*evidence.get('pipeline', []), {'stage': 'PRIMARY_CONTEXT',
        'reached': base, 'passed': not failed if base else None, 'reason': ','.join(failed) or 'context_passed'}]
    return replace(signal, evidence=evidence)


def policy_error(strategy: str, evidence: dict[str, Any], now: datetime) -> str | None:
    proof = evidence.get('primary_admission')
    if not isinstance(proof, dict) or proof.get('version') != POLICY['version'] or proof.get('policy') != POLICY:
        return 'paper_primary_admission_required'
    if (proof.get('strategy_id') != strategy or proof.get('candle_at') != evidence.get('as_of')
            or not isinstance(proof.get('inputs'), dict)):
        return 'paper_primary_admission_identity_mismatch'
    gates = checks(strategy, proof['inputs'], proof.get('candle_at'), proof.get('evaluation_cutoff'), now)
    if not gates['primary_current_candle']:
        return 'paper_current_completed_candle_required'
    stored = proof.get('gates')
    if (not isinstance(stored, dict) or set(stored) != GATES or stored != gates
            or not all(v is True for v in stored.values())
            or not all(v is True for v in gates.values()) or proof.get('base_entry_eligible') is not True):
        return 'paper_primary_context_required'
    return None
