"""Separate research cadence, quote admissibility and actual financial authority."""
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from autotrader.domain import OrderBookLevel
from autotrader.execution.quality import ExecutionQualityEngine
from autotrader.opportunity.economics import CostAssumptions, CostAwareOpportunityEngine
from autotrader.opportunity.engine import relative_strength
from autotrader.opportunity.sizing import quote_for_plan
from autotrader.opportunity.status import freshness, qualification
from autotrader.risk import RiskLimits
from test_v46_opportunities import setup_observation

NOW=datetime(2026,10,22,12,2,30,tzinfo=UTC)


def body():
    observed=NOW.replace(minute=0,second=10)
    return {'cycle_bucket':int(observed.timestamp())//300,'updated_at':observed.isoformat(),
        'evaluation_interval_seconds':300,'evaluation_grace_seconds':90,
        'rows':[{'quote_observed_at':observed.isoformat()}]}


def row(state='RUNNING',age=5,payload=None):
    return SimpleNamespace(state=state,reason='test_observation',updated_at=NOW-timedelta(seconds=age),payload_json=json.dumps(payload or {}))


def test_current_five_minute_research_does_not_authorize_stale_quotes():
    r=freshness(body(),'OBSERVED',NOW,{'worker':row(),'scanner':row('OK')},NOW)
    assert r['research_freshness']['current'] and r['research_freshness']['state']=='CURRENT'
    assert r['research_freshness']['age_seconds']==140
    assert r['market_freshness']['state']=='STALE_QUOTES' and not r['market_freshness']['execution_authorized']
    assert r['worker_health']['state']==r['scanner_health']['state']=='HEALTHY'
    assert freshness(body(),'OBSERVED',NOW,{},NOW.replace(minute=5,second=40))['research_freshness']['state']=='WAITING_NEXT_CANDLE'
    assert freshness(body(),'OBSERVED',NOW,{},NOW.replace(minute=6,second=31))['research_freshness']['state']=='DELAYED'


def test_failure_missing_recovery_partial_and_future_are_not_zero_opportunities():
    assert freshness({},'NOT_RECORDED',None,{},NOW)['research_freshness']['state']=='NOT_RECORDED'
    assert freshness(body(),'ERROR',NOW,{},NOW)['research_freshness']['state']=='FAILED'
    assert freshness(body(),'DEGRADED',NOW,{},NOW)['research_freshness']['state']=='PARTIAL'
    prior={**body(),'observer_process_id':1}
    r=freshness(prior,'OBSERVED',NOW,{'worker_instance':row(payload={'process_id':2})},NOW)
    assert r['worker_health']['state']=='RECOVERING' and r['research_freshness']['current']
    future={**body(),'updated_at':(NOW+timedelta(minutes=5)).isoformat()}
    assert not freshness(future,'OBSERVED',NOW,{},NOW)['research_freshness']['current']
    assert freshness(body(),'OBSERVED',NOW,{'scanner':row('DATA_UNAVAILABLE')},NOW)['scanner_health']['state']=='FAILED'


def test_observed_size_changes_depth_cost_and_gateway_agrees_on_target_scenario():
    pair,_,book=setup_observation()
    book=replace(book,bids=(OrderBookLevel(D('100.3'),D('.1')),OrderBookLevel(D('98'),D(10))))
    model=CostAwareOpportunityEngine(CostAssumptions(D(0),D(0),D(0)))
    options={'stop':D(99),'targets':(D('101.9'),D(104)),'atr':D(1),'plausible_target':D(110),'holding_bars':36}
    small=model.evaluate(pair,book,quote_budget=D(6),**options)
    large=model.evaluate(pair,book,quote_budget=D(75),**options)
    assert small.feasible and not large.feasible
    q=D(large.measurements['fillable_quantity'])
    execution=ExecutionQualityEngine().evaluate(pair,book,q,D(75),D(0),D(0),list(options['targets']))
    assert execution.target_net_scenarios==tuple(D(v) for v in large.measurements['conditional_target_net_eur'])
    assert execution.breakeven_bid==D(large.measurements['breakeven_bid'])
    assert 'first_target_destroyed_by_execution_costs' in execution.rejection_reasons


