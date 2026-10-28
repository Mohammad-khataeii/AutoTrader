"""Causal structural reconstruction; future quote paths remain hypothetical.

Uses genuine exported public observations. No orders or database writes occur.
The named audit archive was unavailable; exact scope differences are disclosed.
"""
from __future__ import annotations

import itertools
import json
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

from autotrader.domain import Candle, OrderBook, OrderBookLevel, TradingPair
from autotrader.raoe import IDENTITIES
from autotrader.raoe.plans import construct
from autotrader.raoe.playbooks import setup
from autotrader.raoe.regime import assess
from autotrader.research.data import canonical, digest

OUT=Path('docs/evidence/v4_9')
CUTOFF=datetime.fromisoformat('2026-10-28T05:16:06+00:00')


def path_result(bars: list[Candle], start: datetime, stop: D, target: D, hours: int=6) -> dict[str,Any]:
    horizon=start+timedelta(hours=hours)
    path=[b for b in bars if start<=b.timestamp and b.timestamp+timedelta(minutes=5)<=min(horizon,CUTOFF)]
    for b in path:
        if b.low<=stop:return {'price_path':'STOP_FIRST','ambiguous':b.high>=target,'at':b.timestamp.isoformat(),'execution_proven':False}
        if b.high>=target:return {'price_path':'TARGET_FIRST','at':b.timestamp.isoformat(),'execution_proven':False}
    return {'price_path':'UNRESOLVED','available_bars':len(path),'execution_proven':False}


