"""Reproduce stage-aware research on read-only original Aruba exports.

No training inputs are reconstructed from later candles. Optional regime
counterfactuals use completed historical bar versions available in the export;
their original first-observation time is not proven, so they cannot validate a
primary policy or prospective performance.
"""
from __future__ import annotations

import argparse
import bisect
import gzip
import json
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

from autotrader.domain import Candle
from autotrader.learning.controller import mature as mature_plan
from autotrader.learning.controller import run_training
from autotrader.learning.features import stamp
from autotrader.learning.lifecycle import ingest, mature, summary
from autotrader.learning.market_model import status, tick
from autotrader.learning.regimes import assess, shadow_hypotheses
from autotrader.learning.store import Store
from autotrader.research.artifacts import source_fingerprint
from autotrader.research.data import canonical, digest


def read(path):
    with gzip.open(path,'rt') as stream:
        for line in stream:
            row=json.loads(line)
            if row.get('type')!='complete':yield row


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    header=json.loads((args.source/'header.json').read_text());now=header['until']
    import hashlib
    exported=json.loads((args.source/'export-manifest.json').read_text())
    assert exported['status']=='PASS'
    for name,expected in exported['files'].items():
        with (args.source/name).open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==expected
    paths=defaultdict(list)
    for c in read(args.source/'candles.jsonl.gz'):paths[c['symbol']].append(c)
    indexes={s:[stamp(c['timestamp']) for c in rows] for s,rows in paths.items()}
    store=Store(args.output/'research');total=0;regime_cache={};hist=Counter();hypotheses=defaultdict(list)
    technical=Counter();primary_gates=Counter()
    signals=iter(read(args.source/'signals.jsonl.gz'));next(signals)
    for row in signals:
        e=row['payload_json'].get('evidence') or {};event={'id':row['signal_id'],'symbol':row['symbol'],
            'strategy_id':row['strategy_id'],'observed_at':row['created_at'],'evidence':e,
            'baseline_eligible':e.get('entry_eligible') is True,'evidence_category':'REVOLUT_X_PROSPECTIVE_PAPER',
            'rejection':','.join(e.get('reasons',[]))}
        ingest(store,event,now);total+=1
        technical['signals']+=1;technical['technical']+=e.get('technical_eligible') is True
        technical['economic']+=e.get('economic_eligible') is True;technical['baseline_entry_eligible']+=e.get('entry_eligible') is True
        primary_gates.update(k for k,v in (e.get('primary_admission',{}).get('gates') or {}).items() if v is False)
        observed=stamp(event['observed_at']);symbol=event['symbol'];times=indexes[symbol]
        left=bisect.bisect_left(times,observed);right=bisect.bisect_right(times,observed+timedelta(hours=4))
        future=paths[symbol][left:right]
        pending=store.db.execute('SELECT payload FROM market_observations WHERE id=?',(event['id'],)).fetchone()
        if pending:mature(store,json.loads(pending[0]),future,now)
        pending_plan=store.db.execute('SELECT payload FROM observations WHERE id=?',(event['id'],)).fetchone()
        if pending_plan:
            mature_plan(store,json.loads(pending_plan[0]),future,now)
        # Reconstruct only technical candidates and hourly context samples.
        as_of=e.get('as_of');end=stamp(as_of)+timedelta(minutes=5) if as_of else None
        if end and (e.get('technical_eligible') or end.minute==0):
            key=(symbol,as_of)
            if key not in regime_cache:
                histories={}
                for s in {symbol,'BTC-EUR','ETH-EUR'}:
                    last=bisect.bisect_right(indexes[s],end-timedelta(minutes=5));raw=paths[s][max(0,last-1152):last]
                    histories[s]=[Candle(s,stamp(c['timestamp']),*[D(c[k]) for k in ('open','high','low','close','volume')],'5m',c['source']) for c in raw]
                regime_cache[key]=assess(histories[symbol],{s:histories[s] for s in ('BTC-EUR','ETH-EUR')},end)
                hist[regime_cache[key]['state']]+=1
            state=regime_cache[key];hyp=shadow_hypotheses({**e,'strategy_id':event['strategy_id']},state)
            plan=store.db.execute("SELECT result FROM observations WHERE id=? AND status='LABELED'",(event['id'],)).fetchone()
            if plan:
                result=json.loads(plan[0])
                for name in ('approved_baseline','confirmed_transition','confirmed_breakout_retest'):
                    if hyp[name]:hypotheses[name].append(result)
        if total%2000==0:store.db.commit();print(json.dumps({'processed':total}),flush=True)
    plan_report=run_training(store,now);market_report=tick(store,now);store.db.commit()
    from autotrader.learning.evaluation import independent
    comparisons={}
    for name,rows in hypotheses.items():
        episodes=independent(rows)
        comparisons[name]={'signals':len(rows),'independent_episodes':len(episodes),
            'modeled_net_r':sum(r['target']['net_r'] for r in episodes)/len(episodes) if episodes else None,
            'cost_stress_2x_net_r':sum(r['stress_target']['net_r'] for r in episodes)/len(episodes) if episodes else None,
            'scope':'Historical modeled path on original priced plans; no executable fill proof'}
    financial=defaultdict(lambda:defaultdict(list))
    for r in read(args.source/'financial.jsonl.gz'):financial[r['database']][r['section']].append(r['row'])
    ledgers=[]
    for name,tables in financial.items():
        positions=tables['positions'];closed=[p for p in positions if p['state']=='CLOSED']
        ledgers.append({'database':name,'closed_positions':len(closed),'open_positions':len(positions)-len(closed),
            'closed_realized_pnl':str(sum((D(p['realized_pnl']) for p in closed),D(0))),
            'fees':str(sum((D(f['fee']) for f in tables['fills']),D(0))),
            'initial_funding_events':sum(r['event_type']=='INITIAL_FUNDING' for r in tables['financial_journal']),
            'section_counts':{k:len(v) for k,v in tables.items()}})
    coverage_by_profile=[{'profile':p,'disposition':d,'signals':n} for p,d,n in store.db.execute('SELECT profile,disposition,count(*) FROM funnel GROUP BY profile,disposition')]
    candidate_by_profile=[{'profile':p,'signals':n,'technical':t,'economic':c,'original_entry_eligible':b} for p,n,t,c,b in store.db.execute("SELECT profile,count(*),sum(json_extract(metadata,'$.technical')),sum(json_extract(metadata,'$.economic')),sum(json_extract(metadata,'$.baseline_eligible')) FROM funnel GROUP BY profile")]
    # Test fixed stop alternatives on all nine recorded primary entries. These
    # remain candle-path scenarios, never replacements for actual managed exits.
    import copy

    from autotrader.learning.targets import label
    forensic=json.loads((Path(__file__).resolve().parents[1]/'docs/evidence/v4_9_2/forensics.json').read_text())
    primary_name=header['registry']['primary']['database_name'];primary_fills=financial[primary_name]['fills']
    exit_scenarios=[]
    for trade in forensic['trades']:
        original=copy.deepcopy(trade['original_entry_evidence']);m=original['economics']['measurements']
        price,quantity,a=D(trade['entry_price']),D(trade['quantity']),D(m['atr'])
        buy_fee=sum((D(f['fee']) for f in primary_fills if f['position_id']==trade['position_id'] and f['side']=='BUY'),D(0))
        m['entry']['vwap']=str(price);m['fillable_quantity']=str(quantity);m['cost_basis_eur']=str(price*quantity+buy_fee)
        original['entry_plan']['stop']=trade['initial_stop']
        event={'id':trade['position_id'],'symbol':trade['symbol'],'observed_at':trade['entry_at'],'evidence':original}
        start=stamp(trade['entry_at']);idx=indexes[trade['symbol']]
        future=paths[trade['symbol']][bisect.bisect_left(idx,start):bisect.bisect_right(idx,start+timedelta(hours=4))]
        variants={}
        for name,k in [('original_fixed_plan',None),('minimum_1_5_atr',D('1.5')),('minimum_2_atr',D(2))]:
            scenario=copy.deepcopy(event)
            stop=min(D(trade['initial_stop']),price-k*a) if k is not None else D(trade['initial_stop'])
            scenario['evidence']['entry_plan']['stop']=str(stop)
            try:variants[name]={'stop_distance_atr':str((price-stop)/a),'target':label(scenario,future,240),'cost_stress_2x':label(scenario,future,240,cost_stress=2.),'changed_live_stops':False}
            except (ValueError,KeyError,IndexError,ZeroDivisionError) as error:variants[name]={'status':'UNAVAILABLE','reason':str(error)}
        exit_scenarios.append({'position_id':trade['position_id'],'symbol':trade['symbol'],'entry_profile':trade['execution_profile'],
            'actual_net_pnl_eur':trade['net_pnl_eur'],'recorded_stop_consistent':trade['stop_condition_consistent'],
            'entry_stop_distance_atr':str((price-D(trade['initial_stop']))/a),
            'actual_round_trip_fees':trade['fees_eur'],'variants':variants,
            'patient_entry':'No executable future quote assumed; no counterfactual fill or profit assigned',
            'scope':'Historical fixed-plan scenario using actual entry VWAP and fee, original targets, declared constant entry spread/impact and future recorded mid bars; not a replay of managed production exits'})
    base={'status':'PASS','source_fingerprint':source_fingerprint()[0],
          'coverage_by_original_profile':coverage_by_profile,'candidate_counts_by_original_profile':candidate_by_profile,
          'nine_entry_stop_research':exit_scenarios,'source_export_sha256':digest((args.source/'export-manifest.json').read_bytes()),
          'source_window':{'since':header['since'],'until':now},'original_signals':total,
          'funnel':summary(store),'market_task':status(store,now),'plan_training':plan_report,
          'market_training':market_report,'recorded_candidate_counts':dict(technical),
          'original_primary_failed_gates':dict(primary_gates),'reconstructed_unique_contexts':len(regime_cache),
          'reconstructed_context_states':dict(hist),'hypothesis_comparison':comparisons,
          'financial_ledgers':ledgers,'primary_policy_changed':False,'new_primary_model':None,
          'conclusion':'INCONCLUSIVE: retain existing primary admission, risk and exits. Continue isolated collection.',
          'limitations':['48-hour signal sample cannot satisfy 45-day/240-independent-episode qualification',
             'Historical regime reconstruction uses exported completed bar versions without proving first-observed availability; excluded from model input generation',
             'Hourly context sample plus all technical candidates, not an unbiased market-frequency estimate',
             'Market-path returns are midpoint observations without costs or executable entry; priced paths use declared historical cost assumptions',
             'Shadow financial ledgers have distinct capital, sizing and entry policies; absolute P&L is not an equal-risk primary comparison',
             'No synthetic acceptance result demonstrates prospective profit']}
    # Bounded evidence: latest full producer context is reported by live collector, not this historical audit.
    base['funnel'].pop('latest',None)
    (args.output/'audit-analysis.json').write_bytes(canonical(base)+b'\n')
    (args.output/'export-manifest.json').write_bytes((args.source/'export-manifest.json').read_bytes())
    store.close();print(json.dumps({'status':'PASS','signals':total,'funnel':base['funnel']['dispositions'],'market':base['market_task']['counts']}),flush=True)

if __name__=='__main__':main()
