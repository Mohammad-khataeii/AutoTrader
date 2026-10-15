"""Read-only connectivity proof. Never imports an authenticated exchange adapter."""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path

from autotrader.domain import utc_now
from autotrader.market_data.revolut import RevolutXPublicClient


async def main() -> None:
    result: dict[str, object] = {"checked_at":utc_now().isoformat(),"documentation":"https://developer.revolut.com/docs/api/revolut-x-crypto-exchange","mode":"public-read-only"}
    client=RevolutXPublicClient()
    try:
        pairs=await client.get_pairs()
        eur=[p for p in pairs if p.quote_asset=='EUR']
        result['pairs']={'status':'PASSED','total':len(pairs),'eur_count':len(eur),'eur_symbols':[p.symbol for p in eur]}
        if not eur:
            raise RuntimeError('No EUR markets available')
        pair=next((p for p in eur if p.base_asset=='BTC'),eur[0])
        result['metadata']=str(pair)
        book=await client.get_order_book(pair.symbol)
        result['book']={'status':'PASSED','symbol':pair.symbol,'timestamp':book.timestamp.isoformat(),'bid':str(book.best_bid),'ask':str(book.best_ask),'received_at':utc_now().isoformat()}
        now=utc_now()
        # Request only completed five-minute intervals.
        until=now.replace(second=0,microsecond=0)-timedelta(minutes=now.minute%5)
        candles=await client.get_candles(pair.symbol,5,int((until-timedelta(hours=20)).timestamp()*1000),int(until.timestamp()*1000))
        result['candles']={'status':'PASSED','count':len(candles),'last':candles[-1].timestamp.isoformat() if candles else None}
        tickers=await client.get_tickers([pair.symbol])
        result['tickers']={'status':'PASSED','count':len(tickers)}
        result['status']='PASSED'
    except Exception as exc:
        result['status']='BLOCKED'
        result['error']=f'{type(exc).__name__}: {exc}'
    finally:
        await client.close()
    path=Path('docs/evidence/live-public-smoke.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    asyncio.run(main())
