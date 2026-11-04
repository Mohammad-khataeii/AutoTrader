"""Four versioned deterministic hypotheses; scenario qualification is not calibrated EV."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from autotrader.perpetuals.micro.signals import features, grouped
from autotrader.perpetuals.micro.types import Features
from autotrader.perpetuals.market import Bar
from autotrader.perpetuals.multi.policy import D, POLICIES, digest


@dataclass(frozen=True)
class Signal:
    id: str
    symbol: str
    policy: str
    side: int
    cutoff: int
    decision_at: int
    reference: Decimal
    stop: Decimal
    target: Decimal
    hold_minutes: int
    regime: str
    feature_hash: str
    evidence: dict[str,Any]
    reasons: tuple[str,...]

    def payload(self) -> dict[str,Any]:
        return dict(self.__dict__)


def generate(symbol: str, bars: dict[int,Bar], cutoff: int, now: int) -> list[Signal]:
    f=features(bars,cutoff,now)
    one,price,atr=f.one,f.reference,f.atr_fraction
    context=grouped(one,15,cutoff)
    side=1 if f.momentum_5m>=0 else -1
    span=(max(r.high for r in one[-20:])-min(r.low for r in one[-20:]))/price
    extension=abs(price/(sum((r.close for r in one[-8:]),D(0))/8)-1)
    records=[]

    def add(index,direction,room,stop_distance,hold,reasons,**evidence):
        if not D('.005')<=room:
            reasons.append('insufficient_remaining_room_for_half_percent')
        distance=min(room,D('.01'))
        if stop_distance<=0 or stop_distance>D('.01'):reasons.append('invalid_or_excessive_stop')
        policy=POLICIES[index]
        records.append(Signal(digest([symbol,policy,cutoff]),symbol,policy,direction,cutoff,now,
            price,price*(1-direction*stop_distance),price*(1+direction*distance),hold,f.regime,f.source_hash,
            {'qualification':'EXPERIMENTAL_DETERMINISTIC','probability':None,'expected_net_pnl_usdt':None,
             'atr_fraction':atr,'efficiency':f.efficiency,'persistence':f.persistence,
             'relative_volume':f.volume_ratio,'expansion':f.expansion,
             'context_15m_closed_at':context[-1].start+15*60_000,
             'forecast_signed_move_fraction':distance,'source':'COMPLETED_PUBLIC_PERPETUAL_CANDLES',**evidence},
            tuple(dict.fromkeys(reasons))))

    reasons=[]
    if f.regime!=('TREND_UP' if side==1 else 'TREND_DOWN'):reasons.append('continuation_regime_mismatch')
    if side*f.acceleration<=0 or not all(side*(frame[-1].close-frame[-2].close)>0 for frame in (f.three,f.five)):
        reasons.append('continuation_acceleration_or_multiframe_missing')
    if not any(side*(r.close-r.open)<0 for r in one[-5:-1]):reasons.append('controlled_pullback_missing')
    if extension>atr*D('2.5'):reasons.append('continuation_already_extended')
    if f.volume_ratio is None or f.volume_ratio<D('.8'):reasons.append('volume_unconfirmed')
    if not D('.6')<=f.expansion<=D('2'):reasons.append('unstable_volatility')
    add(0,side,span,atr*D('1.8'),15,reasons,extension=extension)

    prior=one[-16:-3];upper=max(r.high for r in prior);lower=min(r.low for r in prior)
    b,r,c=one[-3:];direction=1 if b.close>upper else -1;level=upper if direction==1 else lower
    broke=b.close>upper if direction==1 else b.close<lower
    retest=r.low<=level+price*atr/2 and r.high>=level-price*atr/2
    reclaim=direction*(c.close-level)>0 and direction*(c.close-c.open)>0
    broad=max(v.high for v in one[-60:-3])-min(v.low for v in one[-60:-3])
    reasons=[]
    if not broke or not retest or not reclaim:reasons.append('compression_break_retest_reclaim_missing')
    if broad<=0 or (upper-lower)/broad>D('.65'):reasons.append('compression_not_observed')
    if abs(price/level-1)>atr*2:reasons.append('retest_entry_extended')
    if f.expansion>D('2.5'):reasons.append('breakout_volatility_spike')
    add(1,direction,(upper-lower)/price*D('1.5'),max(atr*D('1.5'),abs(price/level-1)+atr/2),20,reasons,structure=level)

    window=one[-31:-1];upper=max(r.high for r in window);lower=min(r.low for r in window)
    mid=(upper+lower)/2;width=upper-lower;direction=1 if price<mid else -1
    edge=(price-lower if direction==1 else upper-price)/max(width,D('1e-12'))
    reasons=[]
    if f.regime!='RANGE' or f.expansion>D('1.3'):reasons.append('stable_range_required')
    if not 0<=edge<=D('.2'):reasons.append('not_at_supported_range_edge')
    if min(sum(v.low<=lower+width*D('.15') for v in window),sum(v.high>=upper-width*D('.15') for v in window))<2:
        reasons.append('range_extremes_not_repeated')
    if direction*(one[-1].close-one[-1].open)<=0:reasons.append('range_rejection_missing')
    stop_distance=max(atr*D('1.5'),direction*(price-(lower if direction==1 else upper))/price+atr/2)
    add(2,direction,direction*(mid/price-1),stop_distance,12,reasons,structure=lower if direction==1 else upper)

    box=one[-25:-4];upper=max(v.high for v in box);lower=min(v.low for v in box)
    excursion=one[-3];failed_up=excursion.high>upper and all(v.close<upper for v in one[-2:])
    failed_down=excursion.low<lower and all(v.close>lower for v in one[-2:])
    direction=-1 if failed_up else 1
    reasons=[]
    if not (failed_up or failed_down):reasons.append('failed_breakout_not_confirmed')
    if direction*f.momentum_3m<=0 or direction*f.acceleration<=0:reasons.append('reversal_momentum_unconfirmed')
    if f.efficiency>D('.65') or f.expansion>D('2'):reasons.append('strong_trend_or_disordered_reversal')
    room=direction*((lower if direction==-1 else upper)/price-1)
    stop_distance=max(atr*D('1.8'),abs(price-(excursion.high if direction==-1 else excursion.low))/price+atr/2)
    add(3,direction,room,stop_distance,10,reasons,failed_break_direction='UP' if failed_up else 'DOWN',structure=upper if direction==-1 else lower)
    return records
