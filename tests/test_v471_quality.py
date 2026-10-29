"""Deterministic regressions establish engineering behavior, never market edge."""
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from autotrader.domain import Candle, OrderBookLevel, utc_now
from autotrader.persistence.models import MarketFeature, OrderModel, SystemStateModel
from autotrader.personal_paper.exits import assess_exit
from autotrader.personal_paper.runtime import PersonalPaperRuntime
from autotrader.personal_paper.selection import ranking, reviewed_signal
from test_v47_paper import candidates_for, isolate_original_baselines, successor_frame
from test_v47_paper import paper as paper_fixture

paper = paper_fixture


def trend_candles(*, down=True):
    end = utc_now().replace(second=0,microsecond=0)
    end -= timedelta(minutes=end.minute%5)
    return [Candle('TEST-EUR',end-timedelta(minutes=(720-i)*5),D(200)+D(i)*D('-.1' if down else '.1'),
        D(201)+D(i)*D('-.1' if down else '.1'),D(199)+D(i)*D('-.1' if down else '.1'),
        D(200)+D(i)*D('-.1' if down else '.1'),D(100),'5m','revolut-x:engineering') for i in range(720)],end


def test_confirmed_position_reversal_and_own_breakout_only():
    candles,now=trend_candles()
    opened=now-timedelta(hours=1)
    a=assess_exit('A3_COST_AWARE_CONTINUATION',opened,{},candles,now)
    assert a['reason']=='regime_exit' and a['higher_15m']['bear']
    assert assess_exit('A3_COST_AWARE_CONTINUATION',now-timedelta(minutes=5),{},candles,now)['reason'] is None
    assert assess_exit('B3_STATEFUL_BREAKOUT',opened,{'pattern_state':{'level':'150'}},candles,now)['reason']=='failed_breakout'
    assert assess_exit('A3_COST_AWARE_CONTINUATION',opened,{'pattern_state':{'level':'150'}},candles,now)['reason']=='regime_exit'
    rising,now=trend_candles(down=False)
    assert assess_exit('A3_COST_AWARE_CONTINUATION',opened,{},rising,now)['reason'] is None


@pytest.mark.parametrize('fault',['future','stale','gap','wrong_source','wrong_timeframe','unknown_strategy'])
def test_invalid_discretionary_context_cannot_close(fault):
    candles,now=trend_candles()
    strategy='A3_COST_AWARE_CONTINUATION'
    if fault=='future':
        # Future observations are excluded: appending one cannot change a causal assessment.
        future=replace(candles[-1],timestamp=now+timedelta(minutes=5),close=D(900))
        before=assess_exit(strategy,now-timedelta(hours=1),{},candles,now)
        after=assess_exit(strategy,now-timedelta(hours=1),{},[*candles,future],now)
        assert before==after
        return
    if fault=='stale':now+=timedelta(minutes=11)
    if fault=='gap':candles.pop(-8)
    if fault=='wrong_source':candles[-1]=replace(candles[-1],source='untrusted')
    if fault=='wrong_timeframe':candles=[replace(c,timeframe='1m') for c in candles]
    if fault=='unknown_strategy':strategy='OTHER_STRATEGY'
    assert assess_exit(strategy,now-timedelta(hours=1),{},candles,now)['reason'] is None


async def test_unrelated_bearish_feature_cannot_close_a3_and_stop_still_wins(paper,tmp_path,monkeypatch):
    isolate_original_baselines(monkeypatch)
    service,repo=paper
    market,candidates=await candidates_for(tmp_path/'irrelevant.json',successor_frame('A3_COST_AWARE_CONTINUATION'))
    runtime=PersonalPaperRuntime(service,market,'v471-regression')
    try:
        await runtime.scan(candidates)
        position=next(p for p in await repo.list_positions() if p.quantity>0)
        async with repo.session_factory() as session,session.begin():
            session.add(MarketFeature(feature_id='unrelated-bear',symbol=position.symbol,timeframe='1m',timestamp=utc_now(),data_quality='BAD',payload_json=json.dumps({'metadata':{'regime_assessment':{'regime':'BEAR'}}})))
        assert await repo.market_exit_reason(position.symbol)=='regime_exit'  # Reproduces old shared-record problem.
        assert await repo.position_exit_reason(position.position_id,position.symbol,utc_now()) is None
        candidate=next(c for c in candidates if c.features.symbol==position.symbol)
        class Feed:
            async def resolve_pair(self,symbol):return next(c.market.pair for c in candidates if c.features.symbol==symbol)
            async def get_position_book(self,pair):
                c=next(c for c in candidates if c.features.symbol==pair.symbol)
                return replace(c.market.order_book,timestamp=utc_now())
        from autotrader.position_manager import PositionManager
        manager=PositionManager(repository=repo,market_data=Feed(),execution_gateway=runtime.gateway(repo))
        await manager.monitor_once()
        assert next(p for p in await repo.list_positions() if p.position_id==position.position_id).quantity>0
        class StopFeed(Feed):
            async def get_position_book(self,pair):
                b=await super().get_position_book(pair)
                return replace(b,bids=(OrderBookLevel(position.initial_stop*D('.99'),D(10000)),),asks=(OrderBookLevel(position.initial_stop,D(10000)),))
        actions=await PositionManager(repository=repo,market_data=StopFeed(),execution_gateway=runtime.gateway(repo)).monitor_once([candidate.market.pair])
        assert any(a.reason=='protective_stop' for a in actions)
        async with repo.session_factory() as session:
            sells=(await session.scalars(select(OrderModel).where(OrderModel.side=='SELL'))).all()
            for sell in sells:
                payload=json.loads(sell.execution_json)
                assert payload['strategy_id']=='A3_COST_AWARE_CONTINUATION'
                assert payload['attribution_source']=='POSITION_ENTRY_PLAN'
                assert payload['strategy_evidence']['execution_profile']==repo.manifest['version']
            assert (await session.scalars(select(SystemStateModel).where(SystemStateModel.state=='EXIT_ASSESSMENT'))).all()
        from autotrader.api.paper_analytics import attributed_summary
        summary=await attributed_summary(service)
        report=next(r for r in summary['trade_reports'] if r['position_id']==position.position_id)
        assert D(report['gross_price_pnl_eur'])-D(report['fees_eur'])==D(report['net_pnl_eur'])
        assert report['exit_reasons']==['STOP'] and report['raw_records_preserved']
        assert await repo.verify_invariants(D(7000))==[]
    finally:await market.close()


