"""Chronological lifecycle proxy using production plans, pricing and causal exits.

OHLCV cannot establish historical execution. The finite-depth book below is an
explicit assumption based only on the previous completed bar's volume.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from autotrader.clock import at
from autotrader.domain import Candle, OrderBook, OrderBookLevel, Side, TradingPair, quantize_down
from autotrader.execution.admission import project_buy
from autotrader.execution.policies import policy_for
from autotrader.execution.postings import closing_posting
from autotrader.execution.pricing import quote_execution, target_gross_floor
from autotrader.execution.protection import trailing_update
from autotrader.indicators import calculate_features
from autotrader.opportunity.engine import SUCCESSOR_REGISTRY, SuccessorOpportunityEngine
from autotrader.opportunity.features import enrich
from autotrader.personal_paper.exits import assess_exit
from autotrader.personal_paper.selection import reviewed_signal
from autotrader.raoe import IDENTITIES
from autotrader.raoe.engine import RAOEEngine
from autotrader.raoe.regime import assess
from autotrader.raoe.structure import classify as structure
from autotrader.research.baselines.v48.engine import RAOEEngine as V48Engine
from autotrader.research.baselines.v48.regime import assess as v48_assess

D=Decimal
ZERO=D(0)
CAPITAL=D(500)


@dataclass
class PortfolioRun:
    identity: str
    patient: bool = False
    delay: bool = False
    cash: Decimal = CAPITAL
    positions: dict[str, Any] = field(default_factory=dict)
    pending: dict[str, Any] = field(default_factory=dict)
    cooldown: dict[str, datetime] = field(default_factory=dict)
    fills: list[dict[str, Any]] = field(default_factory=list)
    closed: list[dict[str, Any]] = field(default_factory=list)
    rejected: Counter[str] = field(default_factory=Counter)
    fees: Decimal = ZERO
    spread: Decimal = ZERO
    slippage: Decimal = ZERO
    peak: Decimal = CAPITAL
    drawdown: Decimal = ZERO
    curves: list[Decimal] = field(default_factory=list)
    technical: int = 0
    feasible: int = 0
    missed: int = 0
    halted: bool = False


def simulate(bars: list[Candle], start: datetime, end: datetime, costs: dict[str,str]) -> list[dict[str,Any]]:
    fee,slip,spread=[D(costs[k]) for k in ('fee_bps','slippage_bps','spread_bps')]
    originals=[s.strategy_id for s in SUCCESSOR_REGISTRY]
    old=['V48_'+s for s in IDENTITIES[:3]]
    reviewed=['V471_'+s for s in originals]
    runs=[PortfolioRun(s) for s in [*originals,*reviewed,*old,*IDENTITIES,'MOMENTUM_30M','BUY_AND_HOLD','CASH']]
    runs += [PortfolioRun(s,True) for s in IDENTITIES]
    runs += [PortfolioRun(s,delay=True) for s in IDENTITIES]
    histories: dict[str,list[Candle]]=defaultdict(list)
    frames: dict[datetime,dict[str,Candle]]=defaultdict(dict)
    for c in bars:
        if c.timestamp<end: frames[c.timestamp][c.symbol]=c
    raoe=RAOEEngine(fee,slip)
    v48=V48Engine(fee,slip)
    baseline=SuccessorOpportunityEngine(fee_bps=fee,slippage_bps=slip)
    day_equity: dict[tuple[int,Any],Decimal]={}
    week_equity: dict[tuple[int,Any],Decimal]={}

    def book(symbol: str, mid: Decimal, stamp: datetime, used: Decimal=D(0)) -> OrderBook:
        known=histories[symbol][-1]
        quantity=max(D(0),known.volume*D('.01')-used)
        return OrderBook(symbol,stamp,(OrderBookLevel(mid*(1-spread/20000),quantity),),
            (OrderBookLevel(mid*(1+spread/20000),quantity),),'historical-assumed-finite-depth')

    def sell(run: PortfolioRun, symbol: str, mid: Decimal, stamp: datetime, reason: str,
             fraction: Decimal | None=None, target: Decimal | None=None) -> None:
        p=run.positions[symbol]
        amount=p['quantity'] if fraction is None else min(p['quantity'],fraction)
        observed=book(symbol,mid,stamp,p['used'])
        if observed.bids[0].quantity<=0:
            run.rejected['no_remaining_exit_depth']+=1;return
        with at(stamp):
            quote=quote_execution(observed,Side.SELL,amount,
                fee_bps=fee,slippage_bps=slip,limit_price=target_gross_floor(target,fee) if target else None)
        if quote.fillable_quantity<=0:
            run.rejected['unfilled_exit']+=1;return
        posting=closing_posting(p['quantity'],p['basis'],quote.fillable_quantity,quote.gross_notional,quote.fee)
        run.cash+=posting.cash_credit;p['quantity']=posting.remaining_quantity;p['basis']=posting.remaining_basis
        p['pnl']+=posting.realized_pnl;p['used']+=quote.fillable_quantity
        run.fees+=quote.fee;run.spread+=quote.fillable_quantity*mid*spread/20000
        run.slippage+=quote.fillable_quantity*mid*(1-spread/20000)*slip/10000
        run.fills.append({'side':'SELL','symbol':symbol,'at':stamp.isoformat(),'price':str(quote.vwap),
            'quantity':str(quote.fillable_quantity),'fee':str(quote.fee),'reason':reason,'net_pnl':str(posting.realized_pnl)})
        if p['quantity']==0:
            run.closed.append({'net_pnl':str(p['pnl']),'holding_seconds':(stamp-p['opened']).total_seconds(),
                'exit_reason':reason,'regime':p['evidence'].get('regime'),'entry_method':'PATIENT_IOC' if run.patient else 'CONFIRMED_REACTION_IOC'})
            del run.positions[symbol];run.cooldown[symbol]=stamp+timedelta(minutes=30)

    for stamp,frame in sorted(frames.items()):
        with at(stamp):
            features={}
            for symbol in frame:
                history=histories[symbol]
                if len(history)>=151 and history[-1].timestamp+timedelta(minutes=5)==stamp:
                    try:
                        f=enrich(calculate_features(history[-240:],D(0),spread),history,stamp)
                        f.metadata.update(liquidity_quote=history[-1].volume*frame[symbol].open*D('.02'),order_book_age_seconds=D(0))
                        features[symbol]=f
                    except ValueError: pass
            if start<=stamp<end:
                signals={}
                for symbol,f in features.items():
                    observation=book(symbol,frame[symbol].open,stamp)
                    if observation.asks[0].quantity<=0: continue
                    pair=TradingPair(symbol,symbol.split('-')[0],'EUR',min_order_quote=D(5))
                    regime=assess(histories[symbol],stamp,dict(histories))
                    old_regime=v48_assess(histories[symbol][-720:],stamp,{s:v[-720:] for s,v in histories.items()})
                    structural=structure(histories[symbol],stamp,observation.best_ask or D(0))
                    for identity in [*originals,*old,*IDENTITIES]:
                        if identity in IDENTITIES:
                            signal=raoe.evaluate(identity,f,pair,observation,candles=histories[symbol],
                                benchmarks=dict(histories),assessment=regime,structural_assessment=structural)
                        elif identity in old:
                            signal=v48.evaluate(identity.removeprefix('V48_'),f,pair,observation,candles=histories[symbol][-720:],
                                benchmarks={s:v[-720:] for s,v in histories.items()},assessment=old_regime)
                        else:
                            signal=baseline.evaluate(identity,f,pair,observation,features.get('BTC-EUR'),features.get('ETH-EUR'),histories[symbol])
                        if identity in originals:signal.evidence['exit_policy']=policy_for(identity)
                        signals[(identity,symbol)]=signal
                        if identity in originals:signals[('V471_'+identity,symbol)]=reviewed_signal(signal,f)
                for index,run in enumerate(runs):
                    equity=run.cash+sum((p['quantity']*frame[s].open for s,p in run.positions.items() if s in frame),D(0))
                    day=(index,stamp.date());week=(index,stamp.date()-timedelta(days=stamp.weekday()))
                    day_equity.setdefault(day,equity);week_equity.setdefault(week,equity)
                    if equity-day_equity[day]<=-15 or equity-week_equity[week]<=-35 or equity<run.peak*D('.9'): run.halted=True
                    for symbol,p in list(run.positions.items()):
                        p['used']=D(0)
                        if symbol not in frame: continue
                        c=frame[symbol];bid=c.open*(1-spread/20000)
                        p['highest']=max(p['highest'],bid)
                        if p['first_target_done']:
                            update=trailing_update(previous_stop=p['stop'],highest_bid=p['highest'],basis=p['basis'],
                                quantity=p['quantity'],distance=p['distance'],atr=features[symbol].atr if symbol in features else None,
                                fee_bps=fee,slippage_bps=slip)
                            p['stop']=update.stop;p['distance']=update.distance
                        reason=None
                        if bid<=p['stop']: reason='STOP_GAP'
                        elif stamp>=p['expiry']: reason='TIME_EXIT'
                        elif run.identity not in {'BUY_AND_HOLD','MOMENTUM_30M'}:
                            reason=assess_exit(run.identity.removeprefix('V48_').removeprefix('V471_'),p['opened'],p['evidence'],histories[symbol],stamp,genuine=False)['reason']
                        if reason: sell(run,symbol,c.open,stamp,reason)
                    for symbol,f in features.items():
                        if run.identity=='CASH' or symbol in run.positions or run.cooldown.get(symbol,start)>stamp: continue
                        observation=book(symbol,frame[symbol].open,stamp)
                        pair=TradingPair(symbol,symbol.split('-')[0],'EUR',min_order_quote=D(5))
                        selected_signal=signals.get((run.identity,symbol))
                        if selected_signal:
                            run.technical+=int(selected_signal.evidence['technical_eligible']);run.feasible+=int(selected_signal.evidence['economic_eligible'])
                            run.rejected.update(selected_signal.evidence['reasons'])
                            eligible=selected_signal.evidence['entry_eligible'];evidence=selected_signal.evidence
                            plan=evidence['entry_plan']
                        else:
                            a=f.atr or frame[symbol].open*D('.01');price=frame[symbol].open
                            eligible=run.identity=='BUY_AND_HOLD' and not any(x['side']=='BUY' and x['symbol']==symbol for x in run.fills)
                            if run.identity=='MOMENTUM_30M': eligible=histories[symbol][-1].close/histories[symbol][-7].close>D('1.005')
                            plan={'stop':str(price-2*a),'targets':[str(price+2*a*i) for i in (1,2,3)]}
                            if run.identity=='BUY_AND_HOLD': plan={'stop':'0','targets':[]}
                            evidence={'holding_bars':72,'regime':'SIMPLE_BASELINE'}
                        if run.delay:
                            pending=run.pending.pop(symbol,None)
                            if pending:
                                plan,evidence=pending['plan'],pending['evidence']
                                eligible=stamp==pending['at'] and histories[symbol][-1].close>=pending['confirmation_close'] and frame[symbol].open>D(plan['stop'])
                                if not eligible:run.missed+=1
                            elif eligible:
                                run.pending[symbol]={'at':stamp+timedelta(minutes=5),'confirmation_close':histories[symbol][-1].close,'plan':plan,'evidence':evidence}
                                eligible=False
                        if run.patient:
                            pending=run.pending.get(symbol)
                            if pending and stamp>pending['expires']:
                                run.pending.pop(symbol);run.missed+=1;pending=None
                            if pending:
                                plan,evidence=pending['plan'],pending['evidence']
                                eligible=(observation.best_ask or D(0))*(1+slip/10000)<=pending['limit'] and frame[symbol].open>D(plan['stop'])
                                if eligible: run.pending.pop(symbol)
                                else: run.rejected['patient_not_executable']+=1
                            elif eligible and plan.get('alternatives'):
                                run.pending[symbol]={'plan':plan,'evidence':evidence,'limit':D(plan['alternatives'][1]['entry']),'expires':stamp+timedelta(minutes=15)}
                                eligible=False
                        if not eligible: continue
                        stop=D(plan['stop']);ask=observation.best_ask
                        assert ask is not None
                        if observation.asks[0].quantity<=0: continue
                        quote_budget=min(D(75),max(D(0),run.cash-150))
                        if stop>0: quote_budget=min(quote_budget,D(5)/((ask-stop)/ask+D('.005'))) if ask>stop else D(0)
                        if run.halted or len(run.positions)>=3 or quote_budget<5:
                            run.rejected['portfolio_risk']+=1;continue
                        if selected_signal and (run.patient or run.delay):
                            economics=raoe.costs.evaluate(pair,observation,quote_budget=quote_budget,stop=stop,
                                targets=tuple(D(v) for v in plan['targets']),atr=f.atr or D(0),
                                plausible_target=D(plan['ceiling']),holding_bars=int(evidence.get('holding_bars',72)),exit_fractions=(D('.3'),D('.4'),D('.3')))
                            if not economics.feasible: run.rejected['patient_economics_changed']+=1;continue
                        q=quantize_down(quote_budget/(ask*(1+(fee+slip)/10000)),pair.quantity_step)
                        if q<=0: run.rejected['no_entry_quantity']+=1;continue
                        admission=project_buy(pair,observation,q,quote_budget,stop,fee,slip)
                        if stop>0 and admission.planned_loss>D(5):run.rejected['actual_fill_planned_loss']+=1;continue
                        quote=admission.entry
                        if quote.fillable_quantity<=0: run.rejected['unfilled_entry']+=1;continue
                        q=quote.fillable_quantity;basis=-quote.net_cash_change
                        if basis<5: run.rejected['minimum_order']+=1;continue
                        run.cash-=basis;run.fees+=quote.fee;run.spread+=q*frame[symbol].open*spread/20000
                        run.slippage+=q*frame[symbol].open*(1+spread/20000)*slip/10000
                        parts=[quantize_down(q*D('.3'),pair.quantity_step),quantize_down(q*D('.4'),pair.quantity_step)]
                        parts.append(q-sum(parts))
                        stored_targets=[D(v) for v in plan['targets']]
                        if run.identity in [*old,*IDENTITIES]:
                            from autotrader.raoe.exits import net_exit_targets
                            stored_targets,_=net_exit_targets(stored_targets,observation,q,pair.quantity_step,fee,slip)
                        run.positions[symbol]={'quantity':q,'basis':basis,'stop':stop,'targets':stored_targets,
                            'parts':parts,'opened':stamp,'expiry':end if run.identity=='BUY_AND_HOLD' else stamp+timedelta(seconds=int((evidence.get('exit_policy') or {}).get('holding_seconds',21600 if run.identity in old else 10800))),
                            'evidence':evidence,'pnl':D(0),'highest':observation.best_bid,'distance':ask-stop,'first_target_done':False,'used':q}
                        run.fills.append({'side':'BUY','symbol':symbol,'at':stamp.isoformat(),'price':str(quote.vwap),'quantity':str(q),'fee':str(quote.fee)})
                    # Intrabar path is unknown: stop first; targets need an
                    # executable assumed bid including both fee and slippage.
                    for symbol,p in list(run.positions.items()):
                        if symbol not in frame: continue
                        c=frame[symbol]
                        if c.low*(1-spread/20000)<=p['stop']:
                            sell(run,symbol,min(c.open,p['stop']/(1-spread/20000)),stamp+timedelta(minutes=5),'STOP_FIRST_AMBIGUOUS_PATH')
                        else:
                            for target_index,target in enumerate(p['targets']):
                                if symbol not in run.positions: break
                                if p['parts'][target_index]>0 and c.high*(1-spread/20000)*(1-slip/10000)*(1-fee/10000)>=target:
                                    before=p['quantity']
                                    sell(run,symbol,target/((1-spread/20000)*(1-slip/10000)*(1-fee/10000)),stamp+timedelta(minutes=5),'TARGET',p['parts'][target_index],target)
                                    p['parts'][target_index]-=before-p['quantity']
                                    if target_index==0 and p['parts'][0]<=0:p['first_target_done']=True
                    equity=run.cash+sum((p['quantity']*(frame[s].close if s in frame else histories[s][-1].close) for s,p in run.positions.items()),D(0))
                    run.peak=max(run.peak,equity);run.drawdown=max(run.drawdown,(run.peak-equity)/run.peak);run.curves.append(equity)
            for symbol,c in frame.items():
                histories[symbol].append(c)
                if len(histories[symbol])>1152: histories[symbol].pop(0)
    # Liquidate remaining exposure at the final recorded bid, using the same
    # finite-depth assumption; any remaining unfilled exposure is disclosed.
    with at(end):
        for run in runs:
            for symbol,p in list(run.positions.items()):
                p['used']=D(0);sell(run,symbol,histories[symbol][-1].close,end,'END_OF_SEGMENT')
    results=[]
    for run in runs:
        pnl=[D(r['net_pnl']) for r in run.closed];wins=[p for p in pnl if p>0];losses=[p for p in pnl if p<0]
        marked=run.cash+sum((p['quantity']*histories[s][-1].close for s,p in run.positions.items()),D(0))
        net=marked-500
        results.append({'strategy_id':run.identity,'entry_method':'PATIENT_IOC' if run.patient else 'ONE_BAR_DELAY_CONFIRMATION' if run.delay else 'MARKET_AFTER_COMPLETED_SETUP',
            'entry_version':'4.8.0-raoe.1' if run.identity in old else '4.9.0-raoe.1' if run.identity in IDENTITIES else '4.6.0-experimental.2 + 4.7.1-quality.1' if run.identity in reviewed else '4.6.0-experimental.2' if run.identity in originals else '4.9.0-fixed-control.1',
            'exit_policy':{'version':'4.8.0-6h-original','holding_seconds':21600} if run.identity in old else policy_for(run.identity.removeprefix('V471_')),
            'time_in_market_seconds':sum(r['holding_seconds'] for r in run.closed),
            'realized_stop_risk_eur':str(sum((-D(r['net_pnl']) for r in run.closed if D(r['net_pnl'])<0),D(0))),
            'net_profit':str(net),'gross_before_fees_spread_slippage':str(net+run.fees+run.spread+run.slippage),
            'fees':str(run.fees),'spread_cost':str(run.spread),'slippage_cost':str(run.slippage),'impact_model':'one finite-volume level; no historical L2',
            'missed_fills':run.missed+len(run.pending),'closed_trades':len(pnl),'fills':len(run.fills),
            'win_rate':len(wins)/len(pnl) if pnl else None,'expectancy':str(sum(pnl)/len(pnl)) if pnl else None,
            'profit_factor':str(sum(wins)/-sum(losses)) if losses else None,'max_drawdown':str(run.drawdown),
            'median_holding_seconds':median(r['holding_seconds'] for r in run.closed) if run.closed else None,
            'open_positions_at_end':len(run.positions),'technical':run.technical,'feasible':run.feasible,
            'rejections':dict(run.rejected),'costs':costs,'start':start.isoformat(),'end_exclusive':end.isoformat(),
            'status':'TOO_INACTIVE' if not pnl else 'WORSE_THAN_CASH' if net<=0 else 'INCONCLUSIVE_POSITIVE_PROXY',
            'estimated_edge':'UNKNOWN','risk_adjusted_result':None,'risk_adjusted_limit':'Short interval and dependent intraday trades; no reliable risk-adjusted estimate',
            'closed_positions':run.closed,'executions':run.fills})
    return results
