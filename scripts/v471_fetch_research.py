"""Predeclared new historical proxy interval, isolated from all previous catalogs."""
import asyncio
import gzip
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from autotrader.research.data import CoinbaseHistory, aggregate_complete, canonical, digest

ROOT=Path('.data/research-v471')
OUT=Path('docs/evidence/v4_7_1')
REGISTRATION={
 'schema':'v471-predeclared-study/1','registered_at':datetime.now(UTC).isoformat(),
 'symbols':['BTC-EUR','ETH-EUR','SOL-EUR'],'source':'coinbase-exchange-public EUR OHLCV proxy',
 'requested_start':'2025-01-01T00:00:00+00:00','requested_end_exclusive':'2025-02-01T00:00:00+00:00',
 'segments':{'training':['2025-01-04','2025-01-11'],'validation':['2025-01-12','2025-01-21'],'sealed_test':['2025-01-22','2025-02-01']},
 'purge_hours':24,'warmup_days':3,'timeframes':['5m','15m','1h'],
 'successor_variants':['A3-original','B3-original','E3-original','A3-reviewed-policy','B3-reviewed-policy','E3-reviewed-policy','A3-reviewed-pullback-IOC','B3-reviewed-retest-IOC','E3-reviewed-longer-horizon'],
 'native_alternatives':['A_TREND_PULLBACK','C_BREAKOUT_RETEST','E_RELATIVE_STRENGTH','F_MEAN_REVERSION'],
 'normal_costs':{'fee_bps':10,'slippage_bps':8,'spread_bps':10},
 'stress_costs':{'fee_bps':15,'slippage_bps':12,'spread_bps':20},
 'reviewed_policy':{'benchmark':'synchronized supportive/mixed required','trend':'bullish continuation; A3/E3 completed bullish 1h','overhead':'TP1 cannot lie beyond nearest observed 15m/1h overhead resistance','net_target_to_roundtrip_cost_minimum':2,'initial_stop_atr_minimum':1},
 'no_winner_promotion':True,'profitability_unknown':True,
 'limitations':['Fixed current liquid universe; survivorship selection','No historical L2; existing conservative finite-volume execution model','EUR500 historical simulator sizing, not EUR7000 prospective portfolio','All examined alternatives and costs reported; no repeated holdout retuning','New-to-this-project historical test is not prospective validation or statistical proof']}

async def main():
 ROOT.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
 registration=OUT/'research-registration.json'
 if registration.exists():
  existing=json.loads(registration.read_text())
  assert existing=={**REGISTRATION,'registered_at':existing['registered_at']}, 'immutable_preregistration_changed'
 else:registration.write_bytes(json.dumps(REGISTRATION,indent=2).encode()+b'\n')
 provider=CoinbaseHistory(ROOT);manifest=[]
 try:
  for symbol in REGISTRATION['symbols']:
   cache=ROOT/(symbol+'-5m.json.gz')
   if cache.exists():
    from autotrader.research.data import HistoricalBar
    bars=[HistoricalBar(**r) for r in json.loads(gzip.decompress(cache.read_bytes()))]
   else:
    bars,provenance=await provider.fetch(symbol,'5m',datetime(2025,1,1,tzinfo=UTC),datetime(2025,2,1,tzinfo=UTC))
    bars=sorted({b.start:b for b in bars}.values(),key=lambda b:b.start);cache.write_bytes(gzip.compress(canonical([asdict(b) for b in bars]),mtime=0))
    (ROOT/(symbol+'-provenance.json')).write_bytes(canonical(provenance))
   for timeframe in ['5m','15m','1h']:
    selected=bars if timeframe=='5m' else aggregate_complete(bars,timeframe)
    path=ROOT/(symbol+'-'+timeframe+'.json.gz');path.write_bytes(gzip.compress(canonical([asdict(b) for b in selected]),mtime=0))
    manifest.append({'symbol':symbol,'timeframe':timeframe,'bars':len(selected),'start':selected[0].start,'end':selected[-1].start,'file':str(path),'sha256':digest(path.read_bytes())})
   print(symbol,len(bars),'saved with immutable cache provenance',flush=True)
 finally:await provider.close()
 (OUT/'research-data.json').write_text(json.dumps({'registration_sha256':digest(registration.read_bytes()),'datasets':manifest},indent=2)+'\n')
 print('All newly requested historical proxy data acquired.',flush=True)

if __name__=='__main__':asyncio.run(main())
