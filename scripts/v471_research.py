"""Fixed predeclared ablation on a new historical interval. Never promotes a winner."""
from __future__ import annotations

import gzip
import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from v47_research import compact

from autotrader.opportunity.engine import (
    SUCCESSOR_REGISTRY,
    SuccessorOpportunityEngine,
    SuccessorParameters,
)
from autotrader.personal_paper.selection import reviewed_signal
from autotrader.research.data import HistoricalBar, digest
from autotrader.research.simulation import Costs, ResearchSimulation
from autotrader.research.strategies import StrategyParameters

OUT = Path('docs/evidence/v4_7_1')

class ReviewedEngine(SuccessorOpportunityEngine):
    def evaluate(self, identity, f, *args, **kwargs):
        return reviewed_signal(super().evaluate(identity, f, *args, **kwargs), f)


def main():
    registration = json.loads((OUT/'research-registration.json').read_text())
    results = []
    started = time.monotonic()
    for tf in registration['timeframes']:
        bars = [HistoricalBar(**row) for symbol in registration['symbols'] for row in json.loads(gzip.decompress((Path('.data/research-v471')/(symbol+'-'+tf+'.json.gz')).read_bytes()))]
        print('Preparing', tf, len(bars), flush=True)
        sim = ResearchSimulation(bars, successor=tf=='5m')
        variants = [(s.strategy_id.split('_')[0]+'-original', s.strategy_id, False, 'MARKET', SuccessorParameters()) for s in SUCCESSOR_REGISTRY] if tf=='5m' else []
        if tf=='5m':
            variants += [(s.strategy_id.split('_')[0]+'-reviewed-policy',s.strategy_id,True,'MARKET',SuccessorParameters()) for s in SUCCESSOR_REGISTRY]
            variants += [('A3-reviewed-pullback-IOC',SUCCESSOR_REGISTRY[0].strategy_id,True,'PULLBACK_IOC',SuccessorParameters()),
                         ('B3-reviewed-retest-IOC',SUCCESSOR_REGISTRY[1].strategy_id,True,'RETEST_IOC',SuccessorParameters()),
                         ('E3-reviewed-longer-horizon',SUCCESSOR_REGISTRY[2].strategy_id,True,'MARKET',replace(SuccessorParameters(),holding_bars=72,target_atr=D(3)))]
        else:
            variants = [(s,s,False,'MARKET',None) for s in registration['native_alternatives']]
        for label,identity,reviewed,method,params in variants:
            row = {'variant':label,'strategy_id':identity,'timeframe':tf,'reviewed_entry_policy':reviewed,
                   'entry_method':method,'parameters':params.payload() if params else StrategyParameters().payload(),'segments':{}}
            with patch('autotrader.opportunity.engine.SuccessorOpportunityEngine', ReviewedEngine if reviewed else SuccessorOpportunityEngine):
                for segment, dates in registration['segments'].items():
                    start, end = [datetime.fromisoformat(d).replace(tzinfo=UTC) for d in dates]
                    options = {'successor_parameters':params} if params else {}
                    row['segments'][segment] = compact(sim.run(start=start,end=end,strategy_ids={identity},entry_method=method,costs=Costs(**{k:D(v) for k,v in registration['normal_costs'].items()}),**options))
                dates = registration['segments']['sealed_test']
                row['stress_sealed_test'] = compact(sim.run(start=datetime.fromisoformat(dates[0]).replace(tzinfo=UTC),end=datetime.fromisoformat(dates[1]).replace(tzinfo=UTC),strategy_ids={identity},entry_method=method,costs=Costs(**{k:D(v) for k,v in registration['stress_costs'].items()}),**options))
            results.append(row)
            print(tf,label,row['segments']['sealed_test'].get('net_profit'),row['segments']['sealed_test'].get('trades'),flush=True)
            (OUT/'research-results.json').write_text(json.dumps({'schema':'v471-fixed-ablation/1','registration_sha256':digest((OUT/'research-registration.json').read_bytes()),'results':results,'complete':len(results)==17,'elapsed_seconds':time.monotonic()-started,'profitability':'UNKNOWN','automatic_promotion':False,'limitations':[*registration['limitations'],'Entry-policy ablation uses unchanged historical bar-based exit simulator. New position-specific discretionary exits are verified separately; these numbers are not a full new-runtime backtest.','Historical intrabar paths and L2 are unavailable; fills are conservative model outcomes.']},indent=2,default=str)+'\n')
    print('Complete',flush=True)

if __name__=='__main__':main()
