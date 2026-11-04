"""Isolated tests only: no exchange requests, server access or financial databases."""
from dataclasses import replace
import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker

from autotrader.perpetuals.micro.types import Book,Ticker
from autotrader.perpetuals.multi.contracts import Contract,Tier,liquidation,maintenance,parse_tiers
from autotrader.perpetuals.multi.economics import plan
from autotrader.perpetuals.multi.ledger import MultiLedger,Refused,reconcile,equity
from autotrader.perpetuals.multi.market import MultiMarket
from autotrader.perpetuals.multi.models import Base,MultiState,MultiEvent
from autotrader.perpetuals.multi.policy import D,COHORTS,encode,digest,initial_state
from autotrader.perpetuals.multi.scanner import map_universe,screen
from autotrader.perpetuals.multi.strategies import Signal

NOW=1_800_000_000_000


def contract(symbol='SOLUSDT',maintenance_rate='.005'):
    return Contract(symbol,symbol.removesuffix('USDT'),D('.001'),D('.001'),D(5),D(1000),D('.01'),
                    D(1),D(20),D(1),480,(Tier(D(100000),D(maintenance_rate),D(0),D(20)),),NOW)


def observation(at=NOW,mid='100'):
    price=D(mid)
    return (Book(at,at,((price-D('.01'),D(1000)),),((price+D('.01'),D(1000)),),at),
            Ticker(at,at,price,at+480*60_000,D('.0001')))


def signal(side=1,symbol='SOLUSDT',cutoff=NOW):
    return Signal(digest([symbol,side,cutoff]),symbol,'MULTI_CONTINUATION_V1',side,cutoff,NOW,
                  D(100),D(100)*(1-side*D('.0015')),D(100)*(1+side*D('.007')),15,'TREND_UP',
                  'features',{'atr_fraction':D('.0007'),'forecast_signed_move_fraction':D('.007')},())


@pytest.fixture
async def ledger(tmp_path,monkeypatch):
    monkeypatch.setattr('autotrader.perpetuals.multi.ledger.clock_ms',lambda:NOW)
    engine=create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'multi.sqlite'))
    async with engine.begin() as connection:await connection.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async with factory() as session,session.begin():session.add(MultiState(id=1,generation=0,payload=None))
    ledger=MultiLedger(factory)
    assert await ledger.acquire('worker')
    await ledger.control(True)
    yield ledger
    await engine.dispose()


def plans(s=None,c=None):
    s=s or signal();c=c or contract();book,ticker=observation()
    return [plan(s,n,D(1000),D(1000),c,book,ticker,NOW) for n in COHORTS]


async def open_matched(ledger,s=None):
    s=s or signal();assert await ledger.reserve('worker',s.payload(),plans(s),contract())
    assert await ledger.fill('worker',s.id,*observation())
    return (await ledger.load())[1]


def test_contract_specific_margin_and_roundtrip():
    low,high=contract(),contract(maintenance_rate='.02')
    p={'side':1,'quantity':'1','entry':'100','margin':'10','funding':'0'}
    assert liquidation(high,p)>liquidation(low,p)
    assert maintenance(high,D(1),D(100))>maintenance(low,D(1),D(100))
    assert Contract.restore(json.loads(encode(low.payload())))==low
    short={**p,'side':-1}
    assert liquidation(high,short)<liquidation(low,short)


def test_contract_margin_units_and_leverage():
    def row(im,mm):return {'symbol':'SOLUSDT','initialMargin':im,'maintenanceMargin':mm,
                            'maxLeverage':'20','riskLimitValue':'100000','mmDeduction':'0'}
    assert parse_tiers([row('.05','.005')],'SOLUSDT')==parse_tiers([row('5','.5')],'SOLUSDT')
    with pytest.raises(ValueError):parse_tiers([row('7','.5')],'SOLUSDT')
    with pytest.raises(ValueError):contract().validate_size(D('.0011'),D(100),10)
    with pytest.raises(ValueError):contract().validate_size(D(1),D(100),30)


