from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from autotrader.domain import (
    Candle,
    DataQuality,
    MarketFeatures,
    OrderBook,
    OrderBookLevel,
    TradingPair,
    utc_now,
)
from autotrader.opportunity.economics import CostAssumptions, CostAwareOpportunityEngine
from autotrader.opportunity.engine import SuccessorOpportunityEngine, relative_strength
from autotrader.opportunity.patterns import BreakoutState, advance, replay
from autotrader.opportunity.regime import assess_regime


def setup_observation():
    stamp = utc_now().replace(second=0, microsecond=0) - timedelta(minutes=5)
    pair = TradingPair('SOL-EUR', 'SOL', 'EUR', price_step=D('.001'), min_order_quote=D(5))
    f = MarketFeatures('SOL-EUR', stamp, '5m', DataQuality.GOOD, {
        'last_close': '100.3', 'previous_close': '99.7', 'last_open': '99.9', 'last_low': '99.5',
        'liquidity_quote': '200000', 'order_book_age_seconds': '0', 'history_contiguous': True,
        'return_20': '.05', 'return_60': '.08', 'return_volatility_20': '.001',
        'recent_returns': ['.001','.002','.003','.004','.005']*4,
        'successor_context': {'15m': {'ready': True, 'bull': True, 'atr': '2'}, '60m': {'ready': True, 'bull': True}}},
        ema_9=D(100), ema_21=D('99.9'), ema_50=D(99), atr=D(1),
        bollinger_upper=D(101), bollinger_lower=D(99), bollinger_mid=D(100), relative_volume=D('1.6'), spread_bps=D(1))
    book = OrderBook(pair.symbol, utc_now(), (OrderBookLevel(D('100.3'), D(1000)),), (OrderBookLevel(D('100.31'), D(1000)),), 'synthetic-isolated')
    return pair, f, book


def test_bullish_compression_has_independent_dimensions_and_unknown_is_not_zero():
    _, f, _ = setup_observation()
    r = assess_regime(f)
    assert r.trend == 'MODERATE_BULLISH' and 'COMPRESSION' in r.structure and r.volatility == 'NORMAL'
    assert r.liquidity == 'HEALTHY'
    missing = assess_regime(replace(f, atr=None))
    assert missing.trend == 'UNKNOWN' and 'atr' in missing.missing and missing.liquidity == 'UNRELIABLE_DATA'


def test_costs_use_bid_and_ask_once_and_reject_destroyed_first_target():
    pair, _, book = setup_observation()
    model = CostAwareOpportunityEngine(CostAssumptions(D(0), D(0), D(0)))
    result = model.evaluate(pair, book, quote_budget=D(75), stop=D(99), targets=(D(105), D(107)), atr=D(1), plausible_target=D(110), holding_bars=36)
    q = D(result.measurements['fillable_quantity'])
    assert result.feasible
    assert abs(D(result.measurements['estimated_total_round_trip_cost_eur']) - q * D('.01')) < D('.00000000001')
    expensive = CostAwareOpportunityEngine().evaluate(pair, book, quote_budget=D(75), stop=D(99),
        targets=(D('100.32'), D(101)), atr=D(1), plausible_target=D(110), holding_bars=36)
    assert not expensive.feasible and 'first_target_destroyed_by_execution_costs' in expensive.reasons
    assert expensive.expected_value_status == 'NOT_ESTIMATED_NO_CALIBRATED_EDGE'


def test_a3_technical_qualification_and_economic_failure_are_separate():
    pair, f, book = setup_observation()
    result = SuccessorOpportunityEngine().evaluate('A3_COST_AWARE_CONTINUATION', f, pair, book)
    assert result.evidence['technical_eligible'] and result.evidence['economic_eligible']
    bad = replace(f, metadata={**f.metadata, 'successor_context': {'15m': {'ready': True, 'bull': True, 'atr': '.02'}}})
    refused = SuccessorOpportunityEngine().evaluate('A3_COST_AWARE_CONTINUATION', bad, pair, book)
    assert refused.evidence['technical_eligible'] and not refused.evidence['entry_eligible']
    assert refused.evidence['pipeline'][3]['reason'].startswith('first_target_destroyed')


