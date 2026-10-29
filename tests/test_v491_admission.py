"""New primary context checks must fail closed without changing shadow controls."""
import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from autotrader.domain import Candle, DataQuality, StrategySignal
from autotrader.personal_paper import admission as a
from autotrader.shadow.versions import execution_fingerprint
from test_v47_paper import paper as paper_fixture

paper = paper_fixture

NOW = datetime(2026, 10, 29, 6, 45, 30, tzinfo=UTC)
CUTOFF = NOW.replace(second=0)
CANDLE = CUTOFF-timedelta(minutes=5)


def metrics():
    return {'ready': True, 'peers': {s: {'ready': True, 'trend': 'BULLISH'} for s in ('BTC-EUR', 'ETH-EUR')},
            'close': '105', 'ema9': '103', 'previous_ema9': '102',
            'higher_ready': True, 'close15': '104', 'previous_close15': '103', 'ema21_15': '102'}


def proof(strategy='RAOE_EARLY_RECOVERY'):
    return {'as_of': CANDLE.isoformat(), 'primary_admission': {'version': a.POLICY['version'],
        'policy': copy.deepcopy(a.POLICY), 'strategy_id': strategy, 'candle_at': CANDLE.isoformat(),
        'evaluation_cutoff': CUTOFF.isoformat(), 'inputs': metrics(),
        'gates': {k: True for k in a.GATES}, 'base_entry_eligible': True}}


def test_positive_context_then_next_candle_boundary_revokes_admission():
    e=proof()
    assert a.policy_error('RAOE_EARLY_RECOVERY',e,NOW) is None
    assert a.policy_error('RAOE_EARLY_RECOVERY',e,CUTOFF+timedelta(minutes=4,seconds=59)) is None
    assert a.policy_error('RAOE_EARLY_RECOVERY',e,CUTOFF+timedelta(minutes=5))=='paper_current_completed_candle_required'
    assert a.policy_error('RAOE_EARLY_RECOVERY',e,CUTOFF-timedelta(seconds=1))=='paper_current_completed_candle_required'


@pytest.mark.parametrize('fault',['absent','version','identity','as_of','missing_gate','integer_gate','nan','infinity','missing_peer','unready','forged_macro','peers_none','gates_none'])
def test_missing_malformed_and_forged_evidence_cannot_authorize(fault):
    e=proof();p=e['primary_admission']
    if fault=='absent':e.pop('primary_admission')
    elif fault=='version':p['version']='old'
    elif fault=='identity':p['strategy_id']='OTHER'
    elif fault=='as_of':e['as_of']=NOW.isoformat()
    elif fault=='missing_gate':p['gates'].pop('primary_local_reclaim')
    elif fault=='integer_gate':p['gates']['primary_local_reclaim']=1
    elif fault=='nan':p['inputs']['close']='NaN'
    elif fault=='infinity':p['inputs']['ema9']='Infinity'
    elif fault=='missing_peer':p['inputs']['peers'].pop('ETH-EUR')
    elif fault=='unready':p['inputs']['ready']=False
    elif fault=='forged_macro':
        for x in p['inputs']['peers'].values():x['trend']='BEARISH'
    elif fault=='peers_none':p['inputs']['peers']=None
    else:p['gates']=None
    assert a.policy_error('RAOE_EARLY_RECOVERY',e,NOW) is not None


def test_one_bearish_benchmark_is_not_joint_bearish_and_recovery_reclaim_is_distinct():
    inputs=metrics();inputs['peers']['BTC-EUR']['trend']='BEARISH'
    assert all(a.checks('RAOE_EARLY_RECOVERY',inputs,CANDLE.isoformat(),CUTOFF.isoformat(),NOW).values())
    inputs['close15']='100'
    assert not a.checks('RAOE_EARLY_RECOVERY',inputs,CANDLE.isoformat(),CUTOFF.isoformat(),NOW)['primary_recovery_reclaim']
    assert a.checks('RAOE_TREND_PULLBACK',inputs,CANDLE.isoformat(),CUTOFF.isoformat(),NOW)['primary_recovery_reclaim']


def bars(symbol, count=720):
    return [Candle(symbol,CUTOFF-timedelta(minutes=5*(count-i)),
                   D(100)+D(i)/100,D('100.04')+D(i)/100,D('99.96')+D(i)/100,
                   D('100.01')+D(i)/100,D(100),'5m','revolut-x:engineering') for i in range(count)]


