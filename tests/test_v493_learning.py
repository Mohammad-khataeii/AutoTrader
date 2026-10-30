"""Stage-aware lifecycle, causal midpoint task and durable research isolation."""
import copy
import json
from datetime import timedelta

import pytest

from autotrader.learning.lifecycle import ingest, market_features, market_label, mature, summary
from autotrader.learning.market_model import evaluate, status, tick
from autotrader.learning.store import Store
from test_v492_learning import NOW, candles, evidence


def event():
    e=evidence();e.update(technical_eligible=False,economic_eligible=False,entry_eligible=False)
    e['primary_admission']={'inputs':{'close':'100'},'gates':{'primary_macro_context':False}}
    e['learning_context']={'data_hash':'causal-volume','close':'100','regime':copy.deepcopy(e['raoe_regime']),'volume_ratio':'1.1'}
    e['economics']=None
    return {'id':'unpriced','observed_at':NOW.isoformat(),'symbol':'TEST-EUR','strategy_id':'RAOE_TREND_PULLBACK',
            'evidence':e,'evidence_category':'REVOLUT_X_PROSPECTIVE_PAPER','baseline_eligible':False,'rejection':'technical_setup'}


def test_unpriced_rejection_retained_without_vwap_or_profit_claim(tmp_path):
    s=Store(tmp_path);e=event();ingest(s,e,NOW.isoformat())
    assert summary(s)['stages']=={'TECHNICAL_REJECTED':1}
    assert summary(s)['dispositions']=={'OBSERVED':1}
    assert s.db.execute('SELECT count(*) FROM observations').fetchone()[0]==0
    payload=json.loads(s.db.execute('SELECT payload FROM market_observations').fetchone()[0])
    assert payload['features']['reference_kind']=='COMPLETED_CANDLE_MID_NOT_EXECUTION_PRICE'
    mature(s,payload,candles(),(NOW+timedelta(hours=5)).isoformat())
    result=json.loads(s.db.execute('SELECT result FROM market_observations').fetchone()[0])
    assert result['target']['cost_adjusted'] is False
    assert result['target']['executable_outcome_proven'] is False
    assert 'net_return' not in result['target']
    assert result['baseline_eligible'] is False
    s.db.commit();s.close();s=Store(tmp_path);ingest(s,e,NOW.isoformat())
    assert summary(s)['unique_signals']==1
    assert s.db.execute('SELECT status FROM market_observations').fetchone()[0]=='LABELED'
    s.close()


@pytest.mark.parametrize('change,disposition',[
    ('legacy','COVERAGE_EXCLUDED'),('stale','COVERAGE_EXCLUDED'),
    ('future','DATA_QUALITY_FAILED'),('nan','DATA_QUALITY_FAILED'),('source','SOURCE_EXCLUDED')])
def test_ordinary_coverage_and_true_corruption_differ(tmp_path,change,disposition):
    s=Store(tmp_path);e=event()
    if change=='legacy':e['evidence'].pop('learning_context');e['evidence'].pop('data_hash')
    if change=='stale':e['evidence']['as_of']=(NOW-timedelta(minutes=10)).isoformat()
    if change=='future':e['evidence']['as_of']=NOW.isoformat()
    if change=='nan':e['evidence']['learning_context']['close']='NaN'
    if change=='source':e['evidence_category']='SYNTHETIC_ACCEPTANCE'
    ingest(s,e,NOW.isoformat())
    assert summary(s)['dispositions']=={disposition:1}
    assert s.db.execute('SELECT count(*) FROM market_observations').fetchone()[0]==0
    s.close()


def test_complete_plan_and_market_tasks_remain_separate(tmp_path):
    s=Store(tmp_path);e=event();e['evidence']['economics']=evidence()['economics']
    e['evidence'].update(technical_eligible=True,economic_eligible=True)
    ingest(s,e,NOW.isoformat());r=summary(s)
    assert r['unique_signals']==r['priced_plans']==1
    assert r['stages']=={'PRIMARY_ADMISSION_REJECTED':1}
    assert s.db.execute('SELECT status FROM observations').fetchone()[0]=='PENDING'
    assert s.db.execute('SELECT count(*) FROM market_observations').fetchone()[0]==1
    s.close()


def test_eligible_missing_plan_is_corrupt_but_zero_quantity_reject_is_normal(tmp_path):
    s=Store(tmp_path);e=event();e['evidence'].update(technical_eligible=True,economic_eligible=True)
    ingest(s,e,NOW.isoformat());assert summary(s)['dispositions']=={'DATA_QUALITY_FAILED':1}
    e['id']='empty-size';e['evidence']['economic_eligible']=False
    e['evidence']['economics']={'measurements':{'entry':{'vwap':'100'},'fillable_quantity':'0'}}
    ingest(s,e,NOW.isoformat());assert summary(s)['dispositions']=={'DATA_QUALITY_FAILED':1,'OBSERVED':1}
    assert summary(s)['priced_plans']==0
    s.close()


def test_market_no_future_features_or_missing_window_imputation():
    e=event();f=market_features(e);e['features']=f
    bars=candles();label=market_label(e,bars,240)
    altered=copy.deepcopy(bars);altered[47]['close']='101'
    assert market_features(e)==f
    assert market_label(e,altered,240)['path_hash']!=label['path_hash']
    with pytest.raises(ValueError,match='incomplete_future_window'):market_label(e,bars[2:],240)
    e['evidence']['learning_context']['regime']['timeframes']['15']['last_closed_at']=(NOW+timedelta(minutes=15)).isoformat()
    with pytest.raises(ValueError,match='future_timeframe_context'):market_features(e)


