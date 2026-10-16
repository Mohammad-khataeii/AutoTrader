"""Acquire genuine public observations using the real market-data adapter."""
import argparse
import asyncio
import json
from pathlib import Path

from autotrader.domain import utc_now
from autotrader.market_data.revolut import RevolutXPublicClient
from autotrader.market_data.service import MarketDataService
from autotrader.research.artifacts import source_fingerprint

parser=argparse.ArgumentParser(description='Read-only genuine Revolut X public-market smoke; never submits orders.')
parser.add_argument('--output',type=Path,default=Path('.tools/public-market-smoke.json'))
args=parser.parse_args()
async def main():
 events={}
 async def record(k,v):events[k]=events.get(k,0)+v
 c=RevolutXPublicClient(event_recorder=record);s=MarketDataService(c,candle_lookback=720)
 result={'started_at':utc_now().isoformat(),'source_fingerprint':source_fingerprint()[0],'data_kind':'GENUINE_PUBLIC_REVOLUT_X','orders_submitted':0,'observations':[]}
 try:
  pairs={p.symbol:p for p in await c.get_pairs()}
  for phase in range(2):
   for symbol in ['BTC-EUR','ETH-EUR','SOL-EUR']:
    m=await s.get_validated_market(pairs[symbol]);row={'phase':phase,'symbol':symbol,'quality':m.quality.value,'reasons':m.rejected_reasons,'candles':len(m.candles),'last_candle':m.candles[-1].timestamp.isoformat(),'book_timestamp':m.order_book.timestamp.isoformat(),'book_source':m.order_book.source,'candle_source':m.candles[-1].source}
    result['observations'].append(row)
    assert m.quality.value=='GOOD' and m.order_book.source=='revolut-x'
  result['events']=events;result['passed']=True;result['finished_at']=utc_now().isoformat()
  args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':True,'observations':len(result['observations']),'events':events,'orders':0}))
 finally:await s.close()
asyncio.run(main())