def test_completed_context_ignores_future_bars_and_rejects_gaps_foreign_assets_and_sources():
    own=bars('TEST-EUR');peers={s:bars(s) for s in ('BTC-EUR','ETH-EUR')}
    before=a.completed_context(own,peers,CUTOFF)
    assert before['ready'] and all(a.checks('RAOE_EARLY_RECOVERY',before,CANDLE.isoformat(),CUTOFF.isoformat(),NOW).values())
    future=replace(own[-1],timestamp=CUTOFF,close=D(10000),high=D(10001))
    assert a.completed_context([*own,future],peers,CUTOFF)==before
    for changed in [own[:-1],own[:-7]+own[-6:],[*own[:-1],replace(own[-1],symbol='OTHER-EUR')],[*own[:-1],replace(own[-1],source='unverified')]]:
        assert not a.completed_context(changed,peers,CUTOFF)['ready']
    peers['ETH-EUR']=peers['ETH-EUR'][-30:]
    assert not a.completed_context(own,peers,CUTOFF)['ready']


def test_guard_cannot_promote_a_rejected_base_signal_or_mutate_its_evidence(monkeypatch):
    monkeypatch.setattr(a,'utc_now',lambda:NOW)
    original={'entry_eligible':False,'qualified':False,'reasons':['old_blocker'],'pipeline':[],'as_of':CANDLE.isoformat()}
    s=StrategySignal('sig','RAOE_EARLY_RECOVERY','TEST-EUR',CANDLE,D(1),DataQuality.GOOD,original,[],[],D(0),'engineering')
    result=a.apply(s,metrics(),CUTOFF)
    assert not result.evidence['entry_eligible'] and original==s.evidence and 'primary_admission' not in original
    eligible=replace(s,evidence={**original,'entry_eligible':True})
    assert a.apply(eligible,metrics(),CUTOFF).evidence['entry_eligible']


def test_original_shadow_execution_identity_is_unchanged():
    assert execution_fingerprint()=='44264f01586fedbd62e949f142c8240bb2dd9bae86c454fb17d388e2f5d9559c'


async def test_locked_primary_admission_requires_proof_and_dispatch_rechecks_boundary(paper,monkeypatch):
    from autotrader.clock import at
    from autotrader.domain import DecisionAction, OrderType, Side, TradingDecision
    from autotrader.persistence.models import OrderModel
    from autotrader.raoe.engine import RAOEEngine
    from autotrader.research.data import canonical, digest
    from test_v48_raoe import fixture
    _service,repo=paper
    own,stamp,peers,pair,book,features=fixture()
    book=replace(book,timestamp=stamp+timedelta(minutes=4,seconds=59))
    features=replace(features,metadata={**features.metadata,'evaluation_as_of':stamp.isoformat()})
    with at(book.timestamp):
        signal=RAOEEngine().evaluate('RAOE_EARLY_RECOVERY',features,pair,book,candles=own,benchmarks=peers)
        signal=a.apply(signal,a.completed_context(own,peers,stamp,genuine=False),stamp)
        signal=replace(signal,evidence={**signal.evidence,'paper_manifest':digest(canonical(repo.manifest))})
        e=signal.evidence
        async with repo.session_factory() as session:
            assert await repo._entry_policy_error(session,signal.strategy_id,{k:v for k,v in e.items() if k!='primary_admission'},D(10),D(8))=='paper_primary_admission_required'
            assert await repo._entry_policy_error(session,signal.strategy_id,e,D(10),D(8)) is None
        decision=TradingDecision('dec-boundary',pair.symbol,stamp,DecisionAction.BUY,[signal.signal_id],None,D(75),D('.3'),book.best_ask,D(e['entry_plan']['stop']),tuple(D(t) for t in e['entry_plan']['targets']),True,None,'Engineering stale-boundary admission regression')
        await repo.store_analysis([signal],None,decision);await repo.record_mark(book)
        original=repo.dispatch_order
        async def hold(identity,order_book=None):
            async with repo.session_factory() as session:return repo._domain_order(await session.get(OrderModel,identity))
        monkeypatch.setattr(repo,'dispatch_order',hold)
        order=await repo.submit_order(pair,Side.BUY,OrderType.MARKET,D('.3'),D(75),book,'boundary-guard',decision_id=decision.decision_id,stop_loss=decision.stop_loss,targets=list(decision.take_profit_targets))
        assert order.status.value=='PENDING'
        monkeypatch.setattr(repo,'dispatch_order',original)
    with at(stamp+timedelta(minutes=5)):
        canceled=await repo.dispatch_order(order.order_id)
        assert canceled.status.value=='CANCELLED' and 'current_completed_candle' in canceled.rejection_reason
        assert not await repo.list_fills() and D((await repo.snapshot())['reserved_cash'])==0
        assert await repo.verify_invariants(D(7000))==[]
