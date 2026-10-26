"""Fixed, versioned historical comparison; never writes a prospective ledger.

These Coinbase EUR OHLCV datasets were used by earlier releases. The final
chronological segment is a reused holdout, not fresh independent validation.
"""
from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from autotrader.opportunity.engine import SUCCESSOR_REGISTRY, SuccessorParameters
from autotrader.research.artifacts import source_fingerprint
from autotrader.research.data import digest, load_dataset
from autotrader.research.experimental import EXPERIMENTAL_REGISTRY
from autotrader.research.simulation import Costs, ResearchSimulation
from autotrader.research.strategies import REGISTRY, StrategyParameters
from autotrader.shadow.versions import convert, legacy_module, verify_legacy, verify_v44
from autotrader.strategies import LegacyStrategyEngine

DEST = Path('docs/evidence/v4_7')
KEYS = ('net_profit','total_return','trades','win_rate','profit_factor','max_drawdown',
        'expectancy','fees','spread_cost','slippage_cost','rejections','regime_observations',
        'first_blocking_stages','opportunity_counts','asset_contributions','regime_contributions',
        'open_positions_at_end','start','end_exclusive','timeframe')


def compact(report):
    return {k:report[k] for k in KEYS if k in report}


def main():
    DEST.mkdir(exist_ok=True, parents=True)
    root = Path('.data/research')
    catalog = json.loads((root/'catalog.json').read_text())['manifests']
    specs = [*REGISTRY,*EXPERIMENTAL_REGISTRY,*SUCCESSOR_REGISTRY]
    registration = {'schema':'v47-fixed-research/1','evidence_category':'HISTORICAL_PROXY_RESEARCH',
        'source_fingerprint':source_fingerprint()[0], 'retuning':False,
        'timeframes':['5m','15m','1h','4h'], 'primary_5m_days':21,
        'chronological_splits':[.6,.2,.2], 'purge_bars':144,
        'reused_test_data':True,'multiple_testing':'Descriptive panel; no winner promotion or independent significance claim.',
        'execution':'Existing EUR500 research simulator. Not a backtest of EUR7000 portfolio allocation.',
        'costs':{'fee_bps':'10','slippage_bps':'8','spread_bps':'10'},
        'dataset_hashes':{m['symbol']+':'+m['timeframe']:m['file_sha256'] for m in catalog},
        'registry':[{'strategy_id':s.strategy_id,'version':s.version,'filter_only':s.filter_only,
                     'primary_paper_selected':s in SUCCESSOR_REGISTRY} for s in specs],
        'successor_trials':[SuccessorParameters().payload(),replace(SuccessorParameters(),holding_bars=72,target_atr=D(3)).payload()]}
    (DEST/'research-registration.json').write_text(json.dumps(registration,indent=2)+'\n')
    results=[];started=time.monotonic()
    for tf,days in [('5m',21),('15m',60),('1h',180),('4h',180)]:
        manifests=[m for m in catalog if m['timeframe']==tf]
        end=min(datetime.fromisoformat(m['requested_end_exclusive']) for m in manifests)
        start=end-timedelta(days=days)
        bars=[b for m in manifests for b in load_dataset(root,m) if start<=datetime.fromisoformat(b.start)<end]
        print('Panel',tf,len(bars),flush=True)
        sim=ResearchSimulation(bars,experimental=tf=='5m')
        times=sim.times
        segments={'training':(times[min(720,len(times)//10)],times[int(len(times)*.6)-1]),
                  'validation':(times[int(len(times)*.6)+min(144,len(times)//30)],times[int(len(times)*.8)-1]),
                  'reused_holdout':(times[int(len(times)*.8)+min(144,len(times)//30)],times[-1])}
        # Experimental engine includes native V4 entries too; run V4 under its
        # original engine, then original experimental engine on the same panel.
        from autotrader.research.experimental import ExperimentalStrategyEngine
        from autotrader.research.strategies import V4StrategyEngine
        for group, engine_type, members in [('V4',V4StrategyEngine,REGISTRY),('V42',ExperimentalStrategyEngine,EXPERIMENTAL_REGISTRY)]:
            if group=='V42' and tf!='5m':
                for spec in members:
                    results.append({'strategy_id':spec.strategy_id,'version':spec.version,'timeframe':tf,
                        'status':'INCOMPATIBLE_FROZEN_PRIMARY_TIMEFRAME','reason':'Original completed_context requires 5m; not rewritten to manufacture a longer-horizon result.'})
                continue
            sim.experimental=group=='V42'
            sim._signal_cache.clear()
            for spec in members:
                if spec.filter_only:
                    results.append({'strategy_id':spec.strategy_id,'version':spec.version,'timeframe':tf,'status':'VETO_ONLY_NO_STANDALONE_TRADES'})
                    continue
                runs={}
                for label,(a,b) in segments.items():
                    runs[label]=compact(sim.run(start=a,end=b,strategy_ids={spec.strategy_id},parameters=StrategyParameters()))
                results.append({'strategy_id':spec.strategy_id,'version':spec.version,'timeframe':tf,'status':'EVALUATED','segments':runs})
                print(tf,spec.strategy_id,runs['reused_holdout'].get('net_profit'),runs['reused_holdout'].get('trades'),flush=True)
        # Old ensemble was never a set of individually authorized strategies.
        if tf=='5m':
            sim.experimental=False
            legacy=LegacyStrategyEngine()
            count={}
            for context in sim.features.values():
                for f in context.values():
                    for s in legacy.generate(f,context.get('BTC-EUR'),context.get('ETH-EUR')):
                        row=count.setdefault(s.strategy_id,{'observations':0,'positive_scores':0,'vetoes':0})
                        row['observations']+=1;row['positive_scores']+=s.score>0;row['vetoes']+=bool(s.evidence.get('veto'))
            a,b=segments['reused_holdout']
            results.append({'strategy_id':'V3.4_LEGACY_ENSEMBLE','timeframe':tf,'status':'EVALUATED_AS_ORIGINAL_ENSEMBLE',
                'signal_members':count,'segments':{'reused_holdout':compact(sim.run(start=a,end=b,strategy_ids=set(count),legacy=True))},
                'limitation':'Individual old scores do not define complete standalone entry policies; evaluated together as implemented.'})
            sim.experimental=True;sim.enable_successors()
            for spec in SUCCESSOR_REGISTRY:
                trials=[]
                for params in (SuccessorParameters(),replace(SuccessorParameters(),holding_bars=72,target_atr=D(3))):
                    runs={label:compact(sim.run(start=a,end=b,strategy_ids={spec.strategy_id},successor_parameters=params)) for label,(a,b) in segments.items()}
                    trials.append({'parameters':params.payload(),'segments':runs})
                a,b=segments['reused_holdout']
                stress=compact(sim.run(start=a,end=b,strategy_ids={spec.strategy_id},successor_parameters=SuccessorParameters(),costs=Costs(fee_bps=D(15),slippage_bps=D(12),spread_bps=D(15))))
                results.append({'strategy_id':spec.strategy_id,'version':spec.version,'timeframe':tf,'status':'EVALUATED','trials':trials,'stress':stress})
                print(tf,spec.strategy_id,'trials complete',flush=True)
        else:
            results.extend({'strategy_id':s.strategy_id,'version':s.version,'timeframe':tf,'status':'INCOMPATIBLE_FROZEN_PRIMARY_TIMEFRAME',
                'reason':'Successor primary is frozen at 5m with completed 15m/1h context. Original V4 hypotheses above test longer holding horizons.'} for s in SUCCESSOR_REGISTRY)
        (DEST/'research-results.json').write_text(json.dumps({'registration_sha256':digest((DEST/'research-registration.json').read_bytes()),
            'results':results,'elapsed_seconds':time.monotonic()-started,'complete':tf=='4h',
            'conclusion':'No validated predictive edge or live authority follows from this reused historical panel.'},indent=2,default=str)+'\n')
    frozen={'v42_files':len(verify_legacy()),'v44_files':len(verify_v44()),'strategy_bytes_changed':False}
    # Run exact frozen historical V4.2 simulation on the same bounded window.
    legacy_sim=legacy_module('research.simulation').ResearchSimulation(convert(bars))
    a,b=segments['reused_holdout']
    frozen['v42_4h']={s.strategy_id:compact(legacy_sim.run(start=a,end=b,strategy_ids={s.strategy_id})) for s in REGISTRY if not s.filter_only}
    (DEST/'frozen-research.json').write_text(json.dumps(frozen,indent=2,default=str)+'\n')
    print('Complete',round(time.monotonic()-started,1),'seconds',flush=True)


if __name__=='__main__':main()
