"""Recorded pricing diagnostics are not replayed into prospective accounts."""
import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from autotrader.clock import at
from autotrader.domain import OrderBook, OrderBookLevel, OrderType, Side, TradingPair, utc_now
from autotrader.execution.admission import project_buy
from autotrader.execution.pricing import observation_key, quote_execution
from autotrader.persistence.models import OrderModel, SystemStateModel
from autotrader.persistence.repository import PersistentTradingRepository
from test_v47_paper import paper as paper_fixture

paper=paper_fixture

DATA=json.loads((Path(__file__).parents[1]/'docs/evidence/v4_9/shadow-pricing-regressions.json').read_text())['cases']
PAIR=TradingPair('TEST-EUR','TEST','EUR',quantity_step=D('.0001'),price_step=D('.01'),min_order_quote=D(1))


def book(asks=((100,100),(500,100)),bids=((99.99,100),)):
    return OrderBook(PAIR.symbol,utc_now(),tuple(OrderBookLevel(D(str(p)),D(str(q))) for p,q in bids),
        tuple(OrderBookLevel(D(str(p)),D(str(q))) for p,q in asks),'synthetic-execution-regression')


@pytest.mark.parametrize('case',DATA,ids=[r['order_id'] for r in DATA])
def test_all_sixteen_recorded_rejections_have_quantity_aware_explanations(case):
    p=case['original_execution'];b=p['book'];stamp=datetime.fromisoformat(b['timestamp'])
    observed=OrderBook(case['symbol'],stamp,tuple(OrderBookLevel(D(x),D(q)) for x,q in b['bids']),
        tuple(OrderBookLevel(D(x),D(q)) for x,q in b['asks']),b['source'])
    pair=replace(PAIR,symbol=case['symbol'],quantity_step=D(p['quantity_step']))
    with at(stamp):
        projected=project_buy(pair,observed,D(case['quantity']),D(case['quote_budget']),D(p['stop_loss']),D(p['fee_bps']),D(p['slippage_bps']))
    assert D(case['old_distant_ask_planned_loss'])>5
    assert projected.planned_loss<=5
    assert projected.entry.allocations[0][0]==0 and len(projected.entry.allocations)==1
    assert projected.payload()==case['quantity_aware_projection']
    assert case['status']=='REJECTED'  # Original rejection is never rewritten.


def test_multilevel_quantity_rounding_consumption_budget_and_costs():
    b=book(((100,1),(102,2),(500,1000)))
    a=project_buy(PAIR,b,D('2.00009'),D(300),D(98),D(10),D(8),consumed={0:D('.5')})
    assert a.entry.fillable_quantity==D(2)
    assert a.entry.allocations==((0,D('.5')),(1,D('1.5')))
    assert a.entry.vwap==D('101.5')*D('1.0008')
    assert a.entry.fee==a.entry.gross_notional*D('.001')
    expected=-a.entry.net_cash_change-a.entry.fillable_quantity*D(98)*D('.999')*D('.9992')
    assert abs(a.planned_loss-expected)<D('1e-12')
    assert a.uncertainty_buffer==0
    limited=project_buy(PAIR,b,D(2),D(300),D(98),D(10),D(8),limit_price=D(101))
    assert limited.entry.fillable_quantity==1
    thin=project_buy(PAIR,book(((100,'.25'),)),D(1),D(100),D(98),D(10),D(8))
    assert thin.entry.fillable_quantity==D('.25') and thin.entry.unfilled_quantity==D('.75')
    exhausted=project_buy(PAIR,book(((100,1),)),D(1),D(100),D(98),D(10),D(8),consumed={0:D(1)})
    assert exhausted.entry.fillable_quantity==0
    with pytest.raises(ValueError,match='stale'):
        project_buy(PAIR,replace(b,timestamp=utc_now()-timedelta(seconds=91)),D(1),D(100),D(98),D(10),D(8))


