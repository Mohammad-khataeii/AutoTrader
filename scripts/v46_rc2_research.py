"""Locked RC1/RC2 comparison, training-only selection and separately acquired forward history."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import autotrader
from autotrader.opportunity.engine import SuccessorParameters
from autotrader.opportunity.rc1 import SuccessorParameters as RC1Parameters
from autotrader.research.data import (
    ASSETS,
    CoinbaseHistory,
    canonical,
    digest,
    load_dataset,
)
from autotrader.research.simulation import Costs, ResearchSimulation

OUT=Path('.tools/v46-rc2-research')
DEST=Path('docs/evidence/v4_6_rc2')
NEW=('A3_COST_AWARE_CONTINUATION','B3_STATEFUL_BREAKOUT','E3_ADAPTIVE_RELATIVE_STRENGTH')


def compact(r):
    keys=('net_profit','trades','fills_count','max_drawdown','sharpe_ratio','profit_factor','win_rate','expectancy',
        'average_gain','average_loss','average_holding_seconds','fees','spread_cost','slippage_cost','total_return',
        'average_exposure_eur','rejections','opportunity_counts','first_blocking_stages','regime_observations',
        'grouped_closed_position_statistics','costs','start','end_exclusive','pending_conditional_entries_at_end',
        'open_positions_at_end','effective_independent_entry_dates')
    return {k:r[k] for k in keys}


async def acquire(start,end):
    provider=CoinbaseHistory(OUT/'additional-history')
    bars=[];sources={}
    try:
        for asset in ASSETS:
            symbol=asset+'-EUR'
            values,source=await provider.fetch(symbol,'5m',start,end)
            # Existing validation rejects bad bars; page overlap is deduplicated explicitly.
            unique={b.start:b for b in values}
            bars.extend(unique.values());sources[symbol]={'bars':len(unique),'provenance':source}
            print('Additional history',symbol,len(unique),flush=True)
    finally:await provider.close()
    payload=[asdict(b) for b in bars]
    path=OUT/'additional-bars.json'
    encoded=canonical(payload)
    if path.exists():assert path.read_bytes()==encoded,'Independent history changed; retain prior acquisition'
    else:path.write_bytes(encoded)
    return bars,{'file_sha256':digest(encoded),'sources':sources,'start':start.isoformat(),'end_exclusive':end.isoformat()}


def main():
    OUT.mkdir(parents=True,exist_ok=True);DEST.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter()
    previous=json.loads(Path('docs/evidence/v4_6/research-comparison.json').read_text())
    old=previous['preregistered'];end=datetime.fromisoformat(old['end_exclusive']);start=end-timedelta(days=60)
    root=Path('.data/research');catalog=json.loads((root/'catalog.json').read_text())
    manifests=[m for m in catalog['manifests'] if m['timeframe']=='5m']
    assert {m['symbol']:m['file_sha256'] for m in manifests}==old['dataset_hashes']
    bars=[b for m in manifests for b in load_dataset(root,m) if start<=datetime.fromisoformat(b.start)<end]
    p=SuccessorParameters(entry_reference='ASK')
    grids={NEW[0]:[p,replace(p,entry_mode='RECOVERY'),replace(p,stop_basis='ATR_CAP'),replace(p,target_basis='STRUCTURE'),replace(p,target_atr=D('1.5')),replace(p,holding_bars=72)],
        NEW[1]:[p,replace(p,breakout_hold_bars=0),replace(p,compression_width=D('.015'),breakout_volume=D('1.5'),retest_bars=6),replace(p,compression_width=D('.03'),breakout_volume=D('1.2'),retest_bars=12),replace(p,holding_bars=72)],
        NEW[2]:[p,replace(p,relative_model='INDEPENDENT_VARIANCE'),replace(p,relative_z=D('.5')),replace(p,relative_z=D('1.25')),replace(p,target_basis='STRUCTURE'),replace(p,holding_bars=72)]}
    package=Path(autotrader.__file__).parent
    files={str(x.relative_to(package)):digest(x.read_bytes()) for x in sorted(package.rglob('*.py'))}
    prereg={'schema':'locked-research/4.6-rc2','source_files':files,'source_fingerprint':digest(canonical(files)),
        'dataset_hashes':old['dataset_hashes'],'chronological_split':old['split'],'training_start':old['actual_start'],
        'reused_test_not_untouched':True,'additional_interval_start':end.isoformat(),'additional_interval_end_exclusive':'2026-10-22T00:00:00+00:00',
        'grids':{s:[p.payload() for p in ps] for s,ps in grids.items()},'selection':'Training net PnL minus EUR500*drawdown, minimum 8 closed positions. If none qualify retain preregistered default, report failure.',
        'cost_models':{'base':asdict(Costs()),'stress':asdict(Costs(fee_bps=D(15),slippage_bps=D(12),spread_bps=D(15),liquidity_fraction=D('.002')))},
        'limits':['Previously studied assets and intervals; no causal edge or calibrated probabilities.',
            'No historical connected-exchange depth. Fixed spread, fees, slippage and prior volume depth are assumptions.',
            'Newly downloaded interval remains short; current surviving asset universe, cross-asset and serial dependence remain.',
            'Conditional entries are expiring IOC watches, no passive queue or first-touch guarantee.']}
    preg=OUT/'preregistered.json';encoded=json.dumps(prereg,indent=2,default=str)+'\n'
    if preg.exists():assert preg.read_text()==encoded,'Preregistered source or design changed'
    else:preg.write_text(encoded)
    train_start=datetime.fromisoformat(old['actual_start']);train_end=datetime.fromisoformat(old['split']['train_end_exclusive'])
    valid_start=datetime.fromisoformat(old['split']['validation_start']);valid_end=datetime.fromisoformat(old['split']['validation_end_exclusive']);test_start=datetime.fromisoformat(old['split']['test_start'])
    print('Building matched completed-candle panel',flush=True)
    sim=ResearchSimulation(bars,successor=True)
    baseline={};chosen={};training={};results={}
    for strategy in NEW:
        old_parameters=RC1Parameters.from_payload(previous['successors'][strategy]['parameters'])
        baseline[strategy]=compact(sim.run(start=test_start,end=end,strategy_ids={strategy},successor_parameters=old_parameters,successor_revision='RC1'))
        expected=previous['successors'][strategy]['test']
        assert abs(baseline[strategy]['net_profit']-expected['net_profit'])<1e-9 and baseline[strategy]['trades']==expected['trades'],'RC1 matched baseline parity failed'
        values=[]
        for i,param in enumerate(grids[strategy]):
            r=compact(sim.run(start=train_start,end=train_end,strategy_ids={strategy},successor_parameters=param));values.append(r)
            print(strategy,'train',i,r['net_profit'],r['trades'],flush=True)
        valid=[i for i,r in enumerate(values) if r['trades']>=8]
        index=max(valid,key=lambda i:values[i]['net_profit']-500*values[i]['max_drawdown']) if valid else 0
        chosen[strategy]=grids[strategy][index];training[strategy]={'grid':values,'index':index,'training_sample_adequate':bool(valid)}
    locked={'parameters':{s:p.payload() for s,p in chosen.items()},'preregistered_sha256':digest(preg.read_bytes()),'locked_before_additional_history_acquisition':True}
    (OUT/'locked-parameters.json').write_text(json.dumps(locked,indent=2)+'\n')
    # Fetch only after the source, candidate set and training choices are locked.
    independent_end=datetime(2026,10,22,tzinfo=UTC)
    added,provenance=asyncio.run(acquire(end-timedelta(days=3),independent_end))
    print('Building newly acquired interval panel',flush=True)
    new_sim=ResearchSimulation(added,successor=True)
    for strategy,param in chosen.items():
        def run(a,b,selected=strategy,parameters=param,**kw):return compact(sim.run(start=a,end=b,strategy_ids={selected},successor_parameters=parameters,**kw))
        validation=run(valid_start,valid_end);test=run(test_start,end)
        stress=run(test_start,end,costs=Costs(fee_bps=D(15),slippage_bps=D(12),spread_bps=D(15),liquidity_fraction=D('.002')))
        timing={m:run(test_start,end,entry_method=m) for m in ('BID_IOC','PULLBACK_IOC','RETEST_IOC')}
        windows=[run(a,b) for a,b in ((valid_start,valid_end),(test_start,test_start+(end-test_start)/2),(test_start+(end-test_start)/2,end))]
        additional=compact(new_sim.run(start=end,end=independent_end,strategy_ids={strategy},successor_parameters=param))
        old_additional=compact(new_sim.run(start=end,end=independent_end,strategy_ids={strategy},successor_parameters=RC1Parameters.from_payload(previous['successors'][strategy]['parameters']),successor_revision='RC1'))
        gates={'validation_positive':validation['net_profit']>0,'reused_test_positive':test['net_profit']>0,'new_interval_positive':additional['net_profit']>0,
            'new_interval_at_least_30_closed_positions':additional['trades']>=30,'cost_stress_positive':stress['net_profit']>0,
            'minimum_two_positive_locked_windows':sum(w['net_profit']>0 for w in windows)>=2,'drawdown_below_five_percent':test['max_drawdown']<.05}
        results[strategy]={'parameters':param.payload(),'training':training[strategy],'validation':validation,'test':test,'cost_stress':stress,
            'entry_timing':timing,'locked_windows':windows,'three_market_comparison':run(test_start,end,universe={'BTC-EUR','ETH-EUR','SOL-EUR'}),
            'sizing_sensitivity':{str(q):run(test_start,end,quote_budget_eur=D(q)) for q in (25,75,100)},
            'new_interval':additional,'rc1_new_interval':old_additional,'validation_gates':gates,'status':'UNVALIDATED' if not all(gates.values()) else 'PROSPECTIVE_RESEARCH_REVIEW_REQUIRED'}
        print(strategy,'test',test['net_profit'],test['trades'],'new interval',additional['net_profit'],additional['trades'],flush=True)
        (OUT/(strategy+'.json')).write_text(json.dumps(results[strategy],indent=2)+'\n')
    assert files=={str(x.relative_to(package)):digest(x.read_bytes()) for x in sorted(package.rglob('*.py'))},'Executed source changed during research'
    report={'schema':'comparison/4.6-rc2','evidence_class':'HISTORICAL_PROXY_RESEARCH_NOT_PAPER_FILL_HISTORY','preregistered':prereg,
        'locked_parameters':locked,'additional_history':provenance,'baseline':baseline,'successors':results,
        'duration_seconds':time.perf_counter()-started,'promotions':[],'new_accounts_created':False,'verdict':'Engineering evidence only; no automatic approval or allocation.'}
    encoded=json.dumps(report,indent=2,default=str)+'\n'
    (OUT/'comparison-v46-rc2.json').write_text(encoded);(DEST/'research-comparison.json').write_text(encoded)


if __name__=='__main__':main()