def test_sizing_preserves_reserve_risk_and_instrument_cap_without_granting_authority():
    pair,_,book=setup_observation()
    limits=RiskLimits(max_planned_loss_per_trade=D('.2'))
    quote,evidence=quote_for_plan(pair,book,D(99),cash=D(160),limits=limits)
    assert 0<quote<=10 and evidence['financial_risk_admission_required']
    quote,_=quote_for_plan(replace(pair,max_order_base=D('.02')),book,D(99),cash=D(500))
    assert quote<=D('.02')*book.best_ask
    assert quote_for_plan(pair,book,D(99),cash=D(150))[0]==0


@pytest.mark.parametrize('evidence,expected',[
    ({},'WATCH'),
    ({'pipeline':[{'stage':'DATA_VALIDATION','passed':False}]},'DATA_UNAVAILABLE'),({'data_errors':['stale']},'DATA_UNAVAILABLE'),
    ({'technical_eligible':True},'TECHNICAL_CANDIDATE'),
    ({'technical_eligible':True,'economics':{'measurements':{'estimates_available':True}},'economic_eligible':False},'COST_CONSTRAINED'),
    ({'technical_eligible':True,'economics':{'measurements':{'estimates_available':True}},'economic_eligible':True},'RESEARCH_CANDIDATE'),
])
def test_ranking_and_economics_never_imply_paper_authority(evidence,expected):
    assert qualification({**evidence,'score':'1'})==expected
    assert qualification(evidence,fill_count=1)=='EXECUTED_IN_SIMULATION'
    assert qualification(evidence,execution_rejected=True)=='REJECTED'


def test_relative_residual_normalization_requires_complete_synchronized_history():
    _,f,_=setup_observation()
    peers=[replace(f,symbol=s,metadata={**f.metadata,'return_20':'.01','return_60':'.02','recent_returns':['.0002','.0001']*10}) for s in ('BTC-EUR','ETH-EUR')]
    assert relative_strength(f,*peers,residual=True)['ready']
    bad=replace(peers[0],metadata={**peers[0].metadata,'recent_returns':[]})
    assert not relative_strength(f,bad,peers[1],residual=True)['ready']
    assert not relative_strength(f,*[replace(p,timestamp=p.timestamp+timedelta(minutes=5)) for p in peers],residual=True)['ready']


async def test_persisted_research_stays_current_between_candles_while_quotes_age(lab,monkeypatch):
    import asyncio

    from fastapi.testclient import TestClient

    import autotrader.api.v46 as api
    from autotrader.api.main import create_app
    from autotrader.persistence.models import SystemStateModel
    monkeypatch.setenv('DATABASE_URL',lab.official.test_database_url)
    monkeypatch.setenv('ENVIRONMENT','test');monkeypatch.setenv('DASHBOARD_PASSWORD','change-me')
    monkeypatch.setattr(api,'utc_now',lambda:NOW)
    payload={**body(),'rows':[{'symbol':'BTC-EUR','score':'.8','technical_eligible':True,'economic_eligible':True,
        'quote_observed_at':body()['updated_at'],'economics':{'measurements':{'estimates_available':True}}}],
        'technical_candidates':1,'economically_viable_candidates':1}
    async with lab.official.session_factory() as session,session.begin():
        session.add(SystemStateModel(key='opportunity_snapshot',state='OBSERVED',reason='completed',payload_json=json.dumps(payload),updated_at=NOW))
    def request():
        with TestClient(create_app()) as client:
            assert client.get('/api/opportunities').status_code==401
            data=client.get('/api/opportunities',auth=('admin','change-me')).json()
            assert not data['stale'] and data['research_freshness']['current']
            assert data['market_freshness']['state']=='STALE_QUOTES' and not data['market_freshness']['execution_authorized']
            assert data['rows'][0]['qualification_state']=='RESEARCH_CANDIDATE'
    await asyncio.to_thread(request)
    assert not await lab.official.list_orders() and not await lab.official.list_fills()


