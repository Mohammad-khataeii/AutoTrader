"""Decision-time provenance and descriptive research; never an order authority."""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from autotrader.perpetuals.market import Bar, MINUTE
from autotrader.perpetuals.multi.policy import D, FEE, SLIP, digest

SCHEMA = 'multi-decision-evidence/2'


def category(signal: dict[str, Any], reason: str) -> str:
    if signal.get('reasons'):
        return 'TECHNICALLY_INVALID'
    if any(word in reason for word in ('stale', 'depth', 'data_unavailable', 'mark', 'quote')):
        return 'DATA_QUALITY'
    if any(word in reason for word in ('paused', 'halted', 'exposure', 'margin', 'risk_cap', 'position_cap', 'collateral')):
        return 'RISK_OR_CONTROL'
    if any(word in reason for word in ('target', 'reward', 'cost', 'noise', 'funding', 'liquidation')):
        return 'UNECONOMIC_OR_UNSAFE'
    if reason == 'research_only_no_entry_authority':
        return 'RESEARCH_ONLY'
    if 'another_strategy' in reason:
        return 'ALTERNATIVE_SELECTED'
    return 'EXECUTION_UNOBSERVABLE'


def decision(signal: dict[str, Any], state: dict[str, Any], reason: str, *, admitted: bool = False) -> dict[str, Any]:
    """Capture control state under the ledger lock; missing observations stay unknown."""
    context = signal.get('decision_context', {})
    return {'schema': SCHEMA, 'group': 'ADMITTED_INTENT' if admitted else category(signal, reason),
            'decision_at': signal['decision_at'], 'available_data_cutoff': signal['cutoff'],
            'entries_enabled': state['entries_enabled'], 'admitted': admitted,
            'fill_established': False, 'reason': reason,
            'contract_hash': context.get('contract_hash'),
            'executable_quote_available': context.get('executable_quote_available'),
            'quote': context.get('quote'), 'cohort_qualification': context.get('cohorts', []),
            'risk_constraints': {'cohorts_halted': {k: a['halted'] for k, a in state['accounts'].items()},
                                 'matched_admission': 'ALL_COHORTS_MUST_PASS_NO_RISK_INCREASE'},
            'success_probability': None, 'expected_net_profit': None, 'confidence': 'UNKNOWN'}


def feature_snapshot(f) -> dict[str, Any]:
    return {'cutoff': f.cutoff, 'known_at': f.known_at, 'reference': f.reference,
            'atr_fraction': f.atr_fraction, 'relative_volume': f.volume_ratio,
            'acceleration': f.acceleration, 'persistence': f.persistence,
            'momentum_3m': f.momentum_3m, 'momentum_5m': f.momentum_5m,
            'expansion': f.expansion, 'efficiency': f.efficiency, 'regime': f.regime,
            'ranges': {str(n): (max(b.high for b in f.one[-n:])-min(b.low for b in f.one[-n:]))/f.reference
                       for n in (1, 3, 5)}, 'source_hash': f.source_hash,
            'source': 'COMPLETED_LAST_TRADE_CANDLES'}


