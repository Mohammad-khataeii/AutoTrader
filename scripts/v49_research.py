"""Run the registered fixed variants without revising the held-out definitions."""
import gzip
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from autotrader.research.artifacts import source_fingerprint
from autotrader.research.data import HistoricalBar, canonical, digest
from autotrader.research.v49 import simulate


def main():
    out=Path('docs/evidence/v4_9')
    registration=json.loads((out/'research-registration.json').read_text())
    datasets=json.loads((out/'research-data.json').read_text())
    bars=[]
    for d in datasets['datasets']:
        data=Path(d['path']).read_bytes();assert digest(data)==d['sha256']
        bars.extend(HistoricalBar(**r).candle() for r in json.loads(gzip.decompress(data)))
    # Pin the algorithm closure before evaluating outcomes. UI and transport
    # edits do not redefine this study; changed model bytes abort the run.
    root=Path('src/autotrader')
    model_paths=[*[p for p in root.glob('raoe/*.py') if p.name not in {'analytics.py','discovery.py','research.py'}],*root.glob('research/baselines/v48/*.py'),root/'research/v49.py',root/'personal_paper/exits.py',root/'personal_paper/selection.py',root/'execution/admission.py',root/'execution/pricing.py',root/'execution/protection.py',root/'execution/postings.py',root/'execution/policies.py',root/'opportunity/economics.py',root/'opportunity/engine.py',root/'opportunity/features.py',root/'opportunity/patterns.py',root/'opportunity/regime.py',root/'opportunity/sizing.py',root/'indicators.py',root/'domain.py',root/'market_data/synchronization.py']
    closure={str(p):digest(p.read_bytes()) for p in model_paths}
    model_source=source_fingerprint()[0]
    results=[];previous_elapsed=0.0;resumed=[]
    existing=out/'research-results.json'
    if existing.exists():
        saved=json.loads(existing.read_bytes())
        # Only complete batches are resumed. Every executed model dependency,
        # registration and dataset must match; no selective outcomes omitted.
        assert saved['registration_sha256']==digest((out/'research-registration.json').read_bytes())
        assert saved['datasets_sha256']==digest((out/'research-data.json').read_bytes())
        assert all(saved.get('model_closure',{}).get(p)==v for p,v in closure.items()),'Model changed; existing batches cannot resume'
        results=saved['results'];previous_elapsed=saved['elapsed_seconds']
        resumed=sorted({(r['segment'],r['cost_scenario']) for r in results})
        for segment,cost in resumed:
            batch=[r for r in results if (r['segment'],r['cost_scenario'])==(segment,cost)]
            assert len(batch)==24 and len({(r['strategy_id'],r['entry_method']) for r in batch})==24
    started=time.monotonic()
    for segment,dates in registration['segments'].items():
        for cost_name,costs in registration['costs'].items():
            if (segment,cost_name) in resumed:
                print('REUSED_VERIFIED_COMPLETE_BATCH',segment,cost_name,flush=True);continue
            batch=simulate(bars,*[datetime.fromisoformat(d).replace(tzinfo=UTC) for d in dates],costs)
            assert all(digest(Path(p).read_bytes())==v for p,v in closure.items()),'Model changed during study; discard outcomes and rerun'
            for r in batch:r.update(segment=segment,cost_scenario=cost_name)
            results.extend(batch)
            print(segment,cost_name,[(r['strategy_id'],r['entry_method'],r['net_profit'],r['closed_trades']) for r in batch],flush=True)
            payload={'schema':'raoe-research/4.9.0','complete':len(results)==144,'evidence_category':'HISTORICAL_PROXY_SIMULATION',
                'source_fingerprint_at_run_start':model_source,
                'model_closure':closure,'model_closure_sha256':digest(canonical(closure)),'registration_sha256':digest((out/'research-registration.json').read_bytes()),
                'datasets_sha256':digest((out/'research-data.json').read_bytes()),'results':results,
                'resumed_verified_batches':resumed,'resume_scope':'Identical model bytes; telemetry/discovery/unreferenced old study modules excluded from numerical model closure',
                'registration_amendment_sha256':digest((out/'research-registration-amendment.json').read_bytes()),
                'elapsed_seconds':previous_elapsed+time.monotonic()-started,'profitability':'UNKNOWN','automatic_promotion':False,
                'limitations':registration['limitations']+['Full lifecycle uses production pricing, structural plans, stop priority, causal position exits, partials and trailing. Database concurrency is tested separately.',
                    'Finite liquidity uses 1% of prior completed candle volume; future depth and order queue are unavailable.',
                    'Train/validation/test always reset separate EUR500 research capital; primary cash is never used.',
                    'BUY_AND_HOLD buys EUR75 per asset, leaving cash idle; it is not a fully invested index.',
                    'Historical proxy findings do not establish prospective profitability.']}
            (out/'research-results.json').write_bytes(canonical(payload)+b'\n')

if __name__=='__main__':main()
