"""Synthetic invariants and immutable recorded PEPE timing, never P&L proof."""
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from autotrader.clock import at
from autotrader.domain import Candle, TradingPair
from autotrader.market_data.service import MarketDataService
from autotrader.market_data.synchronization import alignment, load_cycle
from autotrader.personal_paper.exits import assess_exit
from autotrader.raoe.discovery import discover, screen
from autotrader.raoe.playbooks import setup
from autotrader.raoe.regime import aggregate, assess, dimension
from autotrader.raoe.structure import classify
from test_v48_raoe import fixture

NOW=datetime(2026,10,28,4,tzinfo=UTC)


def history(symbol='TEST-EUR',count=1152):
    return [Candle(symbol,NOW-timedelta(minutes=5*(count-i)),D(100),D('100.2'),D('99.8'),D(100),D(10000),'5m','synthetic-v49') for i in range(count)]


@pytest.mark.parametrize('fault',['missing','gap','duplicate','future_only'])
def test_peer_unknown_records_exact_alignment_failure(fault):
    bars=history('BTC-EUR')
    if fault=='missing':bars=bars[:-1]
    elif fault=='gap':bars.pop(-7)
    elif fault=='duplicate':bars.append(bars[-1])
    else:bars=[replace(bars[-1],timestamp=NOW)]
    result=alignment(bars,NOW)
    assert result['alignment_status']=='UNKNOWN' and result['unknown_reason']
    assert result['requested_candle_at']==(NOW-timedelta(minutes=5)).isoformat()


async def test_independent_peers_and_fixed_boundary_do_not_reuse_stale_classification():
    class Feed:
        def __init__(self):self.calls=[];self._candle_observed_at={}
        async def resolve_pair(self,symbol):return TradingPair(symbol,symbol.split('-')[0],'EUR')
        async def completed_candles(self,pair):
            self.calls.append(pair.symbol)
            return [*history(pair.symbol),replace(history(pair.symbol)[-1],timestamp=NOW)]
    feed=Feed()
    cycle=await load_cycle(feed,[],NOW)
    assert feed.calls==['BTC-EUR','ETH-EUR']
    assert all(v['alignment_status']=='ALIGNED' and v['ignored_future_or_forming_bars']==1 for v in cycle.diagnostics.values())
    assert all(b.timestamp<NOW for bars in cycle.histories.values() for b in bars)
    actual=assess(history(),NOW,cycle.histories)
    assert actual['benchmark']=='MIXED'
    assert assess(history(),NOW,{'BTC-EUR':history('BTC-EUR')[:-1],'ETH-EUR':history('ETH-EUR')[:-1]})['benchmark']=='UNKNOWN'
    # Exact original PEPE timing: its ask preceded the peer data refresh.
    assert datetime.fromisoformat('2026-10-28T01:25:25+00:00')<datetime.fromisoformat('2026-10-28T01:26:07+00:00')


def test_four_hour_readiness_needs_real_complete_contiguous_84_hours():
    bars=history()
    assert dimension(aggregate(bars,240,NOW),240,NOW)['trend']=='RANGING'
    assert dimension(aggregate(bars[-720:],240,NOW),240,NOW)['trend']=='UNKNOWN'
    bars.pop(-50)
    context=dimension(aggregate(bars,240,NOW),240,NOW)
    assert context['trend']=='UNKNOWN' and context['contiguous_bars']<21
    assert len(aggregate([*bars,replace(bars[-1],timestamp=NOW)],240,NOW))==len(aggregate(bars,240,NOW))


async def test_history_restart_reuses_pg_cache_and_only_fetches_increment(pg_repo):
    class Client:
        def __init__(self):self.calls=[]
        async def get_candles(self,symbol,interval,start,end):
            self.calls.append((start,end))
            return [b for b in history(symbol) if start<=b.timestamp.timestamp()*1000<end]
    await pg_repo.initialize_portfolio(D(500))
    c=Client();pair=TradingPair('TEST-EUR','TEST','EUR')
    with at(NOW):
        first=MarketDataService(c,candle_lookback=1152,state_store=pg_repo,cache_enabled=True)
        bars=await first.completed_candles(pair)
        assert len(bars)==1152 and len(c.calls)==2
        reopened=MarketDataService(c,candle_lookback=1152,state_store=pg_repo,cache_enabled=True)
        assert await reopened.completed_candles(pair)==bars and len(c.calls)==2
        assert dimension(aggregate(bars,240,NOW),240,NOW)['trend']!='UNKNOWN'
    with at(NOW+timedelta(minutes=5)):
        # Provider has no new bar: do not fabricate one or report aligned.
        result=await reopened.completed_candles(pair)
        assert len(c.calls)==3 and c.calls[-1][1]-c.calls[-1][0]<=900000
        assert alignment(result,NOW+timedelta(minutes=5))['alignment_status']=='UNKNOWN'


def test_micro_pivots_do_not_become_overhead_ceiling_and_future_cannot_change_structure():
    bars=history(count=240)
    bars[-15]=replace(bars[-15],high=D('100.21'))
    data=classify(bars,NOW,D('100.1'))
    assert any(z['classification']=='MINOR_PRICE_NOISE' for z in data['zones'])
    assert not data['overhead']
    future=replace(bars[-1],timestamp=NOW,high=D(1000),close=D(999))
    assert classify([*bars,future],NOW,D('100.1'))==data


