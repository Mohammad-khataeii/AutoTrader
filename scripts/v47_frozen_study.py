"""Run exact frozen V4.2/V4.4 research runners without modifying their files."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from v47_research import compact

from autotrader.research.data import load_dataset
from autotrader.research.experimental import EXPERIMENTAL_REGISTRY
from autotrader.research.strategies import REGISTRY
from autotrader.shadow.versions import convert, frozen_module, verify_legacy, verify_v44

root=Path('.data/research');catalog=json.loads((root/'catalog.json').read_text())['manifests'];out=[]
for generation in ('v42','v44'):
    for tf,days in [('5m',21),('4h',180)]:
        ms=[m for m in catalog if m['timeframe']==tf];end=min(datetime.fromisoformat(m['requested_end_exclusive']) for m in ms);start=end-timedelta(days=days)
        bars=[b for m in ms for b in load_dataset(root,m) if start<=datetime.fromisoformat(b.start)<end]
        sim=frozen_module('research.simulation',generation).ResearchSimulation(convert(bars,selected=generation),experimental=tf=='5m')
        times=sim.times;a=times[int(len(times)*.8)+min(144,len(times)//30)];b=times[-1]
        for spec in [*REGISTRY,*EXPERIMENTAL_REGISTRY] if tf=='5m' else REGISTRY:
            if spec.filter_only:continue
            sim.experimental=spec in EXPERIMENTAL_REGISTRY
            sim._signal_cache.clear()
            r=sim.run(start=a,end=b,strategy_ids={spec.strategy_id})
            out.append({'generation':generation,'strategy_id':spec.strategy_id,'timeframe':tf,'evidence_category':'FROZEN_HISTORICAL_PROXY_RESEARCH','reused_holdout':compact(r)})
        print(generation,tf,'complete',flush=True)
        Path('docs/evidence/v4_7/frozen-generation-results.json').write_text(json.dumps({'v42_files':len(verify_legacy()),'v44_files':len(verify_v44()),'frozen_files_changed':False,'results':out,'complete':generation=='v44' and tf=='4h','limit':'Previously used historical data; no primary-account or prospective performance claim.'},indent=2,default=str)+'\n')
