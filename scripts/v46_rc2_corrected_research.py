"""Re-evaluate locked choices after removing spread from the technical drift check. No retuning."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path

from v46_rc2_research import compact

import autotrader
from autotrader.opportunity.engine import SuccessorParameters
from autotrader.research.data import HistoricalBar, canonical, digest, load_dataset
from autotrader.research.simulation import Costs, ResearchSimulation


def main():
    dest=Path('docs/evidence/v4_6_rc2');out=Path('.tools/v46-rc2-corrected');out.mkdir(exist_ok=True)
    initial=json.loads((dest/'research-initial.json').read_text())
    old=initial['preregistered'];split=old['chronological_split']
    params={s:SuccessorParameters.from_payload(p) for s,p in initial['locked_parameters']['parameters'].items()}
    package=Path(autotrader.__file__).parent
    files={str(p.relative_to(package)):digest(p.read_bytes()) for p in sorted(package.rglob('*.py'))}
    correction={'reason':'Midpoint movement rather than ask spread defines technical chase; executable ask and spread remain in costs.',
        'initial_report_sha256':digest((dest/'research-initial.json').read_bytes()),'source_files':files,'source_fingerprint':digest(canonical(files)),
        'parameters_locked':{s:p.payload() for s,p in params.items()},'retuning':False,'additional_interval_now_reused':True,
        'independent_claim':'The first run acquired this interval only after training locks. Correction has now seen it; not untouched or prospective.'}
    (out/'locked-correction.json').write_text(json.dumps(correction,indent=2)+'\n')
    root=Path('.data/research');catalog=json.loads((root/'catalog.json').read_text())
    prior=json.loads(Path('docs/evidence/v4_6/research-comparison.json').read_text())['preregistered']
    from datetime import timedelta
    end=datetime.fromisoformat(prior['end_exclusive'])
    bars=[b for m in catalog['manifests'] if m['timeframe']=='5m' for b in load_dataset(root,m) if end-timedelta(days=60)<=datetime.fromisoformat(b.start)<end]
    print('Preparing locked corrected comparison',flush=True)
    sim=ResearchSimulation(bars,successor=True)
    added=[HistoricalBar(**{**b,'quality_flags':tuple(b['quality_flags'])}) for b in json.loads(Path('.tools/v46-rc2-research/additional-bars.json').read_text())]
    forward=ResearchSimulation(added,successor=True)
    test_start=datetime.fromisoformat(split['test_start']);new_end=datetime.fromisoformat(old['additional_interval_end_exclusive'])
    results={}
    for s,p in params.items():
        def run(a,b,selected=s,parameters=p,**kw):return compact(sim.run(start=a,end=b,strategy_ids={selected},successor_parameters=parameters,**kw))
        validation=run(datetime.fromisoformat(split['validation_start']),datetime.fromisoformat(split['validation_end_exclusive']))
        test=run(test_start,end);new=compact(forward.run(start=end,end=new_end,strategy_ids={s},successor_parameters=p))
        stress=run(test_start,end,costs=Costs(fee_bps=D(15),slippage_bps=D(12),spread_bps=D(15),liquidity_fraction=D('.002')))
        windows=[run(datetime.fromisoformat(split['validation_start']),datetime.fromisoformat(split['validation_end_exclusive'])),run(test_start,test_start+(end-test_start)/2),run(test_start+(end-test_start)/2,end)]
        gates={'validation_positive':validation['net_profit']>0,'reused_test_positive':test['net_profit']>0,'new_interval_positive':new['net_profit']>0,
            'new_interval_at_least_30_closed_positions':new['trades']>=30,'cost_stress_positive':stress['net_profit']>0,
            'minimum_two_positive_locked_windows':sum(w['net_profit']>0 for w in windows)>=2,'drawdown_below_five_percent':test['max_drawdown']<.05}
        results[s]={**initial['successors'][s],'parameters':p.payload(),'validation':validation,'test':test,'new_interval':new,'cost_stress':stress,
            'locked_windows':windows,'validation_gates':gates,'status':'UNVALIDATED' if not all(gates.values()) else 'PROSPECTIVE_RESEARCH_REVIEW_REQUIRED',
            'entry_timing':{method:run(test_start,end,entry_method=method) for method in ('BID_IOC','PULLBACK_IOC','RETEST_IOC')},
            'three_market_comparison':run(test_start,end,universe={'BTC-EUR','ETH-EUR','SOL-EUR'}),
            'sizing_sensitivity':{str(q):run(test_start,end,quote_budget_eur=D(q)) for q in (25,75,100)}}
        print(s,'test',test['net_profit'],test['trades'],'added',new['net_profit'],new['trades'],flush=True)
    assert files=={str(p.relative_to(package)):digest(p.read_bytes()) for p in sorted(package.rglob('*.py'))}
    report={**initial,'correction':correction,'successors':results,'preregistered':{**old,'final_source_files':files,'final_source_fingerprint':digest(canonical(files))},
        'verdict':'All results, including initial and corrected studies, retained. No automatic promotion; after correction all evaluation intervals are reused.'}
    (dest/'research-comparison.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
