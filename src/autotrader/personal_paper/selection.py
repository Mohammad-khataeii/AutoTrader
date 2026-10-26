"""Fixed quality hypotheses, not estimated win probabilities or optimized winners."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

from autotrader.domain import MarketFeatures, StrategySignal
from autotrader.opportunity.regime import number

D = Decimal
QUALITY_GATES = {"review_benchmark_support", "review_bullish_continuation", "review_completed_hourly_trend",
    "review_target_within_overhead", "review_target_cost_headroom", "review_stop_above_noise"}
POLICY = {
    'version': '4.7.1-quality.1',
    'benchmark': 'SUPPORTIVE_OR_MIXED_SYNCHRONIZED',
    'trend': 'BULLISH; A3/E3 completed bullish 1h',
    'target': 'TP1 <= nearest observed 15m/1h overhead resistance',
    'minimum_target_net_to_roundtrip_cost': '2',
    'minimum_stop_distance_primary_atr': '1',
    'discretionary_exit': 'position-specific completed candles; two post-entry confirmations and completed 15m reversal',
    'ranking': 'conditional net reward/risk, reward/cost, strategy concentration; technical tie breaker',
    'expected_profitability': 'UNKNOWN',
    'approval': 'EXPERIMENTAL_PAPER_ONLY',
}


def reviewed_signal(signal: StrategySignal, f: MarketFeatures) -> StrategySignal:
    e = dict(signal.evidence)
    economics = (e.get('economics') or {}).get('measurements', {})
    higher = f.metadata.get('successor_context', {})
    assessment = e.get('regime_assessment', {})
    entry = number(economics.get('entry', {}).get('vwap')) or number(f.metadata.get('best_ask')) or number(f.metadata.get('last_close'))
    stop = number(e['entry_plan']['stop'])
    targets = [D(v) for v in e['entry_plan']['targets']]
    overhead = [v for tf in ('15m', '60m') if higher.get(tf, {}).get('ready')
                if (v := number(higher[tf].get('resistance'))) is not None and entry is not None and v > entry]
    # enrich names the hourly context "60m". Never substitute an incomplete bar.
    cost = number(economics.get('estimated_total_round_trip_cost_eur'))
    reward = number((economics.get('conditional_target_net_eur') or [None])[0])
    cost_ratio = reward / cost if reward is not None and cost is not None and cost > 0 else None
    stop_atr = (entry-stop)/f.atr if entry and stop and f.atr and f.atr > 0 else None
    gates = {
        'review_benchmark_support': assessment.get('benchmark') in {'SUPPORTIVE', 'MIXED'},
        'review_bullish_continuation': assessment.get('trend') in {'STRONG_BULLISH', 'MODERATE_BULLISH'},
        'review_completed_hourly_trend': signal.strategy_id.startswith('B3') or bool(higher.get('60m', {}).get('ready') and higher['60m'].get('bull')),
        'review_target_within_overhead': bool(targets and overhead and targets[0] <= min(overhead)),
        'review_target_cost_headroom': cost_ratio is not None and cost_ratio >= 2,
        'review_stop_above_noise': stop_atr is not None and stop_atr >= 1,
    }
    failed = [k for k, passed in gates.items() if not passed]
    e['quality_policy'] = {'version': POLICY['version'], 'gates': gates,
        'nearest_overhead': str(min(overhead)) if overhead else None,
        'target_net_to_roundtrip_cost': str(cost_ratio) if cost_ratio is not None else None,
        'stop_distance_atr': str(stop_atr) if stop_atr is not None else None,
        'as_of': f.timestamp.isoformat(), 'predictive_edge': 'UNKNOWN'}
    e['reasons'] = list(dict.fromkeys([*e['reasons'], *failed]))
    e['entry_eligible'] = bool(e['entry_eligible'] and not failed)
    e['qualified'] = e['entry_eligible']
    e['pipeline'] = [*e['pipeline'], {'stage': 'QUALITY_POLICY', 'reached': bool(e['technical_eligible']),
        'passed': not failed, 'reason': ','.join(failed) or 'fixed_quality_hypotheses_passed'}]
    e['qualification_state'] = 'PAPER_ELIGIBLE_EDGE_UNKNOWN' if e['entry_eligible'] else 'QUALITY_OR_SETUP_BLOCKED'
    return replace(signal, evidence=e)


def ranking(signal: StrategySignal, strategy_committed: Decimal = D(0), strategy_capital: Decimal = D(2100)) -> tuple[Any, ...]:
    e = signal.evidence
    measures = (e.get('economics') or {}).get('measurements', {})
    rr = number(measures.get('net_reward_risk')) or D(0)
    headroom = number(e.get('quality_policy', {}).get('target_net_to_roundtrip_cost')) or D(0)
    fit = max(D(0), 1-strategy_committed/strategy_capital)
    quality = min(rr, D(10))*min(headroom, D(10))*fit
    e['ranking_components'] = {'conditional_net_reward_risk': str(rr), 'target_net_to_cost': str(headroom),
        'strategy_committed_eur': str(strategy_committed), 'portfolio_fit': str(fit),
        'quality_product': str(quality), 'technical_tie_breaker': str(signal.score),
        'expected_profitability': 'UNKNOWN', 'probability': None}
    return (not e['entry_eligible'], -quality, -signal.score, signal.symbol, signal.strategy_id)
