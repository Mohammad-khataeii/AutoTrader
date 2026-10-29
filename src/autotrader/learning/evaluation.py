"""Global nonoverlapping episodes, purged folds and single-use future holdouts."""
from __future__ import annotations

from datetime import timedelta
from statistics import mean
from typing import Any

from autotrader.learning.features import stamp
from autotrader.learning.model import CONFIG, fit, metrics, predict, research_selected
from autotrader.research.data import canonical, digest


def independent(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One deterministic representative per global overlapping exposure window.

    All crypto assets share an episode, so correlated simultaneous longs cannot
    inflate sample size. Selection uses baseline eligibility then timestamp/id,
    never outcomes. This is deliberately conservative until a correlation model
    has independent validation.
    """
    chosen: list[dict[str, Any]] = []
    until = None
    for row in sorted(rows, key=lambda r: (r['observed_at'], not r['baseline_eligible'], r['id'])):
        start = stamp(row['observed_at'])
        if until is not None and start < until:
            continue
        chosen.append(row);until = stamp(row['target']['end_at'])
    return chosen


def evaluate(rows: list[dict[str, Any]], previous_holdout_end: str | None = None, *,
             sealed_windows: list[list[str]] | None = None,
             baseline_profile: str | None = None) -> dict[str, Any]:
    available = [r for r in rows if not any(stamp(lo) <= stamp(r['observed_at']) <= stamp(hi) for lo, hi in sealed_windows or [])]
    episodes = independent(available)
    base = {'config': CONFIG, 'rows': len(rows), 'independent_episodes': len(episodes),
            'primary_promotion': False, 'baseline_profile': baseline_profile,
            'baseline_scope': 'Original recorded eligibility at exact approved profile; no retrospective relabeling', 'evidence_category': 'HISTORICAL_MODELED_EXECUTION',
            'dataset_hash': digest(canonical(rows))}
    if len(episodes) < CONFIG['min_episodes'] or (stamp(episodes[-1]['observed_at'])-stamp(episodes[0]['observed_at'])) < timedelta(days=CONFIG['min_days']):
        return {**base, 'status': 'INSUFFICIENT_EVIDENCE', 'required_episodes': CONFIG['min_episodes'], 'required_days': CONFIG['min_days']}
    # Old holdout windows never enter future fitting or calibration. Fresh data
    # after the previous endpoint is required for a new untouched final check.
    if previous_holdout_end:
        fresh = [r for r in episodes if stamp(r['observed_at']) > stamp(previous_holdout_end)]
        if len(fresh) < CONFIG['min_new_episodes']:
            return {**base, 'status': 'COLLECTING_NEW_INDEPENDENT_EVIDENCE', 'new_episodes': len(fresh)}
    n = len(episodes);train, calibration, walk, hold = (episodes[:int(n*.50)], episodes[int(n*.50):int(n*.65)],
        episodes[int(n*.65):int(n*.80)], episodes[int(n*.80):])
    if previous_holdout_end:
        hold = [r for r in hold if stamp(r['observed_at']) > stamp(previous_holdout_end)]
    if baseline_profile:
        # Original-profile decisions cannot be relabeled as today's approved policy.
        walk = [r for r in walk if r.get('profile', r['features'].get('profile')) == baseline_profile]
        hold = [r for r in hold if r.get('profile', r['features'].get('profile')) == baseline_profile]
    # Embargo one whole label horizon at each partition boundary.
    def purge(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [r for r in left if stamp(r['target']['end_at'])+timedelta(minutes=CONFIG['horizon_minutes']) < stamp(right[0]['observed_at'])] if right else []
    train, calibration, walk = purge(train, calibration), purge(calibration, walk), purge(walk, hold)
    if min(map(len, (train, calibration, walk, hold))) < CONFIG['min_partition']:
        return {**base, 'status': 'INSUFFICIENT_PURGED_PARTITIONS'}
    try:
        model = fit(train, calibration)
    except ValueError as error:
        return {**base, 'status': 'QUARANTINED', 'reason': str(error)}
    comparisons = []
    def score(sample: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        predictions = [predict(model, r['features']) for r in sample]
        return metrics(sample, [p['probability_net_positive'] for p in predictions],
                       selections=[research_selected(r['baseline_eligible'], p) for r, p in zip(sample, predictions)], **kwargs)
    for name, sample in [('walk_forward_1', walk[:len(walk)//2]), ('walk_forward_2', walk[len(walk)//2:]), ('untouched_holdout', hold)]:
        challenger, baseline, stress = score(sample), score(sample, baseline=True), score(sample, stressed=True)
        comparisons.append({'partition': name, 'challenger': challenger, 'approved_baseline': baseline, 'cost_stress_2x': stress,
                            'start': sample[0]['observed_at'], 'end': sample[-1]['target']['end_at']})
    by_regime = {}
    for regime in sorted({r['features']['regime'] for r in hold}):
        group = [r for r in hold if r['features']['regime'] == regime]
        by_regime[regime] = score(group)
    reasons = []
    for c in comparisons:
        m, b, stress = c['challenger'], c['approved_baseline'], c['cost_stress_2x']
        if m['selected'] < CONFIG['min_selected']: reasons.append('insufficient_selected_evidence')
        if (m['net_expectancy_r'] or -1) <= max(0., b['net_expectancy_r'] or 0.): reasons.append('no_net_advantage')
        if (stress['net_expectancy_r'] or -1) <= 0: reasons.append('cost_stress_failed')
        if m['brier'] >= .25 or m['calibration_error'] > .15: reasons.append('calibration_failed')
        if m['max_drawdown_r'] > max(3., b['max_drawdown_r']): reasons.append('drawdown_failed')
    if len(by_regime) < 2 or any(v['selected'] < CONFIG['min_selected'] or (v['net_expectancy_r'] or -1) <= 0 for v in by_regime.values()):
        reasons.append('regime_robustness_insufficient')
    train_score = score(train)
    if comparisons[-1]['challenger']['brier']-train_score['brier'] > .10: reasons.append('overfitting_gap')
    if mean(predict(model, r['features'])['feature_drift_fraction'] for r in hold) > .2: reasons.append('feature_drift')
    return {**base, 'status': 'QUALIFIED_SHADOW' if not reasons else 'QUARANTINED', 'reasons': sorted(set(reasons)),
            'model': model, 'comparisons': comparisons, 'regimes': by_regime, 'training': train_score,
            'holdout_start': hold[0]['observed_at'], 'holdout_end': hold[-1]['target']['end_at'],
            'partition_ids': {name: [r['id'] for r in sample] for name, sample in [('train', train), ('calibration', calibration), ('walk', walk), ('holdout', hold)]},
            'limitations': ['No executable future depth or prospective profit claim',
                           'One chronological expansion and two forward blocks; no hyperparameter selection',
                           'Primary baseline has no approved ML weights; deterministic entry eligibility is compared at equal unit risk']}