@pytest.mark.parametrize('depth,expected_fill',[(D(100),D('.7')),(D('.25'),D('.25'))])
async def test_admission_dispatch_restart_partial_and_reservation_reconcile(pg_repo,monkeypatch,depth,expected_fill):
    await pg_repo.initialize_portfolio(D(500));b=book(((100,depth),(500,1000))) if depth==100 else book(((100,depth),))
    async def hold_dispatch(identity,order_book=None):
        async with pg_repo.session_factory() as session:
            return pg_repo._domain_order(await session.get(OrderModel,identity))
    monkeypatch.setattr(pg_repo,'dispatch_order',hold_dispatch)
    order=await pg_repo.submit_order(PAIR,Side.BUY,OrderType.MARKET,D('.7'),D(75),b,'v49-durable-buy',
        stop_loss=D(98),targets=[D(110),D(115),D(120)])
    assert order.status.value=='PENDING'
    # A new repository instance models submission/dispatch separation. Existing
    # process-crash acceptance additionally exercises actual worker restarts.
    restarted=PersistentTradingRepository(pg_repo.session_factory)
    same=await restarted.submit_order(PAIR,Side.BUY,OrderType.MARKET,D('.7'),D(75),b,'v49-durable-buy',stop_loss=D(98))
    assert same.order_id==order.order_id
    filled=await restarted.dispatch_order(order.order_id)
    assert filled.filled_quantity==expected_fill
    await restarted.dispatch_order(order.order_id)
    assert len(await restarted.list_fills())==1
    snapshot=await restarted.snapshot();assert D(snapshot['reserved_cash'])==0
    assert await restarted.verify_invariants(D(500))==[]
    async with restarted.session_factory() as session:
        row=await session.get(OrderModel,order.order_id);p=json.loads(row.execution_json)
        assert p['buy_admission']['entry']['vwap']==p['dispatch_buy_admission']['entry']['vwap']==p['execution_quality']['vwap']
        assert D(p['dispatch_buy_admission']['planned_loss_eur'])<=5


async def test_consumed_depth_is_checked_at_admission_and_dispatch(pg_repo):
    await pg_repo.initialize_portfolio(D(500));b=book(((100,1),(105,1)))
    async with pg_repo.session_factory() as session,session.begin():
        session.add(SystemStateModel(key=observation_key(b),state='CONSUMED',reason='synthetic-prior-liquidity',payload_json=json.dumps({'BUY':{'0':'.9'},'SELL':{}})))
    expected=quote_execution(b,Side.BUY,D('.7'),quantity_step=PAIR.quantity_step,quote_budget=D(75),consumed={0:D('.9')})
    order=await pg_repo.submit_order(PAIR,Side.BUY,OrderType.MARKET,D('.7'),D(75),b,'consumed',stop_loss=D(99))
    assert order.status.value=='FILLED'
    async with pg_repo.session_factory() as session:
        row=await session.get(OrderModel,order.order_id);admission=json.loads(row.execution_json)['buy_admission']
        assert D(admission['entry']['vwap'])==expected.vwap
    filled=await pg_repo.dispatch_order(order.order_id)
    assert filled.average_fill_price==expected.vwap and filled.filled_quantity==expected.fillable_quantity
    assert await pg_repo.verify_invariants(D(500))==[]


@pytest.mark.parametrize('stop,accepted',[(D(94),True),(D(90),False)])
async def test_near_cap_uses_real_fill_risk_and_still_rejects_over_cap(pg_repo,stop,accepted):
    await pg_repo.initialize_portfolio(D(500));b=book()
    result=project_buy(PAIR,b,D('.7'),D(75),D(94),D(10),D(8))
    assert result.planned_loss<5
    order=await pg_repo.submit_order(PAIR,Side.BUY,OrderType.MARKET,D('.7'),D(75),b,'cap-case',stop_loss=stop)
    assert order.status.value==('FILLED' if accepted else 'REJECTED')
    if not accepted:
        async with pg_repo.session_factory() as session:
            assert 'planned_loss' in json.loads((await session.get(OrderModel,order.order_id)).execution_json)['rejection_reason']
    assert D((await pg_repo.snapshot())['reserved_cash'])==0
    assert await pg_repo.verify_invariants(D(500))==[]


@pytest.mark.parametrize('fault',['aged_book','depth_exhausted','depth_worse'])
async def test_durable_order_rechecks_staleness_and_changed_consumption_before_filling(pg_repo,monkeypatch,fault):
    from sqlalchemy import select
    await pg_repo.initialize_portfolio(D(500))
    observed=book(((100,1),(110,1)))
    stamp=observed.timestamp
    async def hold(identity,order_book=None):
        async with pg_repo.session_factory() as session:return pg_repo._domain_order(await session.get(OrderModel,identity))
    monkeypatch.setattr(pg_repo,'dispatch_order',hold)
    order=await pg_repo.submit_order(PAIR,Side.BUY,OrderType.MARKET,D('.7'),D(75),observed,'separated-risk-check',stop_loss=D(98),targets=[D(105),D(115),D(120)])
    assert order.status.value=='PENDING'
    restarted=PersistentTradingRepository(pg_repo.session_factory)
    if fault!='aged_book':
        async with pg_repo.session_factory() as session,session.begin():
            session.add(SystemStateModel(key=observation_key(observed),state='CONSUMED',reason='synthetic-race',
                payload_json=json.dumps({'BUY':{'0':'1','1':'1'} if fault=='depth_exhausted' else {'0':'1'},'SELL':{}})))
    with at(stamp+timedelta(seconds=91) if fault=='aged_book' else stamp):
        result=await restarted.dispatch_order(order.order_id)
        assert result.status.value=='CANCELLED' and not await restarted.list_fills()
        assert D((await restarted.snapshot())['reserved_cash'])==0
        assert await restarted.verify_invariants(D(500))==[]
        async with restarted.session_factory() as session:
            assert await session.scalar(select(OrderModel.filled_quantity).where(OrderModel.order_id==order.order_id))==0


