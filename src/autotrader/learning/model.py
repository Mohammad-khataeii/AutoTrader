"""Small deterministic L2 logistic model with chronological Platt calibration.

JSON artifacts avoid unsafe pickle deserialization and native runtime dependencies.
Normalization and calibration are fitted on their own training partitions only.
"""
from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any

from autotrader.learning.features import finite

CONFIG: dict[str, Any] = {'version': 'logistic-l2/1', 'epochs': 240, 'learning_rate': .08,
          'l2': .03, 'clip_z': 6., 'probability_threshold': .60,
          'min_episodes': 240, 'min_new_episodes': 48, 'min_days': 45,
          'min_partition': 24, 'min_selected': 12, 'horizon_minutes': 240,
          'primary_authority': False, 'automatic_scope': 'ISOLATED_RESEARCH_ONLY'}


def sigmoid(z: float) -> float:
    return 1/(1+math.exp(-max(-35., min(35., z))))


def fit(rows: list[dict[str, Any]], calibration: list[dict[str, Any]]) -> dict[str, Any]:
    if len({r['target']['positive'] for r in rows}) < 2 or len({r['target']['positive'] for r in calibration}) < 2:
        raise ValueError('both_classes_required')
    schema, names = rows[0]['features']['schema'], rows[0]['features']['names']
    if not names or any(r['features']['schema'] != schema or r['features']['names'] != names
                        or len(r['features']['values']) != len(names) for r in [*rows, *calibration]):
        raise ValueError('mixed_feature_schemas')
    xs = [[finite(v) for v in r['features']['values']] for r in rows]
    center = [mean(v) for v in zip(*xs)]
    scale = [max(pstdev(v), 1e-6) for v in zip(*xs)]
    weights = [0.]*len(names);intercept = 0.
    matrix = [[max(-6., min(6., (v-m)/s)) for v, m, s in zip(x, center, scale)] for x in xs]
    for _ in range(CONFIG['epochs']):
        errors = [sigmoid(intercept+sum(w*v for w, v in zip(weights, x)))-r['target']['positive'] for x, r in zip(matrix, rows)]
        intercept -= CONFIG['learning_rate']*mean(errors)
        weights = [w-CONFIG['learning_rate']*(mean(e*x[j] for e, x in zip(errors, matrix))+CONFIG['l2']*w) for j, w in enumerate(weights)]
    model = {'schema': schema, 'names': list(names), 'center': center, 'scale': scale,
             'positive_mean_return': mean(r['target']['net_return'] for r in rows if r['target']['positive']),
             'negative_mean_return': mean(r['target']['net_return'] for r in rows if not r['target']['positive']),
             'weights': weights, 'intercept': intercept, 'calibration_slope': 1.,
             'calibration_intercept': 0., 'config': CONFIG}
    logits = [logit(model, r['features']) for r in calibration]
    a, b = 1., 0.
    for _ in range(160):
        errors = [sigmoid(a*z+b)-r['target']['positive'] for z, r in zip(logits, calibration)]
        # Nonnegative slope preserves ranking; a reversed model cannot be rescued.
        a = max(0., a-.05*(mean(e*z for e, z in zip(errors, logits))+.03*(a-1)))
        b -= .05*mean(errors)
    model.update(calibration_slope=a, calibration_intercept=b)
    return model


def logit(model: dict[str, Any], features: dict[str, Any]) -> float:
    if features['schema'] != model['schema'] or features['names'] != model['names'] or len(features['values']) != len(model['names']):
        raise ValueError('feature_schema_mismatch')
    xs = [max(-6., min(6., (finite(v)-m)/s)) for v, m, s in zip(features['values'], model['center'], model['scale'])]
    return finite(model['intercept']+sum(w*v for w, v in zip(model['weights'], xs)))


def predict(model: dict[str, Any], features: dict[str, Any]) -> dict[str, Any]:
    p = sigmoid(model['calibration_slope']*logit(model, features)+model['calibration_intercept'])
    z = [abs((finite(v)-m)/s) for v, m, s in zip(features['values'], model['center'], model['scale'])]
    drift = sum(v > 4 for v in z)/len(z)
    return {'probability_net_positive': p,
            'conditional_expected_net_return': p*model['positive_mean_return']+(1-p)*model['negative_mean_return'],
            'expected_return_basis': 'Calibrated class probability times training class mean returns; research estimate', 'feature_drift_fraction': drift,
            'confidence': 'LOW' if drift > .2 or .4 <= p <= .6 else 'RESEARCH_ESTIMATE',
            'research_size_multiplier': max(.5, min(1., p)), 'primary_execution_authorized': False}


def research_selected(baseline_eligible: bool, prediction: dict[str, Any]) -> bool:
    """The same frozen research selection rule in validation and forward use."""
    return (baseline_eligible and prediction['confidence'] != 'LOW'
            and prediction['probability_net_positive'] >= CONFIG['probability_threshold']
            and prediction['conditional_expected_net_return'] > 0)


def metrics(rows: list[dict[str, Any]], probabilities: list[float], *, baseline: bool = False,
            stressed: bool = False, selections: list[bool] | None = None) -> dict[str, Any]:
    if len(rows) != len(probabilities) or selections is not None and len(selections) != len(rows):
        raise ValueError('evaluation_selection_length_mismatch')
    mask = selections if selections is not None else [p >= CONFIG['probability_threshold'] for p in probabilities]
    selected = [r for r, allowed in zip(rows, mask) if r['baseline_eligible'] and (baseline or allowed)]
    outcomes = [r['stress_target' if stressed else 'target']['net_r'] for r in selected]
    returns = [r['stress_target' if stressed else 'target']['net_return'] for r in selected]
    running, peak, dd = 0., 0., 0.
    for value in outcomes:
        running += value;peak = max(peak, running);dd = max(dd, peak-running)
    wins, losses = sum(v for v in outcomes if v > 0), -sum(v for v in outcomes if v < 0)
    bins = []
    for lo in (0., .2, .4, .6, .8):
        pairs = [(r, p) for r, p in zip(rows, probabilities) if lo <= p < lo+.2 or lo == .8 and p == 1.]
        if pairs:
            bins.append({'lower': lo, 'n': len(pairs), 'predicted': mean(p for _, p in pairs),
                         'observed': mean(r['target']['positive'] for r, _ in pairs)})
    return {'episodes': len(rows), 'selected': len(selected), 'net_expectancy_r': mean(outcomes) if outcomes else None,
            'mean_net_return': mean(returns) if returns else None, 'profit_factor': wins/losses if losses else None,
            'max_drawdown_r': dd, 'brier': mean((p-r['target']['positive'])**2 for r, p in zip(rows, probabilities)),
            'calibration_error': sum(b['n']*abs(b['predicted']-b['observed']) for b in bins)/len(rows),
            'calibration_bins': bins, 'evidence_category': 'HISTORICAL_MODELED_EXECUTION'}