@pytest.mark.parametrize('side',[1,-1])
def test_cost_qualified_matched_plans_and_correct_roi(side):
    rows=plans(signal(side=side))
    assert [p['leverage'] for p in rows]==[1,3,10]
    for p in rows:
        assert D(p['scenario_gain'])>0 and D(p['planned_loss'])<=5
        assert D(p['net_target_margin_roi_pct'])>D(p['net_target_account_roi_pct'])
        assert p['expected_net_pnl_usdt'] is None
        assert D(p['margin_estimate'])<=D(250)
    tiny=replace(signal(side=side),target=D(100)*(1+side*D('.002')))
    with pytest.raises(ValueError):plans(tiny)


async def test_atomic_matched_fill_restart_idempotency_and_cash_journal(ledger):
    s=signal();state=await open_matched(ledger,s)
    assert len(state['positions'])==3 and not state['intents']
    again=MultiLedger(ledger.factory)
    assert not await again.fill('worker',s.id,*observation())
    assert not await again.reserve('worker',s.payload(),plans(),contract())
    reconcile((await again.load())[1])
    async with ledger.factory() as session:
        events=[json.loads(e) for e in (await session.scalars(select(MultiEvent.payload))).all()]
    for n in COHORTS:
        posted=sum((D(e.get('cash_delta','0')) for e in events if e.get('cohort')==str(n)),D(0))
        assert posted==D(state['accounts'][str(n)]['cash'])


async def test_reservation_pause_and_expiry_return_collateral(ledger,monkeypatch):
    s=signal();assert await ledger.reserve('worker',s.payload(),plans(),contract())
    monkeypatch.setattr('autotrader.perpetuals.multi.ledger.clock_ms',lambda:NOW+4000)
    assert await ledger.expire('worker')==3
    state=(await ledger.load())[1]
    assert not state['intents'] and all(D(a['cash'])==1000 for a in state['accounts'].values())
    assert not await ledger.fill('worker',s.id,*observation(NOW+4000))
    await ledger.control(False)
    with pytest.raises(Refused):await ledger.reserve('worker',signal(cutoff=NOW+1).payload(),plans(),contract())


@pytest.mark.parametrize('side,exit_mid',[(1,'101'),(-1,'99')])
async def test_signed_exit_funding_fees_and_full_reconciliation(ledger,monkeypatch,side,exit_mid):
    state=await open_matched(ledger,signal(side=side))
    monkeypatch.setattr('autotrader.perpetuals.multi.ledger.clock_ms',lambda:NOW+1000)
    for key,p in state['positions'].items():
        await ledger.exit_intent('worker',key,'TARGET')
        await ledger.quote_exit('worker',key,*observation(NOW+1000,exit_mid))
        with pytest.raises(Refused):await ledger.settle_exit('worker',key)
        await ledger.settle_funding('worker',key,{},NOW+1000)
        assert await ledger.settle_exit('worker',key)
        assert not await ledger.settle_exit('worker',key)
    state=(await ledger.load())[1];reconcile(state)
    assert not state['positions']
    for a in state['accounts'].values():assert D(a['cash'])>1000 and a['closed']==1 and D(a['fees'])>0


async def test_funding_missing_blocks_settlement_and_signed_exactly_once(ledger,monkeypatch):
    state=await open_matched(ledger);key=next(iter(state['positions']))
    due=state['positions'][key]['next_funding_at']
    # Renewing is an ownership operation, not replaying any financial event.
    monkeypatch.setattr('autotrader.perpetuals.multi.ledger.clock_ms',lambda:due)
    assert await ledger.acquire('worker')
    with pytest.raises(Refused):await ledger.settle_funding('worker',key,{},due)
    await ledger.settle_funding('worker',key,{due:(D('.001'),D(100))},due)
    p=(await ledger.load())[1]['positions'][key]
    assert D(p['funding'])==-D(p['quantity'])*D('.1')
    await ledger.settle_funding('worker',key,{due:(D('.001'),D(100))},due)
    assert (await ledger.load())[1]['positions'][key]['funding']==p['funding']


