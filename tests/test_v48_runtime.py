"""Real PostgreSQL ledger and runtime tests with synthetic observations only."""
import asyncio
import json
from dataclasses import replace
from decimal import Decimal as D

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from autotrader.api.main import create_app
from autotrader.domain import utc_now
from autotrader.market_data.service import MarketDataService, ValidatedMarket
from autotrader.persistence.models import JournalEventModel, ShadowExperimentModel, SystemStateModel
from autotrader.personal_paper.runtime import PersonalPaperRuntime
from autotrader.scanner import ScanCandidate
from test_v47_paper import paper as paper_fixture
from test_v48_raoe import (
    causal_clock,  # noqa: F401 - registers the autouse replay clock fixture
    fixture,
)

paper=paper_fixture


def candidates():
    bars,_now,peers,pair,book,f=fixture()
    _,metrics=MarketDataService(None).validate_order_book(book)
    result=[ScanCandidate(ValidatedMarket(pair,bars,book,metrics,f.data_quality,[]),f,[],None,None,D(1))]
    for symbol,rows in peers.items():
        from autotrader.indicators import calculate_features
        p=replace(pair,symbol=symbol,base_asset=symbol.split('-')[0])
        b=replace(book,symbol=symbol)
        feature=calculate_features(rows[-240:],D(0),D(1))
        result.append(ScanCandidate(ValidatedMarket(p,rows,b,metrics,feature.data_quality,[]),feature,[],None,None,D(1)))
    return result


async def test_raoe_ledger_entry_restart_duplicate_and_protective_stop(paper):
    service,repo=paper
    observations=candidates()
    class Feed(MarketDataService):
        def __init__(self): super().__init__(None)
        async def get_position_book(self,pair):
            return replace(next(c.market.order_book for c in observations if c.market.pair.symbol==pair.symbol),timestamp=utc_now())
        async def resolve_pair(self,symbol):return next(c.market.pair for c in observations if c.market.pair.symbol==symbol)
    market=Feed();runtime=PersonalPaperRuntime(service,market,'raoe-pg')
    await runtime.scan(observations)
    fills=await repo.list_fills()
    assert len(fills)==1,(await service.detail())['scan']
    position=next(p for p in await repo.list_positions() if p.quantity>0)
    assert position.symbol=='TEST-EUR'
    await runtime.scan(observations)
    assert len(await repo.list_fills())==1
    await service.close();repo=await service.repository()
    runtime=PersonalPaperRuntime(service,market,'raoe-pg')
    await runtime.scan(observations)
    assert len(await repo.list_fills())==1
    from autotrader.persistence.models import ExitPlanModel
    async with repo.session_factory() as db:
        plan=await db.scalar(select(ExitPlanModel).where(ExitPlanModel.position_id==position.position_id))
        metadata=json.loads(plan.settings_json)
        assert metadata['target_semantics']=='MINIMUM_NET_UNIT_EXIT_PROCEEDS'
        supported_bid=D(metadata['original_bid_targets'][0])
        assert D(metadata['net_unit_targets'][0])==position.take_profit_targets[0]
    from autotrader.domain import OrderBookLevel
    class TargetFeed(Feed):
        async def get_position_book(self,pair):
            b=await super().get_position_book(pair)
            return replace(b,bids=(OrderBookLevel(supported_bid,D(10000)),),asks=(OrderBookLevel(supported_bid+D('.01'),D(10000)),))
    runtime.market=TargetFeed()
    await runtime.monitor()
    assert len(await repo.list_fills())==2
    assert next(p for p in await repo.list_positions() if p.position_id==position.position_id).quantity<position.quantity
    async with repo.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(JournalEventModel).where(JournalEventModel.event_type=='INITIAL_FUNDING'))==1
        events=(await db.scalars(select(SystemStateModel).where(SystemStateModel.key.like('raoe_event:%')))).all()
        assert events and json.loads(events[0].payload_json)['evidence']['estimated_edge']=='UNKNOWN'
    await repo.set_control('pause')
    class StopFeed(Feed):
        async def get_position_book(self,pair):
            b=await super().get_position_book(pair)
            return replace(b,bids=(OrderBookLevel(position.initial_stop*D('.99'),D(10000)),),asks=(OrderBookLevel(position.initial_stop,D(10000)),))
    runtime.market=StopFeed()
    await runtime.monitor()
    assert len(await repo.list_fills())==3
    assert all(p.quantity==0 for p in await repo.list_positions())
    assert await repo.verify_invariants(D(7000))==[]
    from autotrader.persistence.models import OrderModel
    async with repo.session_factory() as db:
        sells=(await db.scalars(select(OrderModel).where(OrderModel.side=='SELL'))).all()
        assert sells and all(json.loads(o.execution_json)['strategy_id']=='RAOE_EARLY_RECOVERY' for o in sells)


