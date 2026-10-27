"""Engineering fixtures are synthetic, not market-performance evidence."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from autotrader.domain import Candle, OrderBook, OrderBookLevel, TradingPair, utc_now
from autotrader.indicators import calculate_features
from autotrader.raoe import IDENTITIES
from autotrader.raoe.discovery import screen
from autotrader.raoe.engine import RAOEEngine
from autotrader.raoe.plans import construct
from autotrader.raoe.playbooks import setup
from autotrader.raoe.regime import aggregate, assess


@pytest.fixture(autouse=True)
def causal_clock():
    from autotrader.clock import at
    with at(utc_now().replace(minute=0,second=0,microsecond=0)):
        yield


def observations(kind='recovery',symbol='TEST-EUR'):
    now=utc_now().replace(minute=0,second=0,microsecond=0)
    now-=timedelta(minutes=now.minute%5)
    bars=[]
    for i in range(720):
        price=D(200)-D(i)*D('.01') if kind=='recovery' else D(100)+D(i)*D('.02')
        bars.append(Candle(symbol,now-timedelta(minutes=(720-i)*5),price-D('.02'),price+D('.07'),price-D('.07'),price,D(10000),'5m','revolut-x:engineering'))
    if kind=='recovery':
        for j,price in enumerate([D('192.85'),D('192.88'),D('192.94'),D('193.05'),D('193.19'),D('193.30')]):
            bars[-6+j]=replace(bars[-6+j],open=price-D('.08'),high=price+D('.015'),low=price-D('.12'),close=price)
        bars[-45]=replace(bars[-45],high=D(198))
    if kind=='pullback':
        for j,price in enumerate([D('114.10'),D('113.98'),D('113.92'),D('113.99'),D('114.12')]):
            bars[-5+j]=replace(bars[-5+j],open=price-D('.03'),high=price+D('.02'),low=price-D('.08'),close=price)
        bars[-30]=replace(bars[-30],high=D('116.8'))
    if kind=='breakout':
        for j in range(40):
            price=D(100)+D(j%3)*D('.01')
            bars[-40+j]=replace(bars[-40+j],open=price-D('.01'),high=price+D('.05'),low=price-D('.05'),close=price)
        bars[-5]=replace(bars[-5],open=D('100.02'),high=D('100.2'),low=D('100.01'),close=D('100.15'))
        bars[-4]=replace(bars[-4],open=D('100.15'),high=D('100.21'),low=D('100.08'),close=D('100.17'))
        bars[-3]=replace(bars[-3],open=D('100.17'),high=D('100.2'),low=D('100.09'),close=D('100.16'))
        bars[-2]=replace(bars[-2],open=D('100.16'),high=D('100.19'),low=D('100.08'),close=D('100.15'))
        bars[-1]=replace(bars[-1],open=D('100.08'),high=D('100.18'),low=D('100.07'),close=D('100.17'))
    return bars,now


def fixture(kind='recovery'):
    bars,now=observations(kind)
    btc,_=observations('trend','BTC-EUR');eth,_=observations('trend','ETH-EUR')
    pair=TradingPair('TEST-EUR','TEST','EUR',price_step=D('.001'),quantity_step=D('.0001'),min_order_quote=D(5))
    close=bars[-1].close
    book=OrderBook(pair.symbol,now,(OrderBookLevel(close-D('.01'),D(10000)),),(OrderBookLevel(close+D('.01'),D(10000)),),'revolut-x:engineering')
    features=calculate_features(bars[-240:],D(0),D(1))
    return bars,now,{'BTC-EUR':btc,'ETH-EUR':eth},pair,book,features


def test_early_recovery_with_bearish_hourly_is_distinct_from_late_trend():
    bars,now,peers,pair,book,f=fixture()
    r=assess(bars,now,peers)
    assert r['timeframes']['60']['trend']=='BEARISH'
    assert 'EMERGING_BULLISH_RECOVERY' in r['labels']
    s=RAOEEngine().evaluate(IDENTITIES[0],f,pair,book,candles=bars,benchmarks=peers)
    assert s.evidence['technical_eligible']
    assert s.evidence['entry_eligible'],s.evidence['reasons']
    assert s.evidence['estimated_edge']=='UNKNOWN'
    assert s.evidence['quality_policy']['gates']['noise_floor']
    assert D(s.evidence['economics']['measurements']['net_reward_risk'])>=D('1.2')


def test_exhaustion_and_future_append_do_not_create_qualification():
    bars,now,peers,pair,book,f=fixture()
    original=RAOEEngine().evaluate(IDENTITIES[0],f,pair,book,candles=bars,benchmarks=peers)
    future=replace(bars[-1],timestamp=now+timedelta(minutes=5),close=D(999),high=D(1000))
    appended=RAOEEngine().evaluate(IDENTITIES[0],f,pair,book,candles=[*bars,future],benchmarks=peers)
    assert original==appended
    bars[-1]=replace(bars[-1],close=D(200),high=D(201))
    r=assess(bars,now,peers)
    assert not setup(IDENTITIES[0],bars,r)['confirmed']


def test_pullback_reaction_and_same_stop_patient_alternative():
    bars,now,peers,pair,book,_f=fixture('pullback')
    r=assess(bars,now,peers)
    pattern=setup(IDENTITIES[1],bars,r)
    assert pattern['confirmed'],pattern
    plan=construct(IDENTITIES[1],bars,pair,book,r,pattern)
    assert plan['valid']
    patient=plan['alternatives'][1]
    assert patient['same_structural_stop']==plan['stop']
    assert not patient['executable_now']


def test_breakout_requires_prior_hold_and_later_retest_and_cleared_level_is_support():
    bars,now,peers,pair,book,_f=fixture('breakout')
    r=assess(bars,now,peers)
    pattern=setup(IDENTITIES[2],bars,r)
    assert pattern['confirmed'],pattern
    plan=construct(IDENTITIES[2],bars,pair,book,r,pattern)
    assert plan['broken_resistance_as_support']==pattern['level']
    assert D(plan['ceiling'])>D(pattern['level'])
    bars[-2]=replace(bars[-2],close=D('99.5'))
    assert not setup(IDENTITIES[2],bars,assess(bars,now,peers))['confirmed']


@pytest.mark.parametrize('minutes',[15,60,240])
def test_aggregation_excludes_forming_bars_and_gaps(minutes):
    bars,now=observations()
    complete=aggregate(bars,minutes,now)
    assert all(c.timestamp+timedelta(minutes=minutes)<=now for c in complete)
    future=replace(bars[-1],timestamp=now)
    assert aggregate([*bars,future],minutes,now)==complete
    removed=bars[200]
    gapped=aggregate([c for c in bars if c is not removed],minutes,now)
    affected=[c for c in complete if c.timestamp<=removed.timestamp<c.timestamp+timedelta(minutes=minutes)]
    assert all(c not in gapped for c in affected)


@pytest.mark.parametrize('fault',['gap','stale','missing_benchmark','pegged','thin'])
def test_missing_stale_or_unexecutable_data_fails_closed(fault):
    bars,now,peers,pair,book,f=fixture()
    if fault=='gap': bars.pop(-9)
    if fault=='stale': book=replace(book,timestamp=now-timedelta(minutes=20))
    if fault=='missing_benchmark': peers={}
    if fault=='pegged': pair=replace(pair,base_asset='USDC')
    if fault=='thin': book=replace(book,bids=(OrderBookLevel(book.best_bid,D('.00001')),),asks=(OrderBookLevel(book.best_ask,D('.00001')),))
    s=RAOEEngine().evaluate(IDENTITIES[0],f,pair,book,candles=bars,benchmarks=peers)
    assert not s.evidence['entry_eligible']
    if fault in {'gap','stale'}:
        assert all(stage['passed'] is None for stage in s.evidence['pipeline'][3:])


def test_discovery_excludes_pegged_assets_and_preserves_unknown_summary():
    pairs=[TradingPair(s+'-EUR',s,'EUR') for s in ['USDC','TEST','MISSING']]
    tickers=[{'symbol':s+'/EUR','bid':'100','ask':'100.01','high_24h':'110','low_24h':'90','quote_volume_24h':'2000000'} for s in ['USDC','TEST']]
    rows=screen(pairs,tickers)
    assert rows[0]['symbol']=='TEST-EUR'
    assert next(r for r in rows if r['symbol']=='USDC-EUR')['reason']=='PEGGED_ASSET_DIRECTIONAL_EXCLUSION'
    assert next(r for r in rows if r['symbol']=='MISSING-EUR')['price'] is None


def test_locked_admission_rejects_changed_plan_and_worsened_fresh_book():
    from autotrader.raoe.admission import validate
    bars,_,peers,pair,book,f=fixture()
    signal=RAOEEngine().evaluate(IDENTITIES[0],f,pair,book,candles=bars,benchmarks=peers)
    e=signal.evidence;stop=D(e['entry_plan']['stop']);targets=[D(v) for v in e['entry_plan']['targets']]
    assert validate(pair,book,D(700),stop,targets,e,D(10),D(8),D(35)) is None
    assert validate(pair,book,D(700),stop-D(1),targets,e,D(10),D(8),D(35))=='raoe_immutable_entry_plan_mismatch'
    expensive=replace(book,asks=(OrderBookLevel(D('195.5'),D(10000)),))
    assert validate(pair,expensive,D(700),stop,targets,e,D(10),D(8),D(35)).startswith('raoe_fresh_economics')


async def test_blocked_candle_family_does_not_hold_protective_book_family():
    import asyncio

    import httpx

    from autotrader.market_data.revolut import RevolutXPublicClient
    entered,release=asyncio.Event(),asyncio.Event()
    async def transport(request):
        if 'candles' in request.url.path:
            entered.set();await release.wait()
        return httpx.Response(200,json={'data':[]})
    client=RevolutXPublicClient()
    await client._client.aclose();client._client=httpx.AsyncClient(base_url='https://provider.invalid',transport=httpx.MockTransport(transport))
    candle=asyncio.create_task(client._request('/1.0/public/candles/TEST-EUR'))
    try:
        await asyncio.wait_for(entered.wait(),1)
        assert await asyncio.wait_for(client._request('/2.0/public/order-book/TEST-EUR'),1)=={'data':[]}
    finally:
        release.set();await candle;await client.close()


def test_experimental_release_cannot_use_production_preflight(tmp_path):
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('release_v48',Path(__file__).parents[1]/'deploy/release.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    (tmp_path/'pyproject.toml').write_text('[project]\nversion="4.8.0.dev1"\n')
    with pytest.raises(ValueError,match='staging-only'):
        module.verify_release_preflight(tmp_path)


def test_supported_bid_targets_match_broker_net_exit_floors_without_extra_cost_charge():
    from autotrader.domain import Side
    from autotrader.execution.pricing import quote_execution, target_gross_floor
    from autotrader.raoe.exits import net_exit_targets
    _,_,_,pair,book,_=fixture()
    supported_bid=D(198)
    quantity=D(1)
    targets,metadata=net_exit_targets([supported_bid],book,quantity,pair.quantity_step,D(10),D(8))
    future=replace(book,bids=(OrderBookLevel(supported_bid,D(10000)),),asks=(OrderBookLevel(supported_bid+D('.01'),D(10000)),))
    executed=quote_execution(future,Side.SELL,quantity,fee_bps=D(10),slippage_bps=D(8),
        limit_price=target_gross_floor(targets[0],D(10)))
    assert executed.fillable_quantity==quantity
    assert abs(executed.net_unit_proceeds-targets[0])<D('1e-10')
    assert metadata['original_bid_targets']==['198']
    assert targets[0]<supported_bid
