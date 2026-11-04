"""Reusable offline evidence adapters. Importing this module performs no IO.

Accepts the private V4.9.8 Bybit NDJSON envelope without retaining raw payloads.
Callers must provide data coverage explicitly; missing depth never becomes fills.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Iterable

from autotrader.perpetuals.market import Bar, MINUTE
from autotrader.perpetuals.multi.evidence import candle_review
from autotrader.perpetuals.multi.policy import D, digest


def reference_records(lines: Iterable[str]) -> dict[str, Any]:
    candles, metadata, funding, acquisition = {}, {}, {}, {}
    for line in lines:
        row = json.loads(line)
        response, symbol = row['response'], row['symbol']
        if not response.get('ok'):
            continue
        result = response['result']; params = row.get('params', {})
        if params.get('category') != 'linear' or params.get('symbol') != symbol:
            raise ValueError('historical_contract_identity_mismatch')
        acquired = datetime.fromisoformat(row['fetched_at_utc'].replace('Z', '+00:00'))
        if acquired.tzinfo is None: raise ValueError('historical_acquisition_timezone_required')
        known_at = int(acquired.timestamp()*1000)
        kind = row['kind']
        if kind == 'instrument_info':
            matches = [r for r in result['list'] if r['symbol'] == symbol]
            if len(matches) != 1:
                raise ValueError('historical_metadata_ambiguous')
            # Metadata fetched today is never claimed to be known historically.
            metadata[symbol] = {'value': matches[0], 'known_at': known_at, 'hash': digest(matches[0])}
        elif 'funding' in kind:
            bucket = funding.setdefault(symbol, {})
            for item in result['list']:
                stamp = int(item['fundingRateTimestamp'])
                rate = D(item['fundingRate'])
                if not rate.is_finite(): raise ValueError('invalid_historical_funding')
                if stamp in bucket and bucket[stamp] != rate: raise ValueError('conflicting_historical_funding')
                bucket[stamp] = rate
        elif str(params.get('interval')) == '1' and ('ohlcv' in kind or 'mark' in kind or 'kline' in kind):
            if result.get('symbol') != symbol or result.get('category') != 'linear':
                raise ValueError('historical_candle_identity_mismatch')
            price_type = 'MARK' if 'mark' in kind.lower() else 'LAST'
            bucket = candles.setdefault((symbol, price_type), {})
            for item in result['list']:
                stamp = int(item[0])
                if stamp % MINUTE: raise ValueError('unaligned_historical_candle')
                if stamp+MINUTE > known_at: continue  # Open acquisition candle.
                bar = Bar(stamp, *(D(v) for v in item[1:5]),
                          volume=D(item[5]) if price_type == 'LAST' and len(item)>5 else None)
                if (any(not v.is_finite() or v <= 0 for v in (bar.open, bar.high, bar.low, bar.close))
                        or not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
                        or bar.volume is not None and (not bar.volume.is_finite() or bar.volume < 0)):
                    raise ValueError('invalid_historical_candle')
                if stamp in bucket and bucket[stamp] != bar: raise ValueError('conflicting_historical_candle')
                bucket[stamp] = bar
                acquisition[(symbol, price_type, stamp)] = known_at
    return {'candles': candles, 'metadata': metadata, 'funding_rates': funding,
            'acquired_at': acquisition, 'funding_coverage_complete': False,
            'warning': 'Historical acquisition is retrospective evidence, never original decision availability'}


def evaluate(signal, dataset, *, now, funding_complete=False):
    """Evaluate frozen signals only; metadata stays retrospective when fetched later."""
    symbol = signal['symbol']; mark = dataset['candles'].get((symbol, 'MARK'))
    funding = None
    if funding_complete:
        funding = []
        for stamp, rate in dataset['funding_rates'].get(symbol, {}).items():
            if not signal['decision_at'] < stamp <= signal['decision_at']+signal['hold_minutes']*MINUTE:
                continue
            # At the boundary, only the preceding completed mark is available.
            bar = (mark or {}).get(stamp//MINUTE*MINUTE-MINUTE)
            if bar is None: raise ValueError('funding_mark_missing')
            funding.append({'at': stamp, 'rate': rate, 'mark': bar.close})
    outcome = candle_review(signal, dataset['candles'][(symbol, 'LAST')], now=now, mark=mark, funding=funding)
    metadata = dataset['metadata'].get(symbol)
    return {'signal_id': signal['id'], 'symbol': symbol, 'policy': signal['policy'],
            'direction': signal['side'], 'regime': signal['regime'],
            'decision_at': signal['decision_at'], 'cutoff': signal['cutoff'],
            'end_at': signal['decision_at']+signal['hold_minutes']*MINUTE,
            'feature_hash': signal['feature_hash'], 'frozen_signal_hash': digest(signal),
            'policy_hash': signal.get('evidence', {}).get('policy_hash'),
            'contract_metadata_hash': metadata['hash'] if metadata else None,
            'metadata_known_at_decision': bool(metadata and metadata['known_at'] <= signal['decision_at']),
            'execution_assumptions': signal.get('decision_context', {}), 'outcome': outcome}


def observation_summary(records):
    """Non-overlapping per-contract observations; markets remain correlated.

    Earliest decision wins, ordered by stable signal identity. Report exclusions
    and raw counts so overlap filtering cannot hide the selected population.
    """
    unique = {}
    for row in records:
        identity = row['signal_id']
        if identity in unique and unique[identity] != row:
            raise ValueError('conflicting_research_observation')
        unique[identity] = row
    accepted, until = [], {}
    for row in sorted(unique.values(), key=lambda r: (r['decision_at'], r['signal_id'])):
        # Do not count opposite-side or leverage versions of one market window
        # as additional independent opportunities.
        if row['decision_at'] < until.get(row['symbol'], 0): continue
        accepted.append(row); until[row['symbol']] = row['end_at']
    values = [D(str(r['outcome']['cost_stressed_no_fill_proxy_fraction'])) for r in accepted]
    gains, losses = [v for v in values if v>0], [v for v in values if v<0]
    cumulative = peak = drawdown = D(0)
    for value in values:
        cumulative += value; peak = max(peak, cumulative); drawdown = max(drawdown, peak-cumulative)
    return {'raw_observations': len(records), 'unique_signals': len(unique),
            'nonoverlapping_contract_windows': len(accepted), 'overlap_excluded': len(unique)-len(accepted),
            'descriptive_no_fill_proxy_mean_fraction': sum(values, D(0))/len(values) if values else None,
            'proxy_profit_factor': sum(gains, D(0))/-sum(losses, D(0)) if losses else None,
            'proxy_worst_fraction': min(values) if values else None,
            'proxy_cumulative_drawdown_fraction': drawdown if values else None,
            'barriers': dict(Counter(r['outcome']['conservative_first_barrier'] for r in accepted)),
            'decision_groups': dict(Counter(r['outcome']['decision_group'] for r in accepted)),
            'interpretations': dict(Counter(tag for r in accepted for tag in r['outcome']['interpretations'])),
            'mean_mfe_fraction': sum((D(str(r['outcome']['mfe_fraction'])) for r in accepted), D(0))/len(accepted) if accepted else None,
            'mean_mae_fraction': sum((D(str(r['outcome']['mae_fraction'])) for r in accepted), D(0))/len(accepted) if accepted else None,
            'correct_rejection_rate': None, 'missed_executable_profit': None,
            'inference': 'UNKNOWN', 'realized_pnl': None,
            'limitations': ['No historical depth fills', 'Cross-market correlation remains',
                           'Earliest-window selection is descriptive, not an independent sample',
                           'No inference of edge from selected rejected hypotheses']}


def compare_frozen(baseline, candidate):
    """Return new reports without changing either frozen set or old labels."""
    def groups(rows):
        grouped = defaultdict(list)
        for row in rows:
            # UTC day buckets permit stability comparisons without pooling eras.
            key = (row['symbol'], row['policy'], row['direction'], row['regime'], row['decision_at']//86_400_000)
            grouped[key].append(row)
        return [{'symbol': k[0], 'policy': k[1], 'direction': k[2], 'regime': k[3],
                 'utc_day': k[4], **observation_summary(v)} for k, v in sorted(grouped.items())]
    return {'schema': 'multi-frozen-comparison/2', 'baseline_hash': digest(baseline),
            'candidate_hash': digest(candidate), 'baseline': groups(baseline), 'candidate': groups(candidate),
            'conclusion': 'UNVALIDATED_DESCRIPTIVE_COMPARISON', 'automatic_promotion': False}