def test_e3_relative_strength_rejects_future_or_missing_benchmark_and_keeps_probability_unknown():
    pair, f, book = setup_observation()
    peers = [replace(f, symbol=s, metadata={**f.metadata, 'return_20': '.01', 'return_60': '.02'}) for s in ('BTC-EUR', 'ETH-EUR')]
    signal = SuccessorOpportunityEngine().evaluate('E3_ADAPTIVE_RELATIVE_STRENGTH', f, pair, book, *peers)
    assert signal.evidence['entry_eligible'] and signal.evidence['expected_value']['probability'] is None
    assert not relative_strength(f, *[replace(p, timestamp=p.timestamp + timedelta(minutes=5)) for p in peers])['ready']
    assert not relative_strength(replace(f, metadata={**f.metadata, 'return_volatility_20': None}), *peers)['ready']


def test_b3_delayed_retest_dedup_expiry_and_json_restart():
    end = utc_now() - timedelta(hours=5)
    bars = [Candle('SOL-EUR', end + timedelta(minutes=5*i), D(100), D(101), D(99), D(100), D(100), '5m', 'synthetic') for i in range(25)]
    breakout = replace(bars[-1], timestamp=bars[-1].timestamp + timedelta(minutes=5), open=D(100), high=D(103), low=D(100), close=D(102), volume=D(200))
    bars.append(breakout)
    state = replay(bars, compression_width=D('.03'))
    assert state.stage == 'RETEST_PENDING'
    event = state.event_id
    for i in range(1, 4):
        candle = replace(breakout, timestamp=breakout.timestamp + timedelta(minutes=5*i), open=D('102.5'), low=D('102.2'), close=D('102.4'))
        state = advance(BreakoutState(**state.payload()), candle, bars[-20:], compression_width=D('.03'))
        bars.append(candle)
    retest = replace(breakout, timestamp=bars[-1].timestamp + timedelta(minutes=5), open=D('100.9'), low=D('100.8'), high=D('102.2'), close=D('101.8'))
    state = advance(state, retest, bars[-20:])
    assert state.stage == 'CONFIRMED' and state.retest_age == 4 and state.event_id == event
    assert advance(state, retest, bars[-20:]).payload() == state.payload()
    waiting = replay(bars[:26], compression_width=D('.03'))
    late = replace(breakout, timestamp=breakout.timestamp + timedelta(minutes=5), open=D(104), low=D(104), close=D(104))
    waiting.retest_age = 8
    assert advance(waiting, late, bars[:26][-20:]).stage == 'EXPIRED'


def test_optimized_pattern_replay_matches_individual_completed_candles():
    end = utc_now() - timedelta(days=2)
    bars = [Candle('SOL-EUR', end + timedelta(minutes=5*i), D(100), D(101), D(99), D(100), D(100), '5m', 'synthetic') for i in range(100)]
    bars[35] = replace(bars[35], close=D(102), high=D(103), volume=D(250))
    bars[39] = replace(bars[39], open=D('100.8'), low=D('100.8'), close=D('101.8'), high=D(102))
    # Include a real gap; neither implementation may fabricate continuity.
    bars = bars[:65] + bars[66:]
    for size in (30, 36, 40, 64, 70, 90):
        state = BreakoutState()
        for i, candle in enumerate(bars[:size]):
            state = advance(state, candle, bars[max(0, i-20):i])
        assert replay(bars[:size]).payload() == state.payload()


@pytest.mark.parametrize('change,expected', [({'timestamp': utc_now()-timedelta(minutes=10)}, 'stale_order_book'), ({'asks': ()}, 'missing_asks')])
def test_stale_and_missing_depth_never_become_economic_candidates(change, expected):
    pair, _, book = setup_observation()
    result = CostAwareOpportunityEngine().evaluate(pair, replace(book, **change), quote_budget=D(75), stop=D(99), targets=(D(105),), atr=D(1), plausible_target=D(110), holding_bars=36)
    assert not result.feasible and expected in result.reasons