def candle_review(signal: dict[str, Any], bars: dict[int, Bar], *, now: int,
                  mark: dict[int, Bar] | None = None, funding: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Exclude the partial decision minute. Unknown intrabar order is stop-first.

    The proxy is per unit notional, not a fill, and excludes unobserved depth.
    Historical funding needs an explicit complete list (including an empty list).
    """
    begin = (signal['decision_at']+MINUTE-1)//MINUTE*MINUTE
    finish = (signal['decision_at']+signal['hold_minutes']*MINUTE)//MINUTE*MINUTE
    if signal['cutoff'] > signal['decision_at'] or now < finish or begin >= finish:
        raise ValueError('review_not_due_or_invalid_cutoff')
    window = [bars[t] for t in range(begin, finish, MINUTE)]
    if any(b.start != t for b, t in zip(window, range(begin, finish, MINUTE))):
        raise ValueError('review_candle_identity_mismatch')
    side, reference, target, stop = signal['side'], D(signal['reference']), D(signal['target']), D(signal['stop'])
    if side not in (-1, 1) or reference <= 0:
        raise ValueError('invalid_review_signal')
    for bar in window:
        if (any(not v.is_finite() or v <= 0 for v in (bar.open, bar.high, bar.low, bar.close))
                or not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high):
            raise ValueError('invalid_review_bar')
    first, ambiguous, exit_price, hit_at = 'TIME', False, window[-1].close, finish
    observed_path = []
    for bar in window:
        observed_path.append(bar)
        favorable, adverse = (bar.high, bar.low) if side == 1 else (bar.low, bar.high)
        t, s = side*(favorable-target) >= 0, side*(adverse-stop) <= 0
        if t or s:
            first, ambiguous, hit_at = 'STOP' if s else 'TARGET', t and s, bar.start+MINUTE
            # A gap beyond the stop is worse than the planned barrier.
            exit_price = min(stop, bar.open) if s and side == 1 else max(stop, bar.open) if s else target
            break
    gross = side*(exit_price/reference-1)
    # Fees/slippage are applied once to stressed prices, with separately named
    # unavailable spread/depth. This remains an incomplete cost proxy.
    entry_proxy, exit_proxy = reference*(1+side*SLIP), exit_price*(1-side*SLIP)
    proxy = (side*(exit_proxy-entry_proxy)-FEE*(entry_proxy+exit_proxy))/reference
    funding_fraction = None
    if funding is not None:
        if len({int(r['at']) for r in funding}) != len(funding):
            raise ValueError('duplicate_historical_funding_event')
        if any(not D(str(r['rate'])).is_finite() or not D(str(r['mark'])).is_finite()
               or D(str(r['mark'])) <= 0 for r in funding):
            raise ValueError('invalid_historical_funding_event')
        relevant = [r for r in funding if signal['decision_at'] < int(r['at']) <= hit_at]
        funding_fraction = sum((-side*D(str(r['rate']))*D(str(r['mark']))/reference for r in relevant), D(0))
        proxy += funding_fraction
    mae = max(D(0), max(-side*((b.low if side == 1 else b.high)/reference-1) for b in observed_path))
    mfe = max(D(0), max(side*((b.high if side == 1 else b.low)/reference-1) for b in observed_path))
    group = signal.get('decision', {}).get('group', 'LEGACY_CONTEXT_UNKNOWN')
    tags = []
    if group == 'DATA_QUALITY': tags.append('DATA_QUALITY_FAILURE')
    if group == 'RISK_OR_CONTROL': tags.append('RISK_BASED_REJECTION')
    reasons = ';'.join(signal.get('reasons', []))
    if 'extended' in reasons or 'late' in reasons: tags.append('LATE_SIGNAL_HYPOTHESIS')
    if first == 'STOP': tags.append('ASSUMPTION_NOT_SUPPORTED_STOP_FIRST')
    if first == 'STOP' and 'BREAK' in signal['policy']: tags.append('FALSE_BREAKOUT_HYPOTHESIS')
    if first == 'TIME': tags.append('INSUFFICIENT_FOLLOW_THROUGH')
    if gross > 0 and proxy <= 0: tags.append('COST_DESTROYED_PROXY')
    if first == 'TARGET' and group not in ('TECHNICALLY_INVALID', 'ADMITTED_INTENT'):
        tags.append('POTENTIALLY_INTERESTING_REJECTED_SETUP')
    tags.append('EXECUTION_OUTCOME_UNOBSERVABLE')
    mark_window = [mark.get(t) for t in range(begin, finish, MINUTE)] if mark is not None else []
    mark_complete = bool(mark_window) and all(b is not None for b in mark_window)
    if mark_complete and any(b.start != t or any(not v.is_finite() or v <= 0 for v in (b.open, b.high, b.low, b.close))
                             or not b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
                             for b, t in zip(mark_window, range(begin, finish, MINUTE))):
        raise ValueError('invalid_mark_review_window')
    return {'schema': 'multi-candle-review/2', 'hypothetical_no_fill': True,
            'decision_group': group, 'target_touched': first == 'TARGET' or ambiguous,
            'stop_touched': first == 'STOP', 'ambiguous_first_barrier': ambiguous,
            'conservative_first_barrier': first, 'barrier_time_upper_bound_ms': hit_at,
            'time_to_target_ms': hit_at-signal['decision_at'] if first == 'TARGET' else None,
            'time_to_stop_ms': hit_at-signal['decision_at'] if first == 'STOP' else None,
            'signed_horizon_move_pct': side*(window[-1].close/reference-1)*100,
            'gross_barrier_or_time_fraction': gross, 'mfe_fraction': mfe, 'mae_fraction': mae,
            'excursions_scope': 'THROUGH_EXIT_CANDLE_INCLUSIVE_INTRABAR_ORDER_UNKNOWN',
            'cost_stressed_no_fill_proxy_fraction': proxy, 'funding_fraction': funding_fraction,
            'cost_provenance': {'fee_per_side': FEE, 'residual_slippage_per_side': SLIP,
                                'historical_spread': None, 'historical_depth_impact': None,
                                'latency_execution': None, 'funding_complete': funding is not None},
            'last_source_hash': digest([[b.start, b.open, b.high, b.low, b.close] for b in window]),
            'mark_source_hash': digest([[b.start, b.open, b.high, b.low, b.close] for b in mark_window]) if mark_complete else None,
            'mark_price_coverage': 'COMPLETE' if mark_complete else 'UNKNOWN',
            'mark_mae_fraction': max(D(0), max(-side*((b.low if side == 1 else b.high)/reference-1) for b in mark_window)) if mark_complete else None,
            'interpretations': tags, 'correct_rejection': None, 'missed_profitable_trade': None,
            'positive_executable_return_proven': False, 'regime_correct': None}


def realized_distribution(events: list[dict[str, Any]], *, minimum_days: int = 20,
                          minimum_samples: int = 30) -> list[dict[str, Any]]:
    """Descriptive closed-paper distributions, split by cohort and calendar month.

    Daily clusters capture overlapping/correlated same-day trades conservatively.
    Intervals describe historical daily mean net/trade, not success probabilities.
    """
    from datetime import UTC, datetime
    groups = defaultdict(list)
    seen = set()
    for event in events:
        if event.get('kind') != 'EXIT_SETTLED' or event['event_key'] in seen:
            continue
        seen.add(event['event_key'])
        p = event['position']; s = p['signal']
        month = datetime.fromtimestamp(event['at']/1000, UTC).strftime('%Y-%m')
        key = (p['symbol'], s['policy'], p['side'], s['regime'], p['leverage'], month)
        groups[key].append(event)
    result = []
    for key, rows in sorted(groups.items()):
        rows.sort(key=lambda r: (r['at'], r['event_key']))
        values = [D(r['net']) for r in rows]  # Already net; never subtract costs again.
        wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
        daily = defaultdict(list)
        for r in rows: daily[r['at']//86_400_000].append(D(r['net']))
        means = [sum(v, D(0))/len(v) for v in daily.values()]
        interval = None
        if len(means) >= minimum_days and len(values) >= minimum_samples:
            mean = sum(means, D(0))/len(means)
            variance = sum(((v-mean)**2 for v in means), D(0))/(len(means)-1)
            half = D('1.96')*(variance/len(means)).sqrt()
            interval = [mean-half, mean+half]
        cumulative = peak = drawdown = D(0)
        for value in values:
            cumulative += value; peak = max(peak, cumulative); drawdown = max(drawdown, peak-cumulative)
        result.append({'symbol': key[0], 'policy': key[1], 'direction': key[2], 'regime': key[3],
                       'leverage': key[4], 'period': key[5], 'closed': len(values), 'independent_day_clusters': len(daily),
                       'net_per_trade': sum(values, D(0))/len(values), 'profit_factor': sum(wins, D(0))/-sum(losses, D(0)) if losses else None,
                       'win_loss_ratio': (sum(wins)/len(wins))/(-sum(losses)/len(losses)) if wins and losses else None,
                       'win_rate': D(len(wins))/len(values), 'max_closed_pnl_drawdown_usdt': drawdown,
                       'worst_net_trade': min(values), 'tail_5pct_mean': sum(sorted(values)[:max(1, len(values)//20)], D(0))/max(1, len(values)//20),
                       'daily_cluster_mean_interval_95_approx': interval,
                       'confidence': 'DESCRIPTIVE_ONLY' if interval else 'UNKNOWN',
                       'interval_assumption': 'Approximate normal daily clusters; serial dependence and selection bias remain',
                       'expected_future_net_profit': None, 'cohorts_are_independent': False})
    return result


def decision_counts(events: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(e.get('signal', {}).get('decision', {}).get('group', 'LEGACY_CONTEXT_UNKNOWN')
                     for e in events if e['kind'] in ('SIGNAL_REJECTED', 'RESEARCH_OBSERVED'))
    return {'groups': dict(counts), 'scope': 'Recent journal window only; not all-time totals',
            'realized_outcomes': sum(e['kind'] == 'EXIT_SETTLED' for e in events),
            'simulated_fills': sum(e['kind'] == 'ENTRY_FILLED' for e in events),
            'hypothetical_reviews': sum(e['kind'] == 'HYPOTHETICAL_FORECAST_REVIEW' for e in events)}
