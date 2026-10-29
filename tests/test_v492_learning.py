"""Causality, independent validation, durable models and paper-only isolation."""
import copy
import json
from datetime import UTC, datetime, timedelta

import pytest

from autotrader.api.learning import read_status
from autotrader.learning import FEATURE_SCHEMA
from autotrader.learning.controller import ingest, mature, publish, run_training
from autotrader.learning.evaluation import evaluate, independent
from autotrader.learning.features import NAMES, build
from autotrader.learning.model import fit, predict
from autotrader.learning.store import Store
from autotrader.learning.targets import label

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def evidence():
    return {'as_of': (NOW-timedelta(minutes=5)).isoformat(), 'data_hash': 'recorded-hash',
        'execution_profile': '4.9.2-paper.1', 'entry_eligible': True,
        'entry_plan': {'stop': '98', 'targets': ['104', '106', '108']},
        'raoe_regime': {'atr': '1', 'benchmark': 'MIXED', 'relative_return_30m': '.01',
            'benchmarks': {s: {'return_30m': '.001', 'last_closed_at': (NOW-timedelta(minutes=5)).isoformat()} for s in ('BTC-EUR','ETH-EUR')},
            'timeframes': {str(tf): {'last_closed_at': (NOW-timedelta(minutes=tf)).isoformat(),
                                   'trend': 'BULLISH', 'ema9': '99'} for tf in (5,15,60)},
            'near_liquidity': {'bid_quote': '1000', 'ask_quote': '1200'}},
        'pattern_state': {'extension_atr': '1'},
        'economics': {'measurements': {'atr': '1', 'entry': {'vwap': '100', 'spread_bps': '10'},
            'cost_basis_eur': '100.1', 'fillable_quantity': '1', 'net_reward_risk': '1.5',
            'estimated_total_round_trip_cost_eur': '.5', 'exit_now': {'depth_impact_bps': '1'},
            'assumptions': {'exit_fee_bps': '10', 'slippage_bps': '8'}}}}


def event(identity='signal1'):
    return {'id': identity, 'observed_at': NOW.isoformat(), 'symbol': 'TEST-EUR',
            'strategy_id': 'RAOE_TREND_PULLBACK', 'evidence': evidence(),
            'evidence_category': 'REVOLUT_X_PROSPECTIVE_PAPER', 'baseline_eligible': True}


def candles():
    return [{'symbol': 'TEST-EUR', 'source': 'revolut-x', 'timestamp': (NOW+timedelta(minutes=5*i)).isoformat(),
             'open': '100', 'high': '101', 'low': '99', 'close': '100'} for i in range(50)]


def sample(i):
    t = NOW+timedelta(hours=5*i)
    good = i%3 != 0
    values = [1. if good else -1.]+[0.]*(len(NAMES)-1)
    return {'id': str(i), 'observed_at': t.isoformat(), 'baseline_eligible': True,
        'features': {'schema': FEATURE_SCHEMA, 'names': list(NAMES), 'values': values, 'regime': 'MIXED' if i%2 else 'SUPPORTIVE', 'strategy': 'RAOE_TREND_PULLBACK'},
        'target': {'positive': int(good), 'net_r': 1.5 if good else -1., 'net_return': .015 if good else -.01, 'end_at': (t+timedelta(hours=4)).isoformat()},
        'stress_target': {'net_r': 1. if good else -1.2, 'net_return': .01 if good else -.012}}


def test_features_ignore_outcomes_and_require_completed_snapshot():
    e = evidence();before = build(e, 'RAOE_TREND_PULLBACK', NOW.isoformat())
    e['future_outcome'] = {'net_return': 999}
    after = build(e, 'RAOE_TREND_PULLBACK', NOW.isoformat())
    assert before['values'] == after['values']  # evidence hash binds all original bytes
    assert len(before['values']) == len(NAMES)
    with pytest.raises(ValueError, match='stale_or_future'):
        build(e, 'RAOE_TREND_PULLBACK', (NOW-timedelta(seconds=1)).isoformat())
    with pytest.raises(ValueError, match='stale_or_future'):
        build(e, 'RAOE_TREND_PULLBACK', (NOW+timedelta(minutes=5)).isoformat())
    e['raoe_regime']['benchmarks']['BTC-EUR']['last_closed_at'] = (NOW+timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError, match='unavailable_context'):
        build(e, 'RAOE_TREND_PULLBACK', NOW.isoformat())


