"""Read-only public historical replay and fixed-parameter walk-forward evidence."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from autotrader.backtest import Backtester
from autotrader.decision import DecisionEngine
from autotrader.domain import TradingPair, utc_now
from autotrader.market_data.revolut import RevolutXPublicClient
from autotrader.persistence.repository import _json
from autotrader.portfolio import Portfolio
from autotrader.risk import RiskEngine, RiskLimits


async def main()->None:
    client=RevolutXPublicClient()
    now=utc_now()
    until=now.replace(second=0,microsecond=0)-timedelta(minutes=now.minute%5)
    observations=[]
    try:
        for symbol in ('BTC-EUR','ETH-EUR'):
            observations.extend(await client.get_candles(symbol,5,int((until-timedelta(hours=20)).timestamp()*1000),int(until.timestamp()*1000)))
    finally:
        await client.close()
    engine=Backtester(TradingPair('BTC-EUR','BTC','EUR'),Portfolio(Decimal(500)),DecisionEngine(RiskEngine(RiskLimits())))
    result={'source':'Revolut X public closed candles','received_at':now.isoformat(),'observations':len(observations),
        'purpose':'engineering replay; does not establish an investment edge'}
    try:
        result['report']=asdict(await engine.run_async(observations))
        result['walk_forward']=await engine.walk_forward(observations,train_bars=200,test_bars=20)
        result['status']='PASSED'
    except Exception as exc:
        result['status']='FAILED'
        result['error']=str(exc)
        raise
    finally:
        Path('docs/evidence/research-replay.json').write_text(_json(result),encoding='utf-8')
        print(_json(result))


if __name__=='__main__':
    asyncio.run(main())