def test_new_breakout_hold_requires_completed_acceptance_and_can_expire():
    from autotrader.domain import Candle
    from autotrader.opportunity.patterns import replay
    start=NOW-timedelta(days=1)
    candles=[Candle('BTC-EUR',start+timedelta(minutes=5*i),D(100),D(101),D(99),D(100),D(100),'5m','synthetic') for i in range(25)]
    candles.append(replace(candles[-1],timestamp=candles[-1].timestamp+timedelta(minutes=5),open=D(100),high=D(103),low=D(100),close=D(102),volume=D(200)))
    for i in (1,2):
        candles.append(replace(candles[-1],timestamp=candles[-1].timestamp+timedelta(minutes=5),open=D('102.4'),high=D(104),low=D(103),close=D('103.5'),volume=D(110)))
    # Fix OHLC validity while keeping price above the retest band.
    candles[-2]=replace(candles[-2],open=D('103.2'));candles[-1]=replace(candles[-1],open=D('103.3'))
    assert replay(candles[:-1],compression_width=D('.03'),hold_bars=2).stage=='RETEST_PENDING'
    new=replay(candles,compression_width=D('.03'),hold_bars=2)
    old=replay(candles,compression_width=D('.03'),hold_bars=0)
    assert new.stage=='CONFIRMED' and new.reason=='resistance_accepted_without_deep_retest'
    assert old.stage=='RETEST_PENDING'
    for _ in range(9):candles.append(replace(candles[-1],timestamp=candles[-1].timestamp+timedelta(minutes=5)))
    assert replay(candles,compression_width=D('.03'),hold_bars=0).stage!='CONFIRMED'


def test_comparison_summary_preserves_financial_metrics_and_omits_heavy_training_payload():
    from autotrader.api.v46 import comparison_summary
    report={'schema':'comparison/4.6-rc2','baseline':{'A3':{'trades':2,'net_profit':-1,'curve':[1,2,3]}},
        'successors':{'A3':{'status':'UNVALIDATED','parameters':{'target_atr':'2'},'test':{'trades':1,'net_profit':-.5,'fills':[{'fill_id':'raw'}]},'training':{'grid':[1,2,3]}}}}
    summary=comparison_summary(report)
    assert summary['baseline']['A3']=={'trades':2,'net_profit':-1}
    assert summary['successors']['A3']['test']=={'trades':1,'net_profit':-.5}
    assert 'training' not in summary['successors']['A3'] and 'details_omitted' in summary
    assert report['successors']['A3']['training']['grid']==[1,2,3]


def test_wider_spread_cannot_be_misreported_as_technical_price_chasing():
    from autotrader.opportunity.engine import SuccessorOpportunityEngine, SuccessorParameters
    pair,f,book=setup_observation()
    f=replace(f,atr=D('.2'),ema_9=D('100.2'),ema_21=D('100.2'),ema_50=D(100),spread_bps=D(60),
        metadata={**f.metadata,'last_low':'100.1'})
    book=replace(book,bids=(OrderBookLevel(D(100),D(1000)),),asks=(OrderBookLevel(D('100.6'),D(1000)),))
    corrected=SuccessorOpportunityEngine().evaluate('A3_COST_AWARE_CONTINUATION',f,pair,book)
    original=SuccessorOpportunityEngine(SuccessorParameters(entry_reference='ASK')).evaluate('A3_COST_AWARE_CONTINUATION',f,pair,book)
    assert corrected.evidence['technical_eligible'] and not corrected.evidence['economic_eligible']
    assert 'spread_too_wide' in corrected.evidence['reasons']
    assert original.evidence['conditions']['entry_not_chased'] is False
    assert corrected.evidence['conditions']['entry_not_chased'] is True