async def test_liquidation_forfeits_only_collateral_and_records_gap(ledger,monkeypatch):
    state=await open_matched(ledger);key=next(k for k,p in state['positions'].items() if p['leverage']==10)
    monkeypatch.setattr('autotrader.perpetuals.multi.ledger.clock_ms',lambda:NOW+1000)
    await ledger.exit_intent('worker',key,'LIQUIDATION',stress_price=D(80))
    await ledger.quote_exit('worker',key,*observation(NOW+1000,'80'))
    await ledger.settle_funding('worker',key,{},NOW+1000)
    assert await ledger.settle_exit('worker',key)
    state=(await ledger.load())[1];reconcile(state)
    assert D(state['accounts']['10']['cash'])>=0 and state['accounts']['10']['liquidations']==1
    async with ledger.factory() as session:
        e=json.loads((await session.scalar(select(MultiEvent.payload).where(MultiEvent.event_key=='close:'+key))))
    assert e['planned_risk_exceeded'] and D(e['settlement_adjustment'])>0


async def test_preintent_or_stale_depth_never_fills(ledger):
    s=signal();assert await ledger.reserve('worker',s.payload(),plans(),contract())
    with pytest.raises(ValueError):await ledger.fill('worker',s.id,*observation(NOW-1))
    assert len((await ledger.load())[1]['intents'])==3


def test_universe_exact_mapping_no_multiplier_guessing_and_fair_revisit():
    rows={'ETHUSDT':{'symbol':'ETHUSDT','baseCoin':'ETH','quoteCoin':'USDT','settleCoin':'USDT',
                    'status':'Trading','contractType':'LinearPerpetual'},
          '1000PEPEUSDT':{'symbol':'1000PEPEUSDT','baseCoin':'1000PEPE','quoteCoin':'USDT','settleCoin':'USDT',
                         'status':'Trading','contractType':'LinearPerpetual'}}
    mapped,rejected=map_universe({'ETH':['ETH-EUR'],'PEPE':['PEPE-EUR']},rows)
    assert [r['symbol'] for r in mapped]==['ETHUSDT'] and rejected[0]['base']=='PEPE'
    mappings=[{'symbol':f'A{i}USDT','base':f'A{i}'} for i in range(10)]
    tickers=[{'symbol':r['symbol'],'bid1Price':'99.99','ask1Price':'100.01','turnover24h':str(10_000_000-i*10000),
              'highPrice24h':'102','lowPrice24h':'98'} for i,r in enumerate(mappings)]
    selected,_,_=screen(mappings,tickers,NOW,{'revisits':{r['symbol']:(0 if i==9 else NOW) for i,r in enumerate(mappings)}},batch=4)
    assert 'A9USDT' in {r['symbol'] for r in selected}


