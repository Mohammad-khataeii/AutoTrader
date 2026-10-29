"""Evidence-driven training and automatic research challenger lifecycle."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import timedelta
from statistics import mean
from typing import Any

from autotrader.learning import FEATURE_SCHEMA, TARGET_SCHEMA
from autotrader.learning.evaluation import evaluate, independent
from autotrader.learning.features import build, stamp
from autotrader.learning.model import CONFIG, predict, research_selected
from autotrader.learning.store import Store
from autotrader.learning.targets import label
from autotrader.research.data import atomic_write, canonical


def ingest(store: Store, event: dict[str, Any], now: str) -> None:
    if event.get('evidence_category') != 'REVOLUT_X_PROSPECTIVE_PAPER':
        event = {**event, 'data_failure': 'nonprospective_source_excluded'}
    else:
        try:
            event = {**event, 'features': build(event['evidence'], event['strategy_id'], event['observed_at'])}
        except (KeyError, ValueError, TypeError, IndexError, ZeroDivisionError) as exc:
            event = {**event, 'data_failure': type(exc).__name__+':'+str(exc)}
    prediction = None
    model_id = store.get('challenger')
    if model_id and 'features' in event:
        model_run = store.read_artifact(model_id)
        # Backlog inference is historical, never relabeled forward performance.
        if stamp(model_run['trained_at']) <= stamp(event['observed_at']) <= stamp(now) < stamp(event['observed_at'])+timedelta(seconds=90):
            prediction = {**predict(model_run['model'], event['features']), 'model_id': model_id,
                          'predicted_at': now, 'category': 'SHADOW_FORWARD_PREDICTION',
                          'selected': False, 'primary_execution_authorized': False}
            prediction['selected'] = research_selected(event['baseline_eligible'], prediction)
            # Pin the prediction before observing its future path.
    # Keep bounded plan inputs locally; full immutable evidence remains in its source ledger.
    if event.get('data_failure'):
        event = {k: v for k, v in event.items() if k != 'evidence'}
    else:
        original = event['evidence']
        event = {**event, 'evidence': {'execution_profile': original.get('execution_profile'),
            'entry_plan': {k: original['entry_plan'][k] for k in ('stop', 'targets')},
            'economics': {'measurements': original['economics']['measurements']}}}
    store.insert(event, prediction)
    if event.get('data_failure'):
        store.finish(event['id'], 'DATA_QUALITY_FAILED', {'reason': event['data_failure']})


def mature(store: Store, event: dict[str, Any], candles: list[dict[str, Any]], now: str) -> None:
    if stamp(now) < stamp(event['observed_at'])+timedelta(minutes=240):
        return
    try:
        targets = {str(h): label(event, candles, h) for h in (60, 240)}
        stress = label(event, candles, 240, cost_stress=2.)
        store.finish(event['id'], 'LABELED', {'id': event['id'], 'symbol': event['symbol'],
            'observed_at': event['observed_at'], 'features': event['features'],
            'baseline_eligible': event['baseline_eligible'], 'targets': targets,
            'target': targets['240'], 'stress_target': stress, 'rejection': event.get('rejection'),
            'profile': event['evidence'].get('execution_profile')})
    except (KeyError, ValueError, TypeError, IndexError, ZeroDivisionError) as error:
        # Retry temporary holes for up to 48h; afterward retain a failed row,
        # never replace missing bars with a negative target.
        if stamp(now) > stamp(event['observed_at'])+timedelta(hours=48):
            store.finish(event['id'], 'DATA_QUALITY_FAILED', {'reason': str(error)})


def training_rows(store: Store) -> list[dict[str, Any]]:
    """Seek independent windows, so dense raw history cannot exhaust the cap.

    The existing status/time index skips overlapping crypto observations without
    loading them. Tie breaking uses recorded eligibility/id, never outcomes.
    Financial source timestamps and collector cursors are normalized UTC.
    """
    rows: list[dict[str, Any]] = []
    cursor = '1970-01-01T00:00:00+00:00'
    while len(rows) < 50000:
        record = store.db.execute("SELECT result FROM observations WHERE status='LABELED' AND observed_at>=? ORDER BY observed_at,json_extract(result,'$.baseline_eligible') DESC,id LIMIT 1", (cursor,)).fetchone()
        if not record:
            break
        row = json.loads(record[0])
        if stamp(row['target']['end_at']) <= stamp(row['observed_at']):
            raise ValueError('nonpositive_learning_episode_window')
        rows.append(row)
        cursor = row['target']['end_at']
    return rows


def run_training(store: Store, now: str) -> dict[str, Any]:
    rows = training_rows(store)
    episodes = independent(rows)
    previous = store.get('last_training', {})
    since = (stamp(now)-stamp(previous['at'])).total_seconds() if previous.get('at') else None
    if previous and (since is not None and since < 21600 or len(episodes)-previous.get('episodes', 0) < CONFIG['min_new_episodes']):
        current: dict[str, Any] = store.get('latest_report', {'status': 'COLLECTING_NEW_INDEPENDENT_EVIDENCE'})
        return current
    sealed = store.get('sealed_holdouts', [])
    report = evaluate(rows, previous.get('holdout_end'), sealed_windows=sealed,
                      baseline_profile=(store.get('baseline_manifest') or {}).get('version'))
    report['actual_outcomes_model'] = train_realized(store, now)
    report.update(trained_at=now, feature_schema=FEATURE_SCHEMA, target_schema=TARGET_SCHEMA,
                  primary_model='DETERMINISTIC_FROZEN_BASELINE_NO_APPROVED_ML',
                  baseline_manifest=store.get('baseline_manifest'), data_limit_reached=len(rows)==50000)
    if report['status'] in {'QUALIFIED_SHADOW', 'QUARANTINED'}:
        if len(rows) == 50000:
            report.update(status='QUARANTINED', reasons=[*report.get('reasons', []), 'dataset_capacity_requires_review'])
        identity = store.artifact(report)
        if report.get('holdout_start'):
            sealed.append([report['holdout_start'], report['holdout_end']])
            store.set('sealed_holdouts', sealed)
        if report['status'] == 'QUALIFIED_SHADOW':
            store.set('challenger', identity)
            store.set('challenger_started_at', now)
        store.set('last_training', {'at': now, 'episodes': len(episodes), 'holdout_end': report.get('holdout_end', previous.get('holdout_end'))})
        # Future control iterations do not reread or refit on a used holdout.
        report = {k: v for k, v in report.items() if k not in {'model', 'partition_ids'}}
        report['model_id'] = identity
    store.set('latest_report', report)
    return report


def status(store: Store, now: str) -> dict[str, Any]:
    counts = dict(store.db.execute('SELECT status,count(*) FROM observations GROUP BY status'))
    rows = [json.loads(r[0]) for r in store.db.execute("SELECT result FROM observations WHERE status='LABELED' ORDER BY observed_at DESC,id DESC LIMIT 50000")]
    rows.reverse()
    episodes = training_rows(store)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[r['features']['strategy']+' / '+r['features']['regime']].append(r)
    performance = [{'strategy_regime': k, 'signals': len(v),
        'independent_episodes': len(independent(v)), 'modeled_net_expectancy_r': mean(r['target']['net_r'] for r in v)} for k, v in groups.items()]
    reasons: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    for state in ('LABELED', 'PENDING', 'DATA_QUALITY_FAILED'):
        for payload, result in store.db.execute('SELECT payload,result FROM observations WHERE status=? ORDER BY observed_at DESC,id DESC LIMIT 10000', (state,)):
            e = json.loads(payload)
            if e.get('rejection'): reasons.update(str(e['rejection']).split(','))
            if state == 'DATA_QUALITY_FAILED': failures.update([json.loads(result)['reason']])
    model_id = store.get('challenger');forward = []
    candidates = []
    for identity, observed, payload in store.db.execute('SELECT id,observed_at,prediction FROM observations WHERE prediction IS NOT NULL ORDER BY observed_at DESC LIMIT 30'):
        p = json.loads(payload)
        if p['model_id'] == model_id:
            candidates.append({'id': identity, 'observed_at': observed, **p})
    candidates.sort(key=lambda p: -(p.get('conditional_expected_net_return') or 0))
    for prediction, result in store.db.execute("SELECT prediction,result FROM observations WHERE prediction IS NOT NULL AND status='LABELED' ORDER BY observed_at,id"):
        p, r = json.loads(prediction), json.loads(result)
        if p['model_id'] == model_id and p['selected']:
            forward.append({**r, 'prediction': p})
    # Collapse selection outcomes into global nonoverlapping forward episodes.
    forward = independent(forward)
    drift_rows = [json.loads(r[0]) for r in store.db.execute('SELECT prediction FROM observations WHERE prediction IS NOT NULL ORDER BY observed_at DESC LIMIT 100')]
    drift_rows = [p for p in drift_rows if p['model_id'] == model_id]
    drift = mean(p['feature_drift_fraction'] for p in drift_rows) if drift_rows else None
    degraded = (len(forward) >= 24 and mean(r['target']['net_r'] for r in forward) <= 0) or (len(drift_rows) >= 24 and drift is not None and drift > .2)
    if model_id and degraded:
        store.set('quarantined_challenger', {'model_id': model_id, 'at': now, 'reason': 'forward_deterioration_or_feature_drift'})
        store.set('challenger', None);model_id = None
    warnings = []
    if counts.get('DATA_QUALITY_FAILED', 0): warnings.append('Some observations fail causal or data quality checks; see coverage failures')
    if len(episodes) < CONFIG['min_episodes']: warnings.append('Insufficient independent evidence for ML promotion')
    if any(n > 10000 for n in counts.values()): warnings.append('Rejection and coverage summaries use the latest 10,000 observations per state; training retains independent episodes across full history')
    return {'observed_at': now, 'status': store.get('latest_report', {}).get('status', 'COLLECTING'),
        'approved_model': 'DETERMINISTIC_FROZEN_BASELINE_NO_APPROVED_ML', 'active_challenger': model_id,
        'dataset': {'counts': counts, 'independent_episodes': len(episodes),
            'from': episodes[0]['observed_at'] if episodes else None, 'until': episodes[-1]['observed_at'] if episodes else None,
            'feature_schema': FEATURE_SCHEMA, 'target_schema': TARGET_SCHEMA,
            'required_episodes': CONFIG['min_episodes'], 'required_days': CONFIG['min_days'],
            'coverage_failures': dict(failures.most_common(12))},
        'latest_training': store.get('latest_report'), 'strategy_regime_performance': performance,
        'summary_scope': 'Latest 50,000 labels for conditional path/exit summaries; latest 10,000 observations per state for rejection/coverage counts. Training seeks up to 50,000 independent episodes across retained history.',
        'rejection_reasons': dict(reasons.most_common(15)), 'feature_drift': drift,
        'forward_evaluation': {'selected_independent_episodes': len(forward),
            'modeled_net_expectancy_r': mean(r['target']['net_r'] for r in forward) if forward else None,
            'prediction_category': 'SHADOW_FORWARD_PREDICTIONS', 'outcome_category': 'RECORDED_PATH_MODELED_EXECUTION',
            'executable_paper_ledger': False}, 'quarantined_challenger': store.get('quarantined_challenger'),
        'ranked_shadow_candidates': candidates,
        'realized_positions_collected': store.db.execute('SELECT count(*) FROM realized').fetchone()[0],
        'warnings': warnings, 'primary_promotion_automatic': False, 'live_authorized': False,
        'fallback': 'Frozen deterministic paper strategy and all broker risk controls',
        'exit_feedback': exit_feedback(rows), 'read_only_financial_ledgers': True}


def exit_feedback(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stopped = [r for r in independent(rows) if r['target']['exit_reason'] == 'STOP_FIRST_CONSERVATIVE']
    return {'modeled_stop_episodes': len(stopped),
        'short_horizon_positive_long_horizon_negative': sum(r['targets']['60']['positive'] == 1 and r['target']['positive'] == 0 for r in independent(rows)),
        'ambiguous_barrier_episodes': sum(r['target']['ambiguous'] for r in independent(rows)),
        'mid_recovered_entry_after_stop': sum(r['target'].get('exit_feedback', {}).get('mid_recovered_entry_after_stop', False) for r in stopped),
        'mid_continued_below_stop': sum(r['target'].get('exit_feedback', {}).get('mid_continued_below_stop', False) for r in stopped),
        'stop_noise_groups': {k: len([r for r in stopped if (r['features']['values'][7] < 1.5) == (k == 'below_1_5_atr')]) for k in ('below_1_5_atr', 'at_least_1_5_atr')},
        'policy': 'Research diagnostics only; existing exit plans and stops never change',
        'limitations': 'Matched regime path labels do not establish an executable alternative exit'}


def publish(store: Store, now: str) -> dict[str, Any]:
    report = status(store, now)
    store.db.commit()
    atomic_write(store.root/'status.json', canonical(report))
    return report


def train_realized(store: Store, now: str) -> dict[str, Any]:
    """Separate outcome task: actual managed paper positions, never mixed with path proxies."""
    rows = []
    for (payload,) in store.db.execute('SELECT payload FROM realized ORDER BY id'):
        r = json.loads(payload)
        if not r.get('features'):
            continue
        cost = float(r['filled_quantity'])*float(r['average_fill_price'])+float(r['buy_fee'])
        net = float(r['realized_pnl'])/cost
        risk = float(r['planned_risk_eur'])/cost
        if cost <= 0 or risk <= 0:
            continue
        target = {'positive': int(net > 0), 'net_r': net/risk, 'net_return': net, 'end_at': r['closed_at']}
        rows.append({'id': 'actual:'+r['position_id'], 'observed_at': r['entry_observed_at'],
            'features': r['features'], 'baseline_eligible': True, 'target': target,
            'stress_target': {**target, 'net_r': (net-float(r['total_fees'])/cost-.0016)/risk,
                              'net_return': net-float(r['total_fees'])/cost-.0016}})
    previous = store.get('actual_last_holdout_end')
    report = evaluate(rows, previous, sealed_windows=store.get('actual_sealed_holdouts', []),
                      baseline_profile=(store.get('baseline_manifest') or {}).get('version'))
    if report.get('model'):
        report.update(trained_at=now, task='ACTUAL_MANAGED_PAPER_POSITION_NET_OUTCOME')
        identity = store.artifact(report)
        store.set('actual_last_holdout_end', report['holdout_end'])
        windows = store.get('actual_sealed_holdouts', [])
        store.set('actual_sealed_holdouts', [*windows, [report['holdout_start'], report['holdout_end']]])
        # A different actual-exit task cannot replace the approved path challenger.
        report = {k: v for k, v in report.items() if k not in {'model', 'partition_ids'}}
        report['model_id'] = identity
    return {**report, 'evidence_category': 'ACTUAL_PRIMARY_PAPER_LEDGER',
            'source_closed_positions': store.db.execute('SELECT count(*) FROM realized').fetchone()[0],
            'task': 'Actual recorded managed-position outcome; distinct from fixed-horizon path model',
            'automatic_primary_promotion': False}