@pytest.mark.parametrize('fault', ['nan', 'missing_peer', 'missing_hash', 'wrong_source', 'future'])
def test_bad_features_are_durable_exclusions(tmp_path, fault):
    e = event()
    if fault == 'nan': e['evidence']['economics']['measurements']['entry']['vwap'] = 'NaN'
    if fault == 'missing_peer': e['evidence']['raoe_regime']['benchmarks'].pop('ETH-EUR')
    if fault == 'missing_hash': e['evidence'].pop('data_hash')
    if fault == 'wrong_source': e['evidence_category'] = 'SYNTHETIC_ACCEPTANCE'
    if fault == 'future': e['evidence']['as_of'] = NOW.isoformat()
    s = Store(tmp_path)
    try:
        ingest(s, e, NOW.isoformat());s.db.commit()
        assert s.db.execute('SELECT status FROM observations').fetchone()[0] == 'DATA_QUALITY_FAILED'
        assert not run_training(s, NOW.isoformat()).get('model')
    finally:s.close()


def test_labels_conservative_ambiguity_gaps_cost_stress_and_future_invariance():
    e = event();bars = candles();result = label(e, bars, 240)
    assert result['net_return'] < 0 and result['executable_outcome_proven'] is False
    stressed = label(e, bars, 240, cost_stress=2)
    assert stressed['net_return'] < result['net_return']
    # Flat mid path: double exit costs, and one extra original entry fee/slip.
    # Existing entry VWAP/cost basis must not receive two extra entry charges.
    expected_proceeds = 100*(1-.001)*(1-.002)*(1-.0016)*(1-.0002)
    assert stressed['net_return'] == pytest.approx(expected_proceeds/(100.1+.18)-1)
    future = copy.deepcopy(bars[-1]);future['high']='1000000'
    assert label(e, bars[:-1]+[future], 240) == result
    missing = [b for b in bars if b['timestamp'] != (NOW+timedelta(minutes=30)).isoformat()]
    with pytest.raises(ValueError, match='incomplete_future'):label(e, missing, 240)
    ambiguous = copy.deepcopy(bars);ambiguous[2].update(high='110', low='95')
    stopped = label(e, ambiguous, 240)
    assert stopped['ambiguous'] and stopped['exit_reason']=='STOP_FIRST_CONSERVATIVE'
    assert stopped['net_return'] < 0
    conflicting = copy.deepcopy(bars[4]);conflicting['close']='100.5'
    with pytest.raises(ValueError, match='conflicting'):label(e, [*bars, conflicting], 240)


def test_correlated_assets_and_overlapping_strategies_are_not_independent():
    rows = [sample(0), {**sample(0), 'id': 'correlated', 'symbol': 'OTHER-EUR'}, sample(1)]
    assert len(independent(rows)) == 2
    assert evaluate(rows)['status'] == 'INSUFFICIENT_EVIDENCE'
    assert evaluate([])['status'] == 'INSUFFICIENT_EVIDENCE'


def test_fit_predict_roundtrip_schema_and_holdout_noninterference(tmp_path):
    rows = [sample(i) for i in range(100)]
    model = fit(rows[:60], rows[60:80]);p = predict(model, rows[81]['features'])
    assert p['primary_execution_authorized'] is False
    assert 0 <= p['probability_net_positive'] <= 1
    assert predict(model, rows[82]['features'])['probability_net_positive'] > predict(model, rows[81]['features'])['probability_net_positive']
    s = Store(tmp_path)
    identity = s.artifact({'model': model});s.db.commit();s.close()
    s = Store(tmp_path)
    assert s.read_artifact(identity)['model'] == model
    path = tmp_path/'artifacts'/(identity+'.json');path.write_text('{}')
    with pytest.raises(ValueError, match='integrity'):s.read_artifact(identity)
    changed = copy.deepcopy(rows[82]['features']);changed['schema']='wrong'
    with pytest.raises(ValueError, match='schema'):predict(model, changed)
    s.close()


