"""Causal structural significance, independent of economic qualification."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from autotrader.domain import Candle
from autotrader.raoe.regime import aggregate, atr

D=Decimal


def classify(candles: list[Candle], as_of: datetime, ask: Decimal) -> dict[str,Any]:
    five=aggregate(candles,5,as_of)
    zones: list[dict[str,Any]]=[];missing=[]
    for minutes in [5,15,60,240]:
        bars=aggregate(candles,minutes,as_of)[-80:]
        distance=atr(bars)
        if len(bars)<7 or distance<=0:
            missing.append(str(minutes));continue
        for i in range(2,len(bars)-2):
            row=bars[i]
            if row.high<max(c.high for c in bars[i-2:i+3]):continue
            prominence=row.high-min(c.low for c in bars[i-2:i+3])
            meaningful=minutes>=15 and prominence>=D('1.25')*distance
            known=row.timestamp+timedelta(minutes=minutes*3)
            later=[c for c in five if c.timestamp>=known]
            buffer=distance*D('.15')
            broken=False;retested=False
            for j,c in enumerate(later):
                previously_broken=broken
                if j and c.close>row.high+buffer and later[j-1].close>row.high+buffer:
                    broken=True
                if previously_broken and c.low<=row.high+buffer and c.close>=row.high:
                    retested=True
            if five and five[-1].close<row.high-buffer:
                broken=retested=False
            role=('MINOR_PRICE_NOISE' if not meaningful else 'RETESTED_RESISTANCE_AS_SUPPORT' if retested
                  else 'CONFIRMED_BROKEN_RESISTANCE' if broken else 'MEANINGFUL_UNBROKEN_RESISTANCE')
            if meaningful and not broken and row.high>ask and minutes>=60:role='HIGHER_OVERHEAD_RESISTANCE'
            zones.append({'price':str(row.high),'timeframe_minutes':minutes,'observed_at':row.timestamp.isoformat(),
                'known_at':known.isoformat(),'classification':role,'prominence_atr':str(prominence/distance),
                'confirmation_buffer':str(buffer),'source':row.source})
    overhead=sorted([z for z in zones if z['classification'] in {'MEANINGFUL_UNBROKEN_RESISTANCE','HIGHER_OVERHEAD_RESISTANCE'} and D(z['price'])>ask],key=lambda z:D(z['price']))
    pending=[z for z in zones if z['classification']=='MEANINGFUL_UNBROKEN_RESISTANCE'
             and D(z['price'])<=ask and five and five[-1].close<=D(z['price'])+D(z['confirmation_buffer'])]
    fifteen=aggregate(candles,15,as_of)
    prior=fifteen[-22:-2]
    top=max((c.high for c in prior),default=D(0));bottom=min((c.low for c in prior),default=D(0))
    discovery=bool(len(prior)>=8 and len(five)>=2 and top>bottom
                   and all(c.close>top for c in five[-2:]))
    classification=('MISSING_OR_UNCERTAIN_STRUCTURE' if len(prior)<8 else
                    'PRICE_DISCOVERY_WITH_HIGHER_OVERHEAD' if discovery and overhead else
                    'PRICE_DISCOVERY_NO_ESTABLISHED_NEARBY_CEILING' if discovery else
                    'MEANINGFUL_UNBROKEN_RESISTANCE' if overhead else 'MISSING_OR_UNCERTAIN_STRUCTURE')
    return {'version':'structural-significance/4.9.0','as_of':as_of.isoformat(),'classification':classification,
        'zones':zones,'overhead':overhead,'pending_breaks':pending,'price_discovery':discovery,
        'completed_range':{'high':str(top),'low':str(bottom),'bars':len(prior),'timeframe':'15m',
                           'last_range_candle_at':prior[-1].timestamp.isoformat() if prior else None},
        'missing_timeframes':missing,'limitation':'Measured extensions are bounded scenarios, not price forecasts.'}
