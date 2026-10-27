"""Run the registered fixed variants without revising the held-out definitions."""
import gzip
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from autotrader.raoe.research import simulate
from autotrader.research.artifacts import source_fingerprint
from autotrader.research.data import HistoricalBar, canonical, digest


def main():
    out=Path('docs/evidence/v4_8')
    registration=json.loads((out/'research-registration.json').read_text())
    datasets=json.loads((out/'research-data.json').read_text())
    bars=[]
    for d in datasets['datasets']:
        data=Path(d['path']).read_bytes();assert digest(data)==d['sha256']
        bars.extend(HistoricalBar(**r).candle() for r in json.loads(gzip.decompress(data)))
    started=time.monotonic();results=[]
    for segment,dates in registration['segments'].items():
        for cost_name,costs in registration['costs'].items():
            batch=simulate(bars,*[datetime.fromisoformat(d).replace(tzinfo=UTC) for d in dates],costs)
            for r in batch:r.update(segment=segment,cost_scenario=cost_name)
            results.extend(batch)
            print(segment,cost_name,[(r['strategy_id'],r['entry_method'],r['net_profit'],r['closed_trades']) for r in batch],flush=True)
            payload={'schema':'raoe-research/1','complete':len(results)==72,'evidence_category':'HISTORICAL_PROXY_SIMULATION',
                'source_fingerprint':source_fingerprint()[0],'registration_sha256':digest((out/'research-registration.json').read_bytes()),
                'datasets_sha256':digest((out/'research-data.json').read_bytes()),'results':results,
                'elapsed_seconds':time.monotonic()-started,'profitability':'UNKNOWN','automatic_promotion':False,
                'limitations':registration['limitations']+['Full lifecycle uses production pricing, structural plans, stop priority, causal position exits, partials and trailing. Database concurrency is tested separately.',
                    'Finite liquidity uses 1% of prior completed candle volume; future depth and order queue are unavailable.',
                    'Train/validation/test always reset separate EUR500 research capital; primary cash is never used.',
                    'BUY_AND_HOLD buys EUR75 per asset, leaving cash idle; it is not a fully invested index.',
                    'Historical proxy findings do not establish prospective profitability.']}
            (out/'research-results.json').write_bytes(canonical(payload)+b'\n')

if __name__=='__main__':main()