def test_chronological_purge_holdout_and_sealing():
    rows = [sample(i) for i in range(600)]
    result = evaluate(rows)
    assert result['status'] in {'QUALIFIED_SHADOW', 'QUARANTINED'}
    ids = result['partition_ids'];by_id = {r['id']: r for r in rows}
    assert len({v for partition in ids.values() for v in partition}) == sum(map(len, ids.values()))
    for a,b in [('train','calibration'),('calibration','walk'),('walk','holdout')]:
        left, right = by_id[ids[a][-1]], by_id[ids[b][0]]
        assert datetime.fromisoformat(left['target']['end_at'])+timedelta(hours=4) < datetime.fromisoformat(right['observed_at'])
    changed = copy.deepcopy(rows)
    for r in changed:
        if r['id'] in ids['holdout']: r['target']['positive'] = 1-r['target']['positive']
    again = evaluate(changed)
    assert again['model'] == result['model']  # no fitting or calibration sees final holdout
    sealed = [[result['holdout_start'],result['holdout_end']]]
    next_result = evaluate([sample(i) for i in range(850)],result['holdout_end'],sealed_windows=sealed)
    assert not set(ids['holdout']).intersection(next_result['partition_ids']['train'])
    assert next_result['holdout_start'] > result['holdout_end']


def test_restart_replays_ingestion_and_maturity_without_duplicates(tmp_path):
    s = Store(tmp_path);e = event();ingest(s,e,NOW.isoformat());s.set('cursor',['saved','signal']);s.db.commit();s.close()
    s = Store(tmp_path);ingest(s,e,NOW.isoformat());assert s.get('cursor')==['saved','signal']
    saved = json.loads(s.db.execute('SELECT payload FROM observations').fetchone()[0])
    mature(s,saved,candles(),(NOW+timedelta(hours=5)).isoformat())
    mature(s,saved,candles(),(NOW+timedelta(hours=5)).isoformat())
    assert s.db.execute('SELECT count(*) FROM observations').fetchone()[0]==1
    assert run_training(s,(NOW+timedelta(hours=5)).isoformat())['status']=='INSUFFICIENT_EVIDENCE'
    state = publish(s, (NOW+timedelta(hours=5)).isoformat())
    assert state['primary_promotion_automatic'] is False and state['live_authorized'] is False
    assert state['dataset']['counts']=={'LABELED':1}
    s.close()


def test_forward_shadow_requires_preexisting_model_and_no_backlog_relabel(tmp_path):
    s = Store(tmp_path);rows=[sample(i) for i in range(100)]
    m = fit(rows[:60],rows[60:80]);identity=s.artifact({'model':m,'trained_at':(NOW-timedelta(hours=1)).isoformat()});s.set('challenger',identity)
    ingest(s,event('fresh'),NOW.isoformat())
    ingest(s,event('backfill'),(NOW+timedelta(hours=2)).isoformat())
    assert json.loads(s.db.execute("SELECT prediction FROM observations WHERE id='fresh'").fetchone()[0])['category']=='SHADOW_FORWARD_PREDICTION'
    assert s.db.execute("SELECT prediction FROM observations WHERE id='backfill'").fetchone()[0] is None
    assert s.get('challenger')==identity
    assert s.get('approved_primary_model') is None
    s.close()


def test_status_reader_missing_corrupt_and_stale(tmp_path):
    assert read_status(tmp_path)['status']=='WAITING_FOR_COLLECTOR'
    (tmp_path/'status.json').write_text('oops')
    assert read_status(tmp_path)['status']=='INVALID_RESEARCH_STATUS'
    (tmp_path/'status.json').write_text(json.dumps({'observed_at':NOW.isoformat(),'warnings':[]}))
    assert read_status(tmp_path)['collector_stale']