def test_market_training_insufficient_evidence_preserves_primary_and_legacy(tmp_path):
    s=Store(tmp_path);s.set('challenger',None);s.set('legacy_marker',{'preserved':True})
    report=tick(s,NOW.isoformat());assert report['status']=='INSUFFICIENT_EVIDENCE'
    assert report['primary_promotion'] is False
    assert report['cost_stress']=='NOT_APPLICABLE_WITHOUT_EXECUTABLE_PLAN'
    assert status(s,NOW.isoformat())['active_challenger'] is None
    assert s.get('legacy_marker')=={'preserved':True}
    s.close()


def market_samples(n=600):
    from autotrader.learning.lifecycle import MARKET_NAMES, MARKET_SCHEMA
    from test_v492_learning import sample
    rows=[]
    for i in range(n):
        r=sample(i);r['features'].update(schema=MARKET_SCHEMA,names=list(MARKET_NAMES),values=[r['features']['values'][0]]+[0.]*(len(MARKET_NAMES)-1))
        r['target']['mid_return']=r['target'].pop('net_return');r['target'].pop('net_r')
        rows.append(r)
    return rows


def test_market_chronology_embargo_sealed_holdouts_and_reproducibility(tmp_path):
    from autotrader.learning.features import stamp
    from autotrader.research.data import canonical, digest
    rows=market_samples();a=evaluate(rows,[]);b=evaluate(rows,[])
    assert digest(canonical(a))==digest(canonical(b))
    assert a['status']=='QUALIFIED_SHADOW'  # synthetic estimator acceptance only
    partitions=a['partition_ids'];indexed={r['id']:r for r in rows}
    for left,right in [('train','calibration'),('calibration','walk'),('walk','holdout')]:
        assert stamp(indexed[partitions[left][-1]]['target']['end_at'])+timedelta(hours=4)<stamp(indexed[partitions[right][0]]['observed_at'])
    sealed=[[a['holdout_start'],a['holdout_end']]]
    again=evaluate(market_samples(900),sealed,a['holdout_end'])
    if 'partition_ids' in again:
        assert not set(partitions['holdout']) & {i for values in again['partition_ids'].values() for i in values}
    s=Store(tmp_path);a['trained_at']=NOW.isoformat();identity=s.artifact(a);s.db.commit();s.close()
    s=Store(tmp_path);assert s.read_artifact(identity)==a
    path=s.root/'artifacts'/(identity+'.json');path.write_text('{}')
    with pytest.raises(ValueError,match='integrity'):s.read_artifact(identity)
    s.close()


def test_forward_market_degradation_quarantines_without_primary_authority(tmp_path):
    from autotrader.research.data import canonical
    s=Store(tmp_path);s.set('market_challenger','original-model')
    s.set('challenger','separate-plan-model')
    for r in market_samples(24):
        r['target']['positive']=0
        p={'model_id':'original-model','probability_mid_up':.99,'feature_drift_fraction':0}
        s.db.execute("INSERT INTO market_observations(id,observed_at,payload,status,result,prediction) VALUES (?,?,?,'LABELED',?,?)",(r['id'],r['observed_at'],'{}',canonical(r).decode(),canonical(p).decode()))
    assert status(s,NOW.isoformat())['active_challenger'] is None
    assert s.get('challenger')=='separate-plan-model'
    assert s.get('market_quarantine')['reason']=='forward_calibration_or_feature_drift'
    s.close()


def test_priced_legacy_coverage_is_not_confused_with_missing_execution_price(tmp_path):
    s=Store(tmp_path);e=event();e['evidence']['economics']=evidence()['economics']
    e['evidence'].update(technical_eligible=True,economic_eligible=True)
    e['evidence'].pop('learning_context');e['evidence'].pop('data_hash')
    ingest(s,e,NOW.isoformat())
    assert summary(s)['dispositions']=={'COVERAGE_EXCLUDED':1}
    assert summary(s)['coverage_reasons']=={'legacy_unbound_snapshot':1}
    s.close()


def test_published_current_counts_and_legacy_failures_have_explicit_scopes(tmp_path):
    from autotrader.learning.controller import ingest as old_ingest
    from autotrader.learning.controller import publish
    from test_v492_learning import event as old_event
    s=Store(tmp_path);legacy=old_event('old-unpriced');legacy['evidence']['economics']=None
    old_ingest(s,legacy,NOW.isoformat())
    e=event();ingest(s,e,NOW.isoformat());report=publish(s,NOW.isoformat())
    assert report['legacy_dataset']['counts']=={'DATA_QUALITY_FAILED':1}
    assert report['dataset']['counts']=={} and report['dataset']['coverage_failures']=={}
    assert report['funnel']['dispositions']=={'OBSERVED':1}
    assert report['rejection_reasons']=={}  # no fabricated gate from unavailable fields
    assert all('data-quality' not in w for w in report['warnings'])
    s.close()


def test_higher_timeframe_start_before_decision_is_not_proof_of_completion():
    from autotrader.learning.features import build
    e=event()
    # Fifteen-minute start is in the past, but its close is still in the future.
    e['evidence']['learning_context']['regime']['timeframes']['15']['last_closed_at']=(NOW-timedelta(minutes=5)).isoformat()
    with pytest.raises(ValueError,match='future_timeframe_context'):market_features(e)
    e=event();e['evidence']['learning_context']['regime']['timeframes']['240']={'trend':'BULLISH','last_closed_at':(NOW-timedelta(minutes=60)).isoformat()}
    with pytest.raises(ValueError,match='future_timeframe_context'):market_features(e)
    plan=evidence();plan['raoe_regime']['timeframes']['60']['last_closed_at']=(NOW-timedelta(minutes=5)).isoformat()
    with pytest.raises(ValueError,match='unavailable_context'):build(plan,'RAOE_TREND_PULLBACK',NOW.isoformat())