async def test_monitoring_creating_projection_and_authenticated_intelligence(pg_repo,monkeypatch):
    from autotrader.config import Settings
    from autotrader.shadow.lab import ShadowLab
    await pg_repo.initialize_portfolio(D(500))
    lab=ShadowLab(pg_repo,Settings(database_url=pg_repo.test_database_url,environment="test",shadow_enabled=True,_env_file=None))
    monkeypatch.setenv('DATABASE_URL',lab.official.test_database_url)
    monkeypatch.setenv('ENVIRONMENT','test');monkeypatch.setenv('SHADOW_ENABLED','true')
    monkeypatch.setenv('DASHBOARD_PASSWORD','change-me')
    async with lab.official.session_factory() as session,session.begin():
        session.add(ShadowExperimentModel(experiment_id='creating-raoe',request_id='creating-raoe',name='Synthetic incomplete provision',
            state='CREATING',database_name='autotrader_shadow_not_provisioned',manifest_json=json.dumps({'strategy_id':'RAOE_EARLY_RECOVERY','strategy_version':'4.8.0-raoe.1'})))
    def read():
        with TestClient(create_app()) as client:
            assert client.get('/api/intelligence').status_code==401
            response=client.get('/api/monitoring/summary',auth=('admin','change-me'))
            assert response.status_code==200,response.text
            assert response.json()['shadows'][0]['reconciliation']['status']=='NOT_CHECKED'
            assert client.get('/api/intelligence',auth=('admin','change-me')).json()['read_only']
            assert client.get('/api/intelligence?limit=101',auth=('admin','change-me')).status_code==422
    try:
        await asyncio.to_thread(read)
    finally:
        await lab.close()


def test_missed_path_is_hypothetical_and_both_barriers_use_stop_first():
    from datetime import timedelta

    from autotrader.raoe.analytics import classify
    bars,now,_,_,_,_=fixture()
    event={'observed_at':now.isoformat(),'horizon_seconds':600,'accepted':False,
        'evidence':{'entry_plan':{'stop':'190','targets':['195']}}}
    future=[replace(bars[-1],timestamp=now+timedelta(minutes=5*i),low=D(189),high=D(199)) for i in range(2)]
    result=classify(event,future)
    assert result['classification']=='CORRECT_REJECTION' and result['ambiguous_stop_and_target']
    future=[replace(c,low=D(191)) for c in future]
    assert classify(event,future)['classification']=='POTENTIAL_FAVORABLE_MOVE_NOT_PROVEN_EXECUTABLE'
    assert classify(event,future[:1])['classification']=='MISSING_MARKET_DATA'


async def test_raoe_shadow_has_independent_funding_and_durable_restart(lab):
    from autotrader.raoe import IDENTITIES
    from autotrader.risk import RiskEngine, RiskLimits
    from autotrader.shadow.runtime import ShadowRuntime
    record=await lab.create('raoe-first','Synthetic RAOE forward lifecycle',IDENTITIES[0])
    repo=await lab.repository(record['experiment_id'])
    observations=candidates()
    market=MarketDataService(None)
    runtime=ShadowRuntime(lab,market,RiskEngine(RiskLimits()),'raoe-shadow')
    await runtime.scan(observations,successors_only=True)
    assert len(await repo.list_fills())==1
    await runtime.scan(observations,successors_only=True)
    assert len(await repo.list_fills())==1
    assert await repo.verify_invariants(D(500))==[]
    assert D((await lab.official.snapshot())['cash'])==500
    async with repo.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(JournalEventModel).where(JournalEventModel.event_type=='INITIAL_FUNDING'))==1
    # Reopen the domain and replay; its original cash and identity survive.
    await lab.close()
    repo=await lab.repository(record['experiment_id'])
    await ShadowRuntime(lab,market,RiskEngine(RiskLimits()),'raoe-shadow').scan(observations,successors_only=True)
    assert len(await repo.list_fills())==1 and await repo.verify_invariants(D(500))==[]