def test_qualified_model_automatically_enters_shadow_and_drift_quarantines(tmp_path):
    """Synthetic separable task proves lifecycle mechanics, not a market edge."""
    from autotrader.learning.controller import status
    rows=[sample(i) for i in range(600)]
    s=Store(tmp_path)
    for r in rows:
        r['symbol']='TEST-EUR';r['rejection']=None;r['targets']={'60':r['target']}
        r['target'].update(exit_reason='HORIZON',ambiguous=False)
        s.db.execute("INSERT INTO observations(id,observed_at,payload,status,result) VALUES (?,?,?,'LABELED',?)",
            (r['id'],r['observed_at'],json.dumps({'id':r['id']}),json.dumps(r)))
    now=(NOW+timedelta(days=130)).isoformat()
    report=run_training(s,now)
    assert report['status']=='QUALIFIED_SHADOW'
    identity=s.get('challenger');assert identity and report['model_id']==identity
    assert s.read_artifact(identity)['model']['config']['primary_authority'] is False
    assert s.get('approved_primary_model') is None
    for i in range(24):
        p={'model_id':identity,'selected':False,'feature_drift_fraction':1.}
        s.db.execute('UPDATE observations SET prediction=? WHERE id=?',(json.dumps(p),str(i)))
    result=status(s,now)
    assert result['active_challenger'] is None
    assert result['quarantined_challenger']['model_id']==identity
    # Restart preserves quarantine; historical calibration cannot reactivate it.
    s.db.commit();s.close();s=Store(tmp_path)
    assert s.get('challenger') is None
    assert run_training(s,(NOW+timedelta(days=131)).isoformat())['model_id']==identity
    assert s.get('challenger') is None
    s.close()


def test_validation_cannot_claim_gains_from_baseline_rejected_candidates():
    from autotrader.learning.model import research_selected

    rows=[{**sample(i), 'baseline_eligible':False} for i in range(600)]
    report=evaluate(rows)
    assert report['status']=='QUARANTINED'
    assert all(p['challenger']['selected']==p['cost_stress_2x']['selected']==0 for p in report['comparisons'])
    prediction={'confidence':'RESEARCH_ESTIMATE','probability_net_positive':.9,'conditional_expected_net_return':.01}
    assert research_selected(True,prediction)
    assert not research_selected(False,prediction)
    assert not research_selected(True,{**prediction,'confidence':'LOW'})
    assert not research_selected(True,{**prediction,'conditional_expected_net_return':-.01})


def test_dense_raw_history_cannot_prevent_long_term_automatic_training(tmp_path):
    """50,001 correlated signals must not hide later independent evidence."""
    from autotrader.learning.controller import training_rows

    s=Store(tmp_path);first=sample(0)
    s.db.executemany("INSERT INTO observations(id,observed_at,payload,status,result) VALUES (?,?,?,'LABELED',?)",
        ((f'dense{i:06}',first['observed_at'],'{}',json.dumps(first)) for i in range(50001)))
    for i in range(1,601):
        row=sample(i)
        s.db.execute("INSERT INTO observations(id,observed_at,payload,status,result) VALUES (?,?,?,'LABELED',?)",
            (row['id'],row['observed_at'],'{}',json.dumps(row)))
    assert len(training_rows(s))==601
    report=run_training(s,(NOW+timedelta(days=130)).isoformat())
    assert report['independent_episodes']==601
    assert report['status']=='QUALIFIED_SHADOW'  # synthetic lifecycle mechanics only
    assert s.get('challenger') and s.get('approved_primary_model') is None
    s.close()


def test_api_learning_requires_auth_and_reports_running_backend(monkeypatch,tmp_path):
    from fastapi.testclient import TestClient

    from autotrader.api.main import create_app
    monkeypatch.setenv('DATABASE_URL',f'sqlite+aiosqlite:///{tmp_path / "learning-api.db"}')
    monkeypatch.setenv('RESEARCH_ROOT',str(tmp_path/'research'))
    monkeypatch.setenv('PERSONAL_PAPER_ENABLED','false')
    app=create_app()
    with TestClient(app) as client:
        assert client.get('/api/personal-paper/learning').status_code==401
        response=client.get('/api/personal-paper/learning',auth=('admin','change-me'))
        assert response.status_code==200
        assert response.json()['backend_version']==app.version=='4.9.2-rc.2'
        assert response.json()['status']=='WAITING_FOR_COLLECTOR'