async def test_quality_and_ranking_economics_dominate_activity(paper,tmp_path):
    from autotrader.opportunity.engine import SuccessorOpportunityEngine
    from autotrader.opportunity.features import enrich
    _service,repo=paper
    market,candidates=await candidates_for(tmp_path/'quality.json',successor_frame('A3_COST_AWARE_CONTINUATION'))
    try:
        fs={c.features.symbol:enrich(c.features,c.market.candles,c.market.order_book.timestamp) for c in candidates}
        c=candidates[0];f=fs[c.features.symbol]
        original=SuccessorOpportunityEngine().evaluate('A3_COST_AWARE_CONTINUATION',f,c.market.pair,c.market.order_book,fs['BTC-EUR'],fs['ETH-EUR'],c.market.candles,quote_budget=D(700))
        good=reviewed_signal(original,f)
        assert good.evidence['entry_eligible']
        bad=replace(original,evidence={**original.evidence,'regime_assessment':{**original.evidence['regime_assessment'],'benchmark':'ADVERSE'}})
        assert not reviewed_signal(bad,f).evidence['entry_eligible']
        assert 'review_benchmark_support' in reviewed_signal(bad,f).evidence['reasons']
        later=replace(f,metadata={**f.metadata,'successor_context':{k:{**v,'resistance':str(c.market.order_book.best_ask+D('.01'))} for k,v in f.metadata['successor_context'].items()}})
        assert not reviewed_signal(original,later).evidence['entry_eligible']
        less=replace(good,score=D('.99'),evidence=json.loads(json.dumps(good.evidence,default=str)))
        less.evidence['economics']['measurements']['net_reward_risk']='1.21'
        less.evidence['quality_policy']['target_net_to_roundtrip_cost']='2'
        assert ranking(good) < ranking(less)
        assert ranking(good,D(2000)) > ranking(less)
        assert ranking(good)==ranking(good) and good.evidence['ranking_components']['probability'] is None
        from autotrader.personal_paper.admission import apply, completed_context
        from autotrader.research.data import canonical, digest
        reference=f.timestamp+timedelta(minutes=5)
        peers={s:next(x.market.candles for x in candidates if x.features.symbol==s) for s in ('BTC-EUR','ETH-EUR')}
        good=apply(good,completed_context(c.market.candles,peers,reference,genuine=False),reference)
        good.evidence['paper_manifest']=digest(canonical(repo.manifest))
        async with repo.session_factory() as session:
            assert await repo._entry_policy_error(session,good.strategy_id,good.evidence,D(10),D(8))=='paper_exit_policy_not_authorized_for_manifest'
            good.evidence['exit_policy']=repo.manifest['strategies'][good.strategy_id]['exit_policy']
            assert await repo._entry_policy_error(session,good.strategy_id,good.evidence,D(10),D(8)) is None
            forged={**good.evidence,'quality_policy':{'version':good.evidence['quality_policy']['version'],'gates':{'review_benchmark_support':True}}}
            assert await repo._entry_policy_error(session,good.strategy_id,forged,D(10),D(8))=='paper_quality_policy_required'
        # Appending observations unavailable at the signal time cannot affect its policy evidence.
        future=[replace(bar,timestamp=bar.timestamp+timedelta(days=4),close=bar.close+D(999)) for bar in c.market.candles[-5:]]
        causal=enrich(c.features,[*c.market.candles,*future],c.market.order_book.timestamp)
        assert reviewed_signal(original,causal).evidence['quality_policy']==reviewed_signal(original,f).evidence['quality_policy']
    finally:await market.close()