async def test_public_catalog_paginates_and_private_endpoints_forbidden():
    calls=[]
    def handler(request):
        calls.append(request)
        cursor=request.url.params.get('cursor')
        return httpx.Response(200,json={'retCode':0,'time':NOW,'result':{'category':'linear',
            'list':[{'symbol':'ETHUSDT' if not cursor else 'SOLUSDT'}],'nextPageCursor':'p2' if not cursor else ''}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        market=MultiMarket(client,client)
        rows=await market.pages('instruments-info')
        assert len(rows)==2 and calls[1].url.params['cursor']=='p2'
        with pytest.raises(ValueError):await market.get('order/create')


async def test_two_assets_share_cohort_limits_without_mixing_balances(ledger):
    await open_matched(ledger)
    s=signal(side=-1,symbol='ETHUSDT')
    assert await ledger.reserve('worker',s.payload(),plans(s,contract('ETHUSDT')),contract('ETHUSDT'))
    assert await ledger.fill('worker',s.id,*observation())
    state=(await ledger.load())[1];reconcile(state)
    assert len(state['positions'])==6 and {p['symbol'] for p in state['positions'].values()}=={'SOLUSDT','ETHUSDT'}
    third=signal(symbol='SOLUSDT',cutoff=NOW+1)
    with pytest.raises(Refused):await ledger.reserve('worker',third.payload(),plans(third),contract())


async def test_full_runtime_durable_quote_then_monitor_settle(ledger,monkeypatch):
    from autotrader.perpetuals.multi.runtime import MultiRuntime
    s=signal()
    monkeypatch.setattr('autotrader.perpetuals.multi.runtime.generate',lambda *args:[s])
    monkeypatch.setattr('autotrader.perpetuals.multi.runtime.clock_ms',lambda:NOW)
    class Market:
        calls=0
        price='100'
        at=NOW
        async def contract(self,*args,**kwargs):return contract()
        async def bars(self,*args,**kwargs):
            from autotrader.perpetuals.market import Bar, MINUTE
            return {NOW-i*MINUTE:Bar(NOW-i*MINUTE,D(100),D('100.01'),D('99.99'),D(100),D(50))
                    for i in range(1,92)}
        async def observation(self,*args,**kwargs):
            self.calls+=1
            state=(await ledger.load())[1]
            if self.calls==2:assert len(state['intents'])==3  # committed BEFORE fetching the fill book
            return observation(self.at,self.price)
    market=Market();runtime=MultiRuntime(ledger,market,owner='worker')
    row=await runtime.detailed({'symbol':'SOLUSDT'})
    assert row['status']=='PAPER_FILLED'
    assert len((await ledger.load())[1]['positions'])==3
    market.price='101';market.at=NOW+1000
    monkeypatch.setattr('autotrader.perpetuals.multi.runtime.clock_ms',lambda:NOW+1000)
    monkeypatch.setattr('autotrader.perpetuals.multi.ledger.clock_ms',lambda:NOW+1000)
    await runtime.monitor_once()
    state=(await ledger.load())[1];reconcile(state)
    assert not state['positions'] and all(D(a['cash'])>1000 for a in state['accounts'].values())
    await runtime.monitor_once()
    assert all(a['closed']==1 for a in (await ledger.load())[1]['accounts'].values())


async def test_journal_detects_balanced_state_tamper(ledger):
    async with ledger.factory() as session,session.begin():
        row=await session.get(MultiState,1);state=json.loads(row.payload)
        state['accounts']['1']['cash']='1001';state['accounts']['1']['realized']='1'
        row.payload=encode(state)
    with pytest.raises(Refused,match='cash_journal'):await ledger.acquire('worker')


async def test_competing_restarts_never_double_fill(ledger):
    import asyncio
    s=signal();await ledger.reserve('worker',s.payload(),plans(),contract())
    results=await asyncio.gather(*(MultiLedger(ledger.factory).fill('worker',s.id,*observation()) for _ in range(3)))
    assert sum(results)==1
    assert len((await ledger.load())[1]['positions'])==3


async def test_independent_additive_migration_in_temporary_database(tmp_path):
    import asyncio
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    url='sqlite+aiosqlite:///'+str(tmp_path/'migration.sqlite')
    config=Config();config.attributes['database_url']=url
    config.set_main_option('script_location',str(Path(__file__).resolve().parents[1]/'alembic/perpetuals_multi'))
    await asyncio.to_thread(command.upgrade,config,'head')
    engine=create_async_engine(url)
    async with engine.connect() as c:
        tables=await c.run_sync(lambda conn:inspect(conn).get_table_names())
    assert set(tables)=={'paper_multi_state','paper_multi_events','paper_multi_signals','paper_multi_scan','paper_multi_schema_version'}
    assert 'paper_perp_state' not in tables and 'alembic_version' not in tables
    await engine.dispose()


async def test_authenticated_api_feature_gate_and_history_pagination(ledger,monkeypatch):
    from fastapi import FastAPI,HTTPException,Request
    from autotrader.api.perpetuals_multi import install
    from autotrader.config import Settings
    app=FastAPI()
    async def auth(request:Request):
        if request.headers.get('authorization')!='Basic unit-test':raise HTTPException(401,'required')
    install(app,ledger,Settings(environment='local',_env_file=None),auth)
    monkeypatch.setenv('PAPER_MULTI_PERPETUALS_ENABLED','false')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://isolated') as client:
        assert (await client.get('/api/perpetuals/multi')).status_code==401
        h={'authorization':'Basic unit-test'}
        response=await client.get('/api/perpetuals/multi',headers=h)
        assert response.status_code==200 and response.json()['real_orders_enabled'] is False
        assert (await client.post('/api/perpetuals/multi/entries',headers=h,json={'enabled':True})).status_code==409
        first=(await client.get('/api/perpetuals/multi/history?limit=2',headers=h)).json()
        second=(await client.get('/api/perpetuals/multi/history?limit=2&cursor='+str(first['next_cursor']),headers=h)).json()
        assert set(r['id'] for r in first['rows']).isdisjoint(r['id'] for r in second['rows'])


@pytest.mark.parametrize('side',[1,-1])
async def test_funding_sign_for_each_direction(ledger,monkeypatch,side):
    state=await open_matched(ledger,signal(side=side));key=next(iter(state['positions']))
    due=state['positions'][key]['next_funding_at']
    monkeypatch.setattr('autotrader.perpetuals.multi.ledger.clock_ms',lambda:due)
    await ledger.acquire('worker')
    await ledger.settle_funding('worker',key,{due:(D('.001'),D(100))},due)
    assert D((await ledger.load())[1]['positions'][key]['funding'])*side<0


async def test_funding_history_pagination_reads_every_page_without_network(monkeypatch):
    from autotrader.perpetuals.market import Bar,MINUTE
    times=[NOW+i*MINUTE for i in range(201)]
    calls=[]
    def handler(request):
        end=int(request.url.params['endTime']);calls.append(end)
        rows=[{'symbol':'SOLUSDT','fundingRate':'0.0001','fundingRateTimestamp':str(t)} for t in reversed(times) if t<=end][:200]
        return httpx.Response(200,json={'retCode':0,'time':NOW,'result':{'list':rows}})
    async def no_wait(*args):pass
    async def bars(symbol,start,end,**kwargs):return {start:Bar(start,D(100),D(101),D(99),D(100))}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        market=MultiMarket(client,client);market.gate.wait=no_wait;market.bars=bars
        result=await market.funding('SOLUSDT',times[0],times[-1])
    assert len(result)==201 and len(calls)==2


def test_continuation_hypothesis_has_economically_qualifiable_example():
    from autotrader.perpetuals.market import Bar,MINUTE
    from autotrader.perpetuals.multi.strategies import generate
    bars={};previous=D(100)
    for i in range(90):
        close=D(100)+D(i)*D('.05')
        if i==87:close-=D('.07')
        if i==89:close+=D('.04')
        start=NOW-(90-i)*MINUTE
        bars[start]=Bar(start,previous,max(previous,close)+D('.05'),min(previous,close)-D('.05'),close,D(11) if i==89 else D(10))
        previous=close
    ideas=generate('SOLUSDT',bars,NOW,NOW)
    continuation=ideas[0]
    assert not continuation.reasons
    book,ticker=observation(mid=str(previous))
    rows=[plan(continuation,n,D(1000),D(1000),contract(),book,ticker,NOW) for n in COHORTS]
    assert all(D(r['scenario_gain'])>0 for r in rows)
    assert len(ideas)==4 and all(s.evidence['probability'] is None for s in ideas)


async def test_pause_keeps_protective_monitor_and_settlement_working(ledger,monkeypatch):
    state=await open_matched(ledger)
    await ledger.control(False)
    monkeypatch.setattr('autotrader.perpetuals.multi.ledger.clock_ms',lambda:NOW+1000)
    key=next(iter(state['positions']))
    await ledger.exit_intent('worker',key,'STOP')
    await ledger.quote_exit('worker',key,*observation(NOW+1000,'99'))
    await ledger.settle_funding('worker',key,{},NOW+1000)
    assert await ledger.settle_exit('worker',key)
    state=(await ledger.load())[1]
    assert not state['entries_enabled'] and len(state['positions'])==2
    assert D(state['accounts']['1']['realized'])<0


async def test_gap_bar_stop_precedes_target_and_is_labeled_hypothetical_stress(ledger,monkeypatch):
    from autotrader.perpetuals.market import Bar,MINUTE
    from autotrader.perpetuals.multi.runtime import MultiRuntime
    await open_matched(ledger)
    later=NOW+2*MINUTE
    monkeypatch.setattr('autotrader.perpetuals.multi.ledger.clock_ms',lambda:later)
    monkeypatch.setattr('autotrader.perpetuals.multi.runtime.clock_ms',lambda:later)
    await ledger.acquire('worker')
    class Market:
        async def contract(self,*args,**kwargs):return contract()
        async def observation(self,*args,**kwargs):return observation(later,'101')
        async def bars(self,symbol,start,end,**kwargs):
            return {t:Bar(t,D(100),D(102),D(98),D(101)) for t in range(start,end+1,MINUTE)}
    await MultiRuntime(ledger,Market(),owner='worker').monitor_once()
    state=(await ledger.load())[1]
    assert not state['positions']
    async with ledger.factory() as session:
        closed=[json.loads(r) for r in (await session.scalars(select(MultiEvent.payload).where(MultiEvent.kind=='EXIT_SETTLED'))).all()]
    assert len(closed)==3
    for event in closed:
        assert event['reason']=='STOP' and D(event['net'])<0 and event['planned_risk_exceeded']
        assert event['position']['observed_exit']['classification'].startswith('GAP_OHLC')


async def test_exit_price_survives_restart_while_funding_is_missing(ledger,monkeypatch):
    state=await open_matched(ledger);key=next(iter(state['positions']))
    due=state['positions'][key]['next_funding_at']
    monkeypatch.setattr('autotrader.perpetuals.multi.ledger.clock_ms',lambda:due)
    await ledger.acquire('worker')
    await ledger.exit_intent('worker',key,'TIME')
    await ledger.quote_exit('worker',key,*observation(due,'101'))
    captured=(await ledger.load())[1]['positions'][key]['observed_exit']
    with pytest.raises(Refused):await ledger.settle_funding('worker',key,{},due)
    recovered=MultiLedger(ledger.factory)
    assert not await recovered.quote_exit('worker',key,*observation(due,'98'))
    assert (await recovered.load())[1]['positions'][key]['observed_exit']==captured
    await recovered.settle_funding('worker',key,{due:(D('.001'),D(100))},due)
    assert await recovered.settle_exit('worker',key)


async def test_strategy_specific_momentum_exit_uses_completed_post_entry_bars(ledger,monkeypatch):
    from autotrader.perpetuals.market import Bar,MINUTE
    from autotrader.perpetuals.multi.runtime import MultiRuntime
    await open_matched(ledger);later=NOW+3*MINUTE
    monkeypatch.setattr('autotrader.perpetuals.multi.ledger.clock_ms',lambda:later)
    monkeypatch.setattr('autotrader.perpetuals.multi.runtime.clock_ms',lambda:later)
    await ledger.acquire('worker')
    class Market:
        async def contract(self,*args,**kwargs):return contract()
        async def observation(self,*args,**kwargs):return observation(later,'100.05')
        async def bars(self,symbol,start,end,**kwargs):
            return {t:Bar(t,D('100.3'),D('100.4'),D(100),D('100.2')-D(t-start)/MINUTE*D('.1'))
                    for t in range(start,end+1,MINUTE)}
    await MultiRuntime(ledger,Market(),owner='worker').monitor_once()
    assert not (await ledger.load())[1]['positions']
    async with ledger.factory() as session:
        rows=(await session.scalars(select(MultiEvent.payload).where(MultiEvent.kind=='EXIT_SETTLED'))).all()
    assert len(rows)==3 and all(json.loads(r)['reason']=='MOMENTUM_FADED_EXIT' for r in rows)


def test_backup_embedded_verifiers_remain_valid_python():
    import ast
    from pathlib import Path
    source=Path(__file__).resolve().parents[1]/'deploy/staging_backup.py'
    tree=ast.parse(source.read_text())
    scripts={node.targets[0].id:ast.literal_eval(node.value) for node in tree.body
             if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)
             and node.targets[0].id in ('OWNER','VERIFY')}
    assert set(scripts)=={'OWNER','VERIFY'}
    for name,script in scripts.items():compile(script,str(source)+':'+name,'exec')