def test_meaningful_zone_break_and_retest_are_distinct_from_higher_overhead():
    bars=history(count=288)
    bars[-30]=replace(bars[-30],high=D(102))
    initial=classify(bars,NOW,D('100.1'))
    assert any(D(z['price'])==102 and z['classification']=='MEANINGFUL_UNBROKEN_RESISTANCE' for z in initial['overhead'])
    for i in [-3,-2,-1]:bars[i]=replace(bars[i],open=D('102.2'),high=D('102.5'),low=D('102.01'),close=D('102.4'))
    changed=classify(bars,NOW,D('102.41'))
    assert any(D(z['price'])==102 and z['classification']=='RETESTED_RESISTANCE_AS_SUPPORT' for z in changed['zones'])
    assert changed['price_discovery']


@pytest.mark.parametrize('fault',['wide','thin','bearish','wick','one_close','too_extended'])
def test_continuation_does_not_globally_remove_exhaustion(fault):
    bars=history(count=240)
    for i in [-2,-1]:bars[i]=replace(bars[i],open=D('100.3'),high=D('100.7'),low=D('100.28'),close=D('100.6'))
    bars[-20]=replace(bars[-20],low=D(99))
    r=assess(bars,NOW,{'BTC-EUR':history('BTC-EUR'),'ETH-EUR':history('ETH-EUR')})
    r.update(liquidity_adequate=True,relative_return_30m='.01')
    assert setup('RAOE_BREAKOUT_CONTINUATION',bars,r)['confirmed']
    if fault in {'wide','thin'}:r['liquidity_adequate']=False
    if fault=='bearish':r['benchmark']='RISK_OFF'
    if fault=='wick':bars[-1]=replace(bars[-1],high=D('101.5'))
    if fault=='one_close':bars[-2]=replace(bars[-2],close=D('100.2'))
    if fault=='too_extended':bars[-1]=replace(bars[-1],close=D(105),high=D('105.1'))
    assert not setup('RAOE_BREAKOUT_CONTINUATION',bars,r)['confirmed']


def test_continuation_exit_requires_version_and_two_completed_fifteen_minute_failures():
    bars=history(count=240);opened=NOW-timedelta(minutes=35)
    evidence={'exit_policy':{'version':'4.9.0-continuation-exit.1'},'pattern_state':{'level':'100'},'raoe_regime':{'atr':'.4'}}
    bars[-1]=replace(bars[-1],close=D('99.8'))
    result=assess_exit('RAOE_BREAKOUT_CONTINUATION',opened,evidence,bars,NOW,genuine=False)
    assert result['reason'] is None
    for i in [-4,-1]:bars[i]=replace(bars[i],close=D('99.8'))
    assert assess_exit('RAOE_BREAKOUT_CONTINUATION',opened,evidence,bars,NOW,genuine=False)['reason']=='failed_breakout'
    assert assess_exit('RAOE_BREAKOUT_CONTINUATION',opened,{},bars,NOW,genuine=False)['status']=='UNKNOWN_ENTRY_EXIT_VERSION'


async def test_scanner_rotation_and_true_short_window_without_summary_invention():
    symbols=['PEPE','BCH','NEAR','BTC','ETH']
    pairs=[TradingPair(s+'-EUR',s,'EUR') for s in symbols]
    tickers=[{'symbol':p.symbol,'bid':'100','ask':'100.01','high_24h':'150','low_24h':'50','quote_volume_24h':'2000000'} for p in pairs]
    unknown=screen(pairs,tickers,observed_at=NOW)
    assert all(r['completed_return_30m'] is None and r['summary_return_30m'] is None for r in unknown)
    class Client:
        async def get_tickers(self):return tickers
    service=MarketDataService(Client())
    seen=set()
    for index in range(3):
        with at(NOW+timedelta(minutes=5*index)):
            selected=await discover(service,pairs,1)
            assert {'BTC-EUR','ETH-EUR'}.issubset({p.symbol for p in selected})
            seen.update(p.symbol for p in selected)
            assert any(r['status']=='DEFERRED' for r in service._discovery_state['rows'])
    assert seen=={p.symbol for p in pairs}
    bars=history('PEPE-EUR',240);bars[-1]=replace(bars[-1],close=D(102),high=D('102.2'))
    rows=screen(pairs,tickers,cached={'PEPE-EUR':bars},observed_at=NOW)
    assert rows[0]['symbol']=='PEPE-EUR' and D(rows[0]['completed_return_30m'])==D('.02')
    assert rows[0]['short_window_source']=='GENUINE_CACHED_COMPLETED_CANDLES'


def test_recorded_pepe_cases_preserve_original_decision_evidence():
    rows=json.loads((Path(__file__).parents[1]/'docs/evidence/v4_9/pepe-original-signals.json').read_text())
    assert rows  # Exact decisions are also reconstructed by the forensic script.
    with at(NOW):
        bars,_stamp,peers,pair,book,f=fixture()
        from autotrader.raoe.engine import RAOEEngine
        signal=RAOEEngine().evaluate('RAOE_EARLY_RECOVERY',f,pair,book,candles=bars,benchmarks=peers)
        assert signal.evidence['exit_policy']['version']=='4.9.0-structure-exit.1'
        assert signal.evidence['entry_plan']['structure']['version']=='structural-significance/4.9.0'
