"""Versioned causal market-state research; no primary admission authority."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from autotrader.domain import Candle, OrderBook
from autotrader.indicators import _ema
from autotrader.market_data.synchronization import alignment
from autotrader.raoe.regime import aggregate, atr, dimension

D = Decimal
VERSION = 'market-state/4.9.3.1'
RECIPE = {'version': VERSION, 'scope': 'ISOLATED_RESEARCH_ONLY',
          'breakout_range_atr': '1.5', 'exhaustion_extension_atr': '3',
          'confirmation_volume_ratio': '1.2', 'persistence_bars': 6,
          'primary_admission_authority': False, 'tuned_on_final_holdout': False}
STATES = ('SUSTAINED_BEAR', 'RELIEF_RALLY', 'EMERGING_RECOVERY',
          'BULLISH_CONTINUATION', 'RANGE_BOUND', 'HIGH_VOL_BREAKOUT',
          'EXHAUSTED_MOMENTUM', 'UNCERTAIN_TRANSITION', 'UNKNOWN')


def frame(bars: list[Candle], minutes: int, as_of: datetime) -> dict[str, Any]:
    rows = aggregate(bars, minutes, as_of)
    result = dimension(rows, minutes, as_of)
    if result['unknown_reason']:
        return result
    close = [c.close for c in rows[-61:]]
    e9, e21 = D(result['ema9']), D(result['ema21'])
    a = atr(rows)
    prior9, prior21 = _ema(close[:-1], 9), _ema(close[:-1], 21)
    return {**result, 'close': str(close[-1]), 'previous_close': str(close[-2]),
            'return_3': str(close[-1]/close[-4]-1),
            'ema9_slope_atr': str((e9-prior9)/a) if a and prior9 else None,
            'ema21_slope_atr': str((e21-prior21)/a) if a and prior21 else None,
            'extension_atr': str((close[-1]-e9)/a) if a else None,
            'bearish_persistence': sum(c < e21 for c in close[-6:])/6,
            'bullish_persistence': sum(c > e21 for c in close[-6:])/6}


def _positive(value: Any) -> bool:
    return value is not None and D(str(value)).is_finite() and D(str(value)) > 0


def assess(candles: list[Candle], benchmarks: dict[str, list[Candle]], as_of: datetime,
           book: OrderBook | None = None, *, genuine: bool = True) -> dict[str, Any]:
    closed = aggregate(candles, 5, as_of)
    errors = []
    if (not closed or len({c.symbol for c in candles}) != 1
            or alignment(candles, as_of)['alignment_status'] != 'ALIGNED'):
        errors.append('asset_completed_history_unavailable')
    if any(not all(v.is_finite() for v in (c.open,c.high,c.low,c.close,c.volume))
           or min(c.open,c.high,c.low,c.close) <= 0 or c.volume < 0
           or not c.low <= min(c.open,c.close) <= max(c.open,c.close) <= c.high
           or genuine and not c.source.startswith('revolut-x') for c in closed):
        errors.append('invalid_market_observation')
    safe = [] if 'invalid_market_observation' in errors else candles
    frames = {str(m): frame(safe,m,as_of) for m in (5,15,60,240)}
    peers: dict[str, Any] = {}
    for symbol in ('BTC-EUR','ETH-EUR'):
        bars = benchmarks.get(symbol,[])
        valid = all(all(v.is_finite() for v in (c.open,c.high,c.low,c.close,c.volume))
                    and min(c.open,c.high,c.low,c.close)>0 and c.volume>=0
                    and c.low<=min(c.open,c.close)<=max(c.open,c.close)<=c.high for c in bars)
        if not valid:bars=[]
        known = (alignment(bars,as_of)['alignment_status']=='ALIGNED'
                 and all(c.symbol==symbol for c in bars)
                 and (not genuine or all(c.source.startswith('revolut-x') for c in bars)))
        peers[symbol] = {'ready':known,'timeframes':{str(m):frame(bars,m,as_of) for m in (5,15,60,240)}}
        micro = aggregate(bars,5,as_of)
        peers[symbol]['return_30m'] = str(micro[-1].close/micro[-7].close-1) if known and len(micro)>=7 else None
    ready = not errors and all(frames[k]['unknown_reason'] is None for k in ('5','15','60')) and all(p['ready'] for p in peers.values())
    if not safe:closed=[]
    a = atr(closed)
    volumes = [c.volume for c in closed[-21:-1]]
    average = sum(volumes,D(0))/len(volumes) if volumes else D(0)
    volume = closed[-1].volume/average if closed and average > 0 else None
    relative = (closed[-1].close/closed[-7].close-1
                -sum((D(p['return_30m']) for p in peers.values()),D(0))/2) if ready and len(closed)>=7 and all(p['return_30m'] is not None for p in peers.values()) else None
    f5,f15,f60,f240 = [frames[str(m)] for m in (5,15,60,240)]
    hour_bear = all(p['timeframes']['60']['trend']=='BEARISH' for p in peers.values())
    fast_improving = all(_positive(p['return_30m']) and _positive(p['timeframes']['5'].get('ema9_slope_atr')) for p in peers.values())
    medium_confirmed = all(p['timeframes']['15']['trend']=='BULLISH' and _positive(p['timeframes']['15'].get('ema9_slope_atr')) for p in peers.values())
    asset_reclaim = bool(f15.get('close') and D(f15['close']) >= D(f15['ema21'])
                         and D(f15['close']) > D(f15['previous_close'])
                         and _positive(f5.get('ema9_slope_atr')))
    confirmed = bool(fast_improving and medium_confirmed and asset_reclaim
                     and relative is not None and relative>0 and volume is not None and volume>=D('1.2'))
    expansion = bool(closed and a and closed[-1].high-closed[-1].low>D('1.5')*a)
    breakout = bool(len(closed)>13 and closed[-1].close>max(c.high for c in closed[-13:-1]))
    overextended = bool(f5.get('extension_atr') and D(f5['extension_atr'])>3)
    state,reason = 'UNCERTAIN_TRANSITION','Mixed or incomplete timeframe confirmation'
    if not ready:state,reason='UNKNOWN','Causal completed market or benchmark context is unavailable'
    elif overextended:state,reason='EXHAUSTED_MOMENTUM','Price is over three completed ATR above the fast mean; research caution'
    elif expansion and breakout and volume is not None and volume>=D('1.2') and not hour_bear:
        state,reason='HIGH_VOL_BREAKOUT','Completed range breakout with volatility/volume expansion'
    elif hour_bear and confirmed:state,reason='EMERGING_RECOVERY','Both hourly benchmarks remain bearish; completed 5m/15m and asset confirmation improve'
    elif hour_bear and (fast_improving or f5['trend']=='BULLISH'):
        state,reason='RELIEF_RALLY','Short-term rebound lacks complete benchmark, asset or volume confirmation'
    elif f5['trend']==f15['trend']==f60['trend']=='BULLISH' and f240['trend'] in {'BULLISH','RANGING'} and not hour_bear:
        state,reason='BULLISH_CONTINUATION','Aligned completed asset trends with non-adverse higher context'
    elif f5['trend']==f15['trend']=='RANGING':state,reason='RANGE_BOUND','Completed short/medium structures remain ranging'
    elif hour_bear and f60['trend']=='BEARISH' and f240['trend']=='BEARISH' and f5.get('bearish_persistence',0)>=5/6:
        state,reason='SUSTAINED_BEAR','Persistent asset decline and bearish hourly/higher context'
    return {'version':VERSION,'recipe':RECIPE,'state':state,'reason':reason,'ready':ready,
            'as_of':as_of.isoformat(),'completed_at':(closed[-1].timestamp+timedelta(minutes=5)).isoformat() if closed else None,
            'errors':errors,'timeframes':frames,'benchmarks':peers,
            'hourly_joint_bearish':hour_bear,'short_term_benchmarks_improving':fast_improving,
            'medium_benchmark_confirmation':medium_confirmed,'asset_confirmation':asset_reclaim,
            'transition_confirmation':confirmed,'relative_return_30m':str(relative) if relative is not None else None,
            'volume_ratio':str(volume) if volume is not None else None,
            'close':str(closed[-1].close) if closed else None,'atr':str(a),
            'spread_bps':str((book.best_ask-book.best_bid)/((book.best_ask+book.best_bid)/2)*10000) if book and book.best_ask and book.best_bid else None,
            'liquidity_kind':'Current observed depth; no future fill guarantee',
            'primary_policy_changed':False,'execution_authorized':False}


def shadow_hypotheses(evidence: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    proof = evidence.get('primary_admission') or {}
    gates = proof.get('gates') or {}
    structural = evidence.get('technical_eligible') is True and evidence.get('economic_eligible') is True
    other = all(gates.get(k) is True for k in ('primary_context_ready','primary_current_candle','primary_local_reclaim','primary_recovery_reclaim'))
    baseline = evidence.get('entry_eligible') is True
    transition = bool(structural and other and state.get('ready') and state.get('state')=='EMERGING_RECOVERY' and state.get('transition_confirmation'))
    return {'version':'regime-hypotheses/4.9.3.1','approved_baseline':baseline,
            'confirmed_transition':baseline or transition,
            'confirmed_breakout_retest':bool(structural and other and state.get('state') in {'BULLISH_CONTINUATION','HIGH_VOL_BREAKOUT'} and evidence.get('strategy_id','').endswith(('BREAKOUT_RETEST','BREAKOUT_CONTINUATION'))),
            'patient_execution':'UNOBSERVED_FUTURE_QUOTE_NOT_ASSUMED',
            'scope':'MODELED_RESEARCH_ONLY','primary_execution_authorized':False}