def main() -> None:
    raw=json.loads((OUT/'recorded-market-history.json').read_text())
    histories={s:[Candle(s,datetime.fromisoformat(r['timestamp']),*[D(r[k]) for k in ['open','high','low','close','volume']],'5m',r['source']) for r in rows] for s,rows in raw['candles'].items()}
    cases=json.loads((OUT/'pepe-original-signals.json').read_text())['cases']
    pairs=json.loads((OUT/'recorded-instruments.json').read_text())
    signals=json.loads((OUT/'recorded-signal-index.json').read_text())
    quotes=json.loads((OUT/'pepe-recorded-quotes.json').read_text())['quotes']
    result=[]
    for case in cases:
        original=case['signal'];e=original['evidence'];asof=datetime.fromisoformat(e['raoe_regime']['as_of'])
        bars=[b for b in histories['PEPE-EUR'] if b.timestamp+timedelta(minutes=5)<=asof][-720:]
        ask=D(case['case_quote']);metadata=pairs['PEPE-EUR']
        pair=TradingPair('PEPE-EUR','PEPE','EUR',price_step=D(metadata['price_step']),quantity_step=D(metadata['quantity_step']),min_order_quote=D(metadata['min_order_quote']))
        # A one-unit quote holder supplies only a price to the pure planner.
        # It is explicitly not an L2 reconstruction and cannot authorize fills.
        holder=OrderBook(pair.symbol,asof,(OrderBookLevel(ask*D('.999'),D(1)),),(OrderBookLevel(ask,D(1)),),'QUOTE_ONLY_NO_EXECUTION_DEPTH')
        peers={}
        for symbol,context in e['raoe_regime']['benchmarks'].items():
            last=datetime.fromisoformat(context['last_closed_at'])
            peers[symbol]=[b for b in histories[symbol] if b.timestamp<=last][-720:]
        actual=assess(bars,asof,peers)
        pattern=setup(original['strategy_id'],bars,actual)
        plan=construct(original['strategy_id'],bars,pair,holder,actual,pattern)
        synced=assess(bars,asof,{s:[b for b in v if b.timestamp+timedelta(minutes=5)<=asof][-720:] for s,v in histories.items() if s in {'BTC-EUR','ETH-EUR'}})
        continuation=setup(IDENTITIES[-1],bars,{**synced,'liquidity_adequate':False})
        summary=(e.get('economics') or {}).get('measurements',{})
        payoff=None
        if summary and plan.get('targets'):
            quantity=D(summary['fillable_quantity']);basis=D(summary['cost_basis_eur'])
            factor=D(summary['exit_now']['net_unit_proceeds'])/D(summary['exit_now']['best_bid'])
            loss=basis-quantity*D(plan['stop'])*factor
            gain=quantity*D(plan['targets'][0])*factor-basis
            cost=D(summary['estimated_total_round_trip_cost_eur'])
            payoff={'evidence':'Recorded original entry/exit cost summary reused as explicit future-impact assumption; full book absent',
                'first_target_net_eur':str(gain),'planned_stop_loss_eur':str(loss),'net_reward_risk':str(gain/loss) if loss>0 else None,
                'cost_eur':str(cost),'passes_net_R_and_cost_headroom':gain>=D('1.2')*loss and gain>=2*cost}
        created=datetime.fromisoformat(case['created_at']);later=[q for q in quotes if datetime.fromisoformat(q['feature_created_at'])>created and q.get('best_bid') and q.get('best_ask')]
        scenarios=[]
        for method in ['PROMPT_ORIGINAL_ASK','NEXT_COMPLETED_CANDLE','PATIENT_WITHIN_15_MINUTES']:
            execution_ask=ask;entry_at=created
            if method=='NEXT_COMPLETED_CANDLE':
                matching=next((q for q in later if datetime.fromisoformat(q['candle_at'])>datetime.fromisoformat(original['timestamp'])),None)
                if not matching:scenarios.append({'method':method,'status':'NO_LATER_QUOTE'});continue
                execution_ask=D(matching['best_ask']);entry_at=datetime.fromisoformat(matching['feature_created_at'])
            if method=='PATIENT_WITHIN_15_MINUTES':
                limit=D(e['entry_plan']['alternatives'][1]['entry'])
                matching=next((q for q in later if datetime.fromisoformat(q['feature_created_at'])<=created+timedelta(minutes=15) and D(q['best_ask'])*D('1.0008')<=limit),None)
                if not matching:scenarios.append({'method':method,'status':'NO_OBSERVED_EXECUTABLE_ASK_AT_LIMIT','fill_proven':False});continue
                execution_ask=D(matching['best_ask']);entry_at=datetime.fromisoformat(matching['feature_created_at'])
            checkpoints=[];stop=D(e['entry_plan']['stop']);unit_basis=execution_ask*D('1.0008')*D('1.001')
            target_bid=(unit_basis+D('1.2')*(unit_basis-stop*D('.9992')*D('.999')))/(D('.9992')*D('.999'))
            active=[q for q in later if datetime.fromisoformat(q['feature_created_at'])>=entry_at]
            for minutes in [20,60,180,240,360]:
                point=entry_at+timedelta(minutes=minutes)
                quote=next((q for q in active if point<=datetime.fromisoformat(q['feature_created_at'])<=point+timedelta(minutes=6)),None)
                checkpoints.append({'minutes':minutes,'status':'MISSING_QUOTE_AT_HORIZON' if quote is None else 'OBSERVED_BID_HYPOTHETICAL_EXIT',
                    'bid':quote['best_bid'] if quote else None,'net_return_before_unknown_depth':str(D(quote['best_bid'])*D('.9992')*D('.999')/unit_basis-1) if quote else None})
            outcome=path_result(histories['PEPE-EUR'],entry_at,stop,target_bid)
            highest=execution_ask;trail=stop;trailing=None
            for q in active:
                time=datetime.fromisoformat(q['feature_created_at'])
                if time>entry_at+timedelta(hours=4):break
                bid=D(q['best_bid']);highest=max(highest,bid)
                # Predeclared diagnostic: trail two ORIGINAL entry ATR after
                # crossing the 1.2R threshold; no peak-selected exit.
                if highest>=target_bid:trail=max(trail,highest-2*D(e['raoe_regime']['atr']))
                if bid<=trail:
                    trailing={'at':time.isoformat(),'bid':str(bid),'net_return':str(bid*D('.9992')*D('.999')/unit_basis-1),'fill_proven':False};break
            scenarios.append({'method':method,'entry_at':entry_at.isoformat(),'ask':str(execution_ask),'stop':str(stop),'bid_for_1_2_net_R':str(target_bid),
                'barrier_path':outcome,'fixed_time_checkpoints':checkpoints,'two_entry_atr_trailing_after_1_2_R':trailing,
                'execution_proven':False,'strategy_qualified':False,'warning':'Diagnostic cost arithmetic only. Signal/benchmark gate failures still apply; saved quotes have no future L2 or queue.'})
        result.append({'original':case,'original_rejection_preserved':True,'v49_structure':plan,'v49_pattern':pattern,
            'benchmark_under_original_available_context':actual['benchmark'],'retrospective_synchronized_benchmark':synced['benchmark'],
            'synchronized_context_was_not_necessarily_available_at_original_quote':True,
            'continuation_with_missing_depth':continuation,'cost_summary_counterfactual':payoff,'entry_timing_diagnostics':scenarios})
    # Independent price trigger, fixed 90 minute suppression per asset. Scope
    # starts at first recorded V48 signal; archive-specific scope is unavailable.
    start=min(datetime.fromisoformat(r['signal']['timestamp']) for r in signals)
    events=[]
    for symbol,bars in histories.items():
        prior_event=None
        for index,b in enumerate(bars):
            if index<12 or not start<=b.timestamp or b.timestamp+timedelta(minutes=5)>CUTOFF:continue
            context=bars[index-12:index+1]
            if any(y.timestamp-x.timestamp!=timedelta(minutes=5) for x,y in itertools.pairwise(context)):continue
            move=b.close/bars[index-6].close-1
            if move<D('.008') or b.close<=max(c.high for c in bars[index-12:index]):continue
            if prior_event and b.timestamp-prior_event<timedelta(minutes=90):continue
            prior_event=b.timestamp
            matched=[r for r in signals if r['signal']['symbol']==symbol and datetime.fromisoformat(r['signal']['timestamp'])==b.timestamp and datetime.fromisoformat(r['created_at'])<=CUTOFF]
            eligible=next((r['signal'] for r in matched if r['signal']['strategy_id']=='RAOE_EARLY_RECOVERY'),None)
            diagnostic=None
            if eligible:
                plan=eligible['evidence']['entry_plan'];entry=D(plan.get('entry') or 0);stop=D(plan.get('stop') or 0)
                if 0<stop<entry:
                    unit=entry*D('1.0008')*D('1.001');factor=D('.9992')*D('.999')
                    target=(unit+D('1.2')*(unit-stop*factor))/factor
                    first=next(r for r in matched if r['signal']['strategy_id']=='RAOE_EARLY_RECOVERY')
                    observed=datetime.fromisoformat(first['created_at'])
                    diagnostic={'entry_ask':str(entry),'stop':str(stop),'target_bid_for_1_2_net_R':str(target),
                        **path_result(bars,observed,stop,target),
                        'horizon_sensitivity':{str(hours):path_result(bars,observed,stop,target,hours) for hours in [1,3,6]},
                        'evidence_category':'HYPOTHETICAL_COST_BARRIER_NO_FUTURE_L2','original_strategy_qualified':False}
            events.append({'symbol':symbol,'candle_at':b.timestamp.isoformat(),'return_30m':str(move),'saved_evaluations':len(matched),
                'classification':'BLOCKED_BY_ECONOMICS' if any(r['signal']['evidence'].get('technical_eligible') for r in matched) else 'BLOCKED_BY_STRATEGY' if matched else 'MISSED_BY_DISCOVERY','fixed_1_2_net_R_diagnostic':diagnostic,'execution_proven':False,
                'original_stop':eligible['evidence']['entry_plan'].get('stop') if eligible else None,
                'reason':'Scope-limited price trigger; neither label proves net profitability'})
    original_cut=[r for r in signals if datetime.fromisoformat(r['created_at'])<=CUTOFF]
    output={'schema':'v49-development-forensics/1','evidence_category':'KNOWN_OCTOBER_DEVELOPMENT_OBSERVATIONS',
        'source_hashes':{name:digest((OUT/name).read_bytes()) for name in ['recorded-market-history.json','pepe-original-signals.json','pepe-recorded-quotes.json']},
        'pepe_cases':result,'price_trigger_episodes':sorted(events,key=lambda e:(e['candle_at'],e['symbol'])),
        'scope':{'start_candle':start.isoformat(),'cutoff':CUTOFF.isoformat(),'signals_by_persistence_cutoff':len(original_cut),'reported_archive_signals':5430,
            'scope_match':False,'reported_original_barriers':{'target_first':1,'stop_first':3,'unresolved':7},
            'barrier_reproduction':'Different explicitly modeled costs/6h horizon can yield an extra later AAVE target. Exact original CSV formula/horizon was unavailable; do not call it an exact numerical reproduction.','reason':'Named archive and CSVs unavailable. Restored current DB history yields 5460 rather than reported 5430; do not force counts or claim exact archive reproduction.'},
        'limitations':[raw['limitation'],'PEPE case A/B overlap one broader rally; never count as independent winning trades',
            'Full original RAOE L2 was not persisted for rejected plans. Quote summaries establish observed prices, not guaranteed executable fills.',
            'Case B synchronous label reconstruction is retrospective; later peer bars cannot retroactively authorize an earlier quote.',
            'Entry timing and trailing diagnostics are fully specified forensic alternatives on known data, not independent strategy validation.',
            'No V48 rejected order was replayed into any financial ledger.']}
    (OUT/'development-forensics.json').write_bytes(canonical(output)+b'\n')
    print(json.dumps({'cases':len(result),'price_episodes':len(events),'scope_signals':len(original_cut),'scope_matches_original_archive':False}))


if __name__=='__main__':main()
