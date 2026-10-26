"""Descriptive entry/cost/size sensitivity; no automatic strategy activation."""
import json
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from v47_research import compact

from autotrader.opportunity.engine import SUCCESSOR_REGISTRY, SuccessorParameters
from autotrader.research.data import load_dataset
from autotrader.research.simulation import ResearchSimulation
from autotrader.research.strategies import StrategyParameters

root=Path('.data/research');dest=Path('docs/evidence/v4_7/execution-study.json')
catalog=json.loads((root/'catalog.json').read_text())['manifests']
results=[]
for tf,days in [('5m',21),('1h',180),('4h',180)]:
    manifests=[m for m in catalog if m['timeframe']==tf]
    end=min(datetime.fromisoformat(m['requested_end_exclusive']) for m in manifests)
    start=end-timedelta(days=days)
    bars=[b for m in manifests for b in load_dataset(root,m) if start<=datetime.fromisoformat(b.start)<end]
    sim=ResearchSimulation(bars,successor=tf=='5m')
    times=sim.times;a=times[int(len(times)*.8)+min(144,len(times)//30)];b=times[-1]
    if tf=='5m':
        for spec in SUCCESSOR_REGISTRY:
            for entry in ('BID_IOC','PULLBACK_IOC','RETEST_IOC'):
                run=sim.run(start=a,end=b,strategy_ids={spec.strategy_id},successor_parameters=SuccessorParameters(),entry_method=entry)
                results.append({'strategy_id':spec.strategy_id,'timeframe':tf,'entry_method':entry,'result':compact(run)})
        for spec in SUCCESSOR_REGISTRY:
            for size in (D(50),D(100)):
                run=sim.run(start=a,end=b,strategy_ids={spec.strategy_id},successor_parameters=SuccessorParameters(),quote_budget_eur=size)
                results.append({'strategy_id':spec.strategy_id,'timeframe':tf,'entry_method':'MARKET','requested_quote_eur':str(size),'result':compact(run)})
    else:
        # A new research identity for a slower rotation hypothesis. Parameters
        # below are fixed before this run, never adopted by the live portfolio.
        for stop,target in [(D('1.5'),D(3)),(D(2),D(3))]:
            params=StrategyParameters(stop_atr=stop,target_atr=target)
            train_end=times[int(len(times)*.6)-1];validation_start=times[int(len(times)*.6)+min(144,len(times)//30)];validation_end=times[int(len(times)*.8)-1]
            for size in (D(75),):
                results.append({'strategy_id':'E4_SLOW_ROTATION_RESEARCH_ONLY','parent':'E_RELATIVE_STRENGTH','version':'4.7-research.1','timeframe':tf,'parameters':params.payload(),'quote_eur':str(size),
                    'training':compact(sim.run(start=times[240],end=train_end,strategy_ids={'E_RELATIVE_STRENGTH'},parameters=params,quote_budget_eur=size)),
                    'validation':compact(sim.run(start=validation_start,end=validation_end,strategy_ids={'E_RELATIVE_STRENGTH'},parameters=params,quote_budget_eur=size)),
                    'reused_holdout':compact(sim.run(start=a,end=b,strategy_ids={'E_RELATIVE_STRENGTH'},parameters=params,quote_budget_eur=size))})
    dest.write_text(json.dumps({'evidence_category':'HISTORICAL_PROXY_RESEARCH','reused_data':True,'selection':'NO_AUTOMATIC_PROMOTION','trials':results,'complete':tf=='4h',
        'limits':'EUR500 original simulator; IOC executable depth only; no passive queue-fill assumption; 50/100 EUR sensitivities; current market histories do not establish live advantage.'},indent=2,default=str)+'\n')
    print(tf,'complete',flush=True)
