"""Evidence categories and non-destructive lifecycle invariants."""
import importlib.util
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from autotrader.domain import utc_now
from autotrader.raoe.analytics import classify, episodes
from test_v48_raoe import fixture


def test_touching_uneconomic_target_cannot_be_a_missed_profit_or_correct_rejection():
    bars,now,*_=fixture()
    event={'observed_at':now.isoformat(),'horizon_seconds':600,'accepted':False,
        'evidence':{'economic_eligible':False,'entry_plan':{'entry':'193','stop':'190','targets':['193.01']}}}
    path=[replace(bars[-1],timestamp=now+timedelta(minutes=5*i),low=D(192),high=D(199)) for i in range(2)]
    r=classify(event,path)
    assert r['classification']=='INCONCLUSIVE'
    assert r['price_path_observation']['first_barrier']=='TARGET'
    assert r['modeled_paper_execution']['status']=='MISSING_EVIDENCE'
    assert r['actual_prospective_paper_trade']['status']=='NOT_ESTABLISHED'
    assert not r['profitability_proven']


def test_pepe_signals_across_strategies_and_overlapping_horizons_are_one_episode():
    events=[]
    for hour,strategy in [('2026-10-27T22:41:08+00:00','RAOE_TREND_PULLBACK'),('2026-10-28T01:25:25+00:00','RAOE_EARLY_RECOVERY')]:
        events.append({'event_id':strategy,'observed_at':hour,'strategy_id':strategy,'symbol':'PEPE-EUR',
            'horizon_seconds':21600,'evidence':{'entry_eligible':False}})
    r=episodes(list(reversed(events)))
    assert len(r)==1 and r[0]['signal_count']==2 and len(r[0]['strategies'])==2
    assert r[0]['first_actionable_observation'] is None and not r[0]['independent_win']
    events.append({**events[0],'observed_at':'2026-10-28T05:00:00+00:00'})
    assert len(episodes(events))==2


async def test_flat_archival_releases_capacity_without_deleting_ledger_or_rebinding_manifest(lab):
    from autotrader.raoe import IDENTITIES
    original=[]
    for index in range(8):
        record=await lab.create('v49-old-'+str(index),'Retained '+str(index),IDENTITIES[index%4])
        repo=await lab.repository(record['experiment_id'])
        original.append((record,await repo.snapshot(),await repo.list_orders(),await repo.list_fills()))
    with pytest.raises(ValueError,match='bounded_shadow_limit'):await lab.create('overflow','Overflow',IDENTITIES[0])
    for record,_,_,_ in original:
        with pytest.raises(ValueError,match='pause_or_stop_before_archiving'):await lab.archive(record['experiment_id'])
        await lab.control(record['experiment_id'],'pause')
        result=await lab.archive(record['experiment_id'])
        assert result['history_preserved'] and result['slot_released']
        assert await lab.archive(record['experiment_id'])==result
        with pytest.raises(ValueError,match='archived_experiment_cannot_resume'):await lab.control(record['experiment_id'],'resume')
    new=await lab.create('v49-new','Independent successor',IDENTITIES[-1])
    assert new['manifest']['exit_policy']['holding_seconds']==14400
    assert len(await lab.records())==9
    for record,before,orders,fills in original:
        detail=await lab.detail(record['experiment_id'])
        repo=await lab.repository(record['experiment_id'])
        assert detail['manifest']==record['manifest'] and detail['archived_at']
        assert detail['portfolio']['cash']==before['cash']
        assert await repo.list_orders()==orders and await repo.list_fills()==fills
        assert await repo.verify_invariants(D(500))==[]
    assert D((await lab.official.snapshot())['cash'])==500


def diagnostic_module():
    spec=importlib.util.spec_from_file_location('diag',Path('scripts/v49_diagnostic_remote.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_collector_redacts_credentials_and_uses_only_read_only_sql(monkeypatch):
    m=diagnostic_module()
    clean=m.sanitize({'password':'secret','nested':{'api_key':'ABC','message':'postgresql://user:pass@host/db'},'raw':'Bearer ABC','pem':'-----BEGIN PRIVATE KEY-----'})
    assert 'secret' not in str(clean) and 'pass@' not in str(clean) and 'ABC' not in str(clean) and 'PRIVATE KEY' not in str(clean)
    calls=[]
    monkeypatch.setattr(m,'run',lambda args:(calls.append(args) or '{}'))
    assert m.query('scoped-pg','autotrader_aruba_staging','SELECT json_build_object()')=={}
    assert 'REPEATABLE READ READ ONLY' in calls[0][-1] and 'ON_ERROR_STOP=1' in calls[0]
    with pytest.raises(ValueError):m.query('scoped-pg','unrelated','SELECT 1')
    with pytest.raises(ValueError):m.collect(49)


def test_v49_production_preflight_stays_forbidden(tmp_path):
    spec=importlib.util.spec_from_file_location('release49',Path('deploy/release.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    (tmp_path/'pyproject.toml').write_text('[project]\nversion="4.9.0.dev1"\n')
    with pytest.raises(ValueError,match='staging-only'):m.verify_release_preflight(tmp_path)


async def test_assessment_drains_oldest_backlog_beyond_100_and_preserves_original_reviews(pg_repo):
    import json

    from sqlalchemy import func, select

    from autotrader.persistence.models import SystemStateModel
    from autotrader.raoe.analytics import assess_due
    await pg_repo.initialize_portfolio(D(500))
    now=utc_now()
    async with pg_repo.session_factory() as session,session.begin():
        for index in range(150):
            suffix=f'{index:048x}';stamp=now-timedelta(hours=7,minutes=index)
            event={'observed_at':stamp.isoformat(),'horizon_seconds':600,'symbol':'TEST-EUR',
                'evidence':{'entry_plan':{'entry':'100','stop':'98','targets':['110']}},'accepted':False}
            session.add(SystemStateModel(key='raoe_event:'+suffix,state='RECORDED',payload_json=json.dumps(event),created_at=stamp))
        session.add(SystemStateModel(key='raoe_outcome:'+f'{149:048x}',state='ASSESSED',payload_json='{"legacy":"unchanged"}'))
    await assess_due(pg_repo,limit=12)
    await assess_due(pg_repo,limit=12)
    async with pg_repo.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(SystemStateModel).where(SystemStateModel.key.like('raoe49_outcome:%')))==24
        assert await session.get(SystemStateModel,'raoe49_outcome:'+f'{149:048x}')
        assert (await session.get(SystemStateModel,'raoe_outcome:'+f'{149:048x}')).payload_json=='{"legacy":"unchanged"}'


def test_conflicting_bar_versions_cannot_establish_a_favorable_outcome():
    bars,now,*_=fixture()
    event={'observed_at':now.isoformat(),'horizon_seconds':600,'accepted':False,
        'evidence':{'economic_eligible':True,'entry_plan':{'entry':'193','stop':'190','targets':['195']}}}
    path=[replace(bars[-1],timestamp=now+timedelta(minutes=5*i),low=D(192),high=D(199)) for i in range(2)]
    result=classify(event,[*path,replace(path[0],high=D(194))])
    assert result['classification']=='MISSING_EVIDENCE' and result['price_path_observation']['status']=='CONFLICTING_MARKET_DATA'
