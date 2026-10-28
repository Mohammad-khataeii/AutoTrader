"""Acquire an unexamined, predeclared proxy interval. No runtime mutations."""
import asyncio
import gzip
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from autotrader.raoe import IDENTITIES, PARAMETERS
from autotrader.research.data import CoinbaseHistory, canonical, digest

OUT=Path('docs/evidence/v4_9')
ROOT=Path('.data/research-v49')
REGISTRATION={'schema':'raoe-fixed-study/4.9.0','registered_at':datetime.now(UTC).isoformat(),
    'symbols':['BTC-EUR','ETH-EUR','SOL-EUR','LINK-EUR','ADA-EUR'],'source':'Coinbase public EUR historical OHLCV proxy',
    'start':'2025-03-01T00:00:00+00:00','end':'2025-03-17T00:00:00+00:00',
    'segments':{'training':['2025-03-05','2025-03-08'],'validation':['2025-03-09','2025-03-11'],
                'untouched_test':['2025-03-13','2025-03-17']},
    'purge_hours':24,'test_purge_hours':48,'parameters':PARAMETERS,'raoe_variants':IDENTITIES,
    'frozen_v48_variants':['V48_RAOE_EARLY_RECOVERY','V48_RAOE_TREND_PULLBACK','V48_RAOE_BREAKOUT_RETEST'],
    'hypotheses':['V49 structural significance vs frozen V48 micro ceilings',
        'Bounded continuation with two range-break closes, liquid depth and synchronized peers',
        'Immediate vs next completed-bar confirmation vs controlled patient entry; no forced fill'],
    'holding_seconds':{'matched_originals':10800,'v48_raoe':21600,'v49_structure':21600,'v49_continuation':14400},
    'entry_variants':['IMMEDIATE','ONE_BAR_DELAY_CONFIRMATION','PATIENT_IOC_3_BARS'],
    'parameter_changes_after_test_allowed':False,
    'baselines':['A3_COST_AWARE_CONTINUATION','B3_STATEFUL_BREAKOUT','E3_ADAPTIVE_RELATIVE_STRENGTH',
        'MOMENTUM_30M','BUY_AND_HOLD','CASH'],
    'costs':{'normal':{'fee_bps':'10','slippage_bps':'8','spread_bps':'10'},
             'stress':{'fee_bps':'15','slippage_bps':'12','spread_bps':'20'}},
    'patient_variant':'Same fixed plan, next-bar open ask/slippage must be below limit within 3 bars; no candle-touch fills',
    'sizing':'Independent EUR500 portfolios, EUR75 nominal proposals, EUR5 stop risk, EUR150 reserve, no primary financial writes',
    'limitations':['All audit/January-February2025/April-October2026 intervals are development data',
        'March2025 is new to this project, not prospective performance',
        'March2025 has not previously been inspected in this project; registration precedes acquisition',
        'Fixed surviving liquid asset universe; no historical L2 or queue',
        'Worst-case stop before target when both barriers cross in a bar',
        'No retuning or winner promotion after viewing the untouched test']}


async def main():
    OUT.mkdir(exist_ok=True,parents=True);ROOT.mkdir(exist_ok=True,parents=True)
    path=OUT/'research-registration.json'
    if path.exists():
        old=json.loads(path.read_text())
        assert old==json.loads(json.dumps({**REGISTRATION,'registered_at':old['registered_at']}))
    else: path.write_text(json.dumps(REGISTRATION,indent=2)+'\n')
    provider=CoinbaseHistory(ROOT)
    datasets=[]
    try:
        for symbol in REGISTRATION['symbols']:
            cache=ROOT/(symbol+'-5m.json.gz')
            if not cache.exists():
                bars,provenance=await provider.fetch(symbol,'5m',datetime.fromisoformat(REGISTRATION['start']),datetime.fromisoformat(REGISTRATION['end']))
                bars=sorted({b.start:b for b in bars}.values(),key=lambda b:b.start)
                cache.write_bytes(gzip.compress(canonical([asdict(b) for b in bars]),mtime=0))
                (ROOT/(symbol+'-provenance.json')).write_bytes(canonical(provenance))
            rows=json.loads(gzip.decompress(cache.read_bytes()))
            datasets.append({'symbol':symbol,'bars':len(rows),'sha256':digest(cache.read_bytes()),'path':str(cache)})
            print(symbol,len(rows),flush=True)
    finally: await provider.close()
    (OUT/'research-data.json').write_text(json.dumps({'registration_sha256':digest(path.read_bytes()),'datasets':datasets},indent=2)+'\n')

if __name__=='__main__':asyncio.run(main())