async def test_same_quantity_price_path_is_identical_for_primary_and_shadow(paper,lab):
    """Real scoped repositories, actual strategy authority, separate reserves."""
    from autotrader.domain import DecisionAction, TradingDecision
    from autotrader.raoe.engine import RAOEEngine
    from autotrader.research.data import canonical, digest
    from test_v48_raoe import fixture
    _service,primary=paper
    record=await lab.create('v49-parity','Synthetic price parity','RAOE_EARLY_RECOVERY')
    shadow=await lab.repository(record['experiment_id'])
    bars,stamp,peers,pair,observed,f=fixture()
    with at(stamp):
        original=RAOEEngine().evaluate('RAOE_EARLY_RECOVERY',f,pair,observed,candles=bars,benchmarks=peers)
        from autotrader.personal_paper.admission import apply, completed_context
        original=apply(original,completed_context(bars,peers,stamp,genuine=False),stamp)
        outputs=[]
        for repo in [primary,shadow]:
            signal=replace(original,evidence={**original.evidence,'paper_manifest':digest(canonical(primary.manifest))})
            decision=TradingDecision(decision_id='dec-parity',timestamp=stamp,symbol=pair.symbol,action=DecisionAction.BUY,
                accepted=True,proposed_quote_amount=D(75),proposed_quantity=D('.3'),entry_price=observed.best_ask,
                stop_loss=D(signal.evidence['entry_plan']['stop']),take_profit_targets=tuple(D(v) for v in signal.evidence['entry_plan']['targets']),
                signal_ids=[signal.signal_id],ai_assessment_id=None,rejected_reason=None,explanation='Synthetic parity integration')
            # Store the actual immutable signal/decision through the same path
            # used by both runtime coordinators; no admission gates bypassed.
            await repo.store_analysis([signal],None,decision)
            await repo.record_mark(observed)
            order=await repo.submit_order(pair,Side.BUY,OrderType.MARKET,D('.3'),D(75),observed,'parity',decision_id=decision.decision_id,
                stop_loss=decision.stop_loss,targets=list(decision.take_profit_targets))
            assert order.status.value=='FILLED',order.rejection_reason
            async with repo.session_factory() as session:
                row=await session.get(OrderModel,order.order_id);payload=json.loads(row.execution_json)
                outputs.append(payload['dispatch_buy_admission']['entry'])
            assert await repo.verify_invariants(repo.expected_initial_cash)==[]
        assert outputs[0]==outputs[1]


async def test_pending_partial_vwap_loss_is_included_in_primary_aggregate_risk(paper,monkeypatch):
    """Isolate the financial gate with synthetic intents and a LOWER test cap."""
    import autotrader.personal_paper.repository as policy
    _service,repo=paper
    monkeypatch.setattr(policy,'AGGREGATE_STOP_RISK',D(6))
    async def authority(*args,**kwargs):return None
    async def hold(identity,order_book=None):
        async with repo.session_factory() as session:return repo._domain_order(await session.get(OrderModel,identity))
    # Strategy authority has its own full integration tests. This regression
    # specifically isolates aggregate reservation and executable stop-risk units.
    monkeypatch.setattr(repo,'_entry_policy_error',authority)
    monkeypatch.setattr(repo,'dispatch_order',hold)
    observed=book(((100,'.1'),(105,100)))
    first=await repo.submit_order(PAIR,Side.BUY,OrderType.MARKET,D('.7'),D(70),observed,'aggregate-first',stop_loss=D(99),targets=[D(110),D(115),D(120)])
    assert first.status.value=='PENDING'
    async with repo.session_factory() as session:
        payload=json.loads((await session.get(OrderModel,first.order_id)).execution_json)
        assert D(payload['buy_admission']['planned_loss_eur'])>3
    second_pair=replace(PAIR,symbol='OTHER-EUR',base_asset='OTHER')
    second_book=replace(observed,symbol='OTHER-EUR')
    second=await repo.submit_order(second_pair,Side.BUY,OrderType.MARKET,D('.7'),D(70),second_book,'aggregate-second',stop_loss=D(99),targets=[D(110),D(115),D(120)])
    assert second.status.value=='REJECTED' and second.rejection_reason=='aggregate_stop_risk_budget'
    assert D((await repo.snapshot())['reserved_cash'])==70
    assert await repo.verify_invariants(D(7000))==[]
