"""Autonomous opt-in paper pipeline. Scanner and protective monitor have separate loops."""
from __future__ import annotations

import asyncio
from collections import defaultdict
import json
import logging
from time import monotonic
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import select

from autotrader.perpetuals.market import MINUTE,clock_ms
from autotrader.perpetuals.micro.execution import vwap
from autotrader.perpetuals.multi.contracts import Contract,liquidation,maintenance
from autotrader.perpetuals.multi.economics import plan
from autotrader.perpetuals.multi.ledger import MultiLedger,Refused,equity
from autotrader.perpetuals.multi.market import MultiMarket
from autotrader.perpetuals.multi.models import MultiScan
from autotrader.perpetuals.multi.policy import COHORTS,D,FEE,SLIP,encode
from autotrader.perpetuals.multi.scanner import dashboard_assets,map_universe,screen
from autotrader.perpetuals.multi.strategies import generate

log=logging.getLogger(__name__)


class MultiRuntime:
    def __init__(self, ledger: MultiLedger, market: MultiMarket, *, owner: str | None = None):
        self.ledger,self.market=ledger,market
        self.owner=owner or uuid4().hex
        self.detail_slots=asyncio.Semaphore(2)

    async def detailed(self, row: dict[str,Any]) -> dict[str,Any]:
        async with self.detail_slots:
            symbol=row['symbol'];cutoff=((clock_ms()-4000)//MINUTE)*MINUTE
            try:
                contract,bars=await asyncio.gather(self.market.contract(symbol),
                    self.market.bars(symbol,cutoff-90*MINUTE,cutoff-MINUTE))
                signals=generate(symbol,bars,cutoff,clock_ms())
                technical=[s for s in signals if not s.reasons]
                row.update(technical_passed=bool(technical),regime=signals[0].regime,
                    examined_policies=[s.policy for s in signals],current_signal=None)
                if not technical:
                    for signal in signals:await self.ledger.record_signal(self.owner,signal.payload(),';'.join(signal.reasons))
                    return {**row,'status':'REJECTED','reason':'no_technical_setup','rejection_reasons':sorted({r for s in signals for r in s.reasons})}
                _,state=await self.ledger.load()
                book,ticker=await self.market.observation(symbol)
                now=clock_ms();options=[];rejected=[]
                for signal in signals:
                    if signal.reasons:
                        rejected.append((signal,';'.join(signal.reasons)));continue
                    try:
                        plans=[plan(signal,n,equity(state,str(n),now=now),D(state['accounts'][str(n)]['cash']),contract,book,ticker,now) for n in COHORTS]
                        options.append((signal,plans))
                    except (ValueError,ArithmeticError) as error:rejected.append((signal,str(error)))
                if not options:
                    for signal,reason in rejected:await self.ledger.record_signal(self.owner,signal.payload(),reason)
                    return {**row,'status':'REJECTED','reason':'net_cost_or_risk_qualification',
                            'rejection_reasons':sorted({r for _,r in rejected})}
                # This ranks conditional target/stop scenarios, never unknown calibrated EV.
                signal,plans=max(options,key=lambda item:min(D(p['scenario_gain'])/D(p['planned_loss']) for p in item[1]))
                signal_payload=signal.payload()
                try:
                    accepted=await self.ledger.reserve(self.owner,signal_payload,plans,contract)
                    if accepted:
                        fresh_book,fresh_ticker=await self.market.observation(symbol,protective=True)
                        await self.ledger.fill(self.owner,signal.id,fresh_book,fresh_ticker)
                except (ValueError,ArithmeticError,httpx.HTTPError) as error:
                    await self.ledger.cancel(self.owner,signal.id,str(error))
                    await self.ledger.record_signal(self.owner,signal_payload,str(error))
                    return {**row,'status':'MISSED','reason':str(error),'policy':signal.policy,'direction':signal.side}
                for candidate,reason in rejected:await self.ledger.record_signal(self.owner,candidate.payload(),reason)
                for other,_ in options:
                    if other.id!=signal.id:await self.ledger.record_signal(self.owner,other.payload(),'another_strategy_has_better_net_scenario_ratio')
                return {**row,'status':'PAPER_FILLED' if accepted else 'ALREADY_CONSUMED','reason':None,
                    'policy':signal.policy,'direction':signal.side,'current_signal':signal_payload,'plans':plans,
                    'target_move_pct':signal.evidence['forecast_signed_move_fraction']*100,
                    'qualification':'EXPERIMENTAL_DETERMINISTIC','forecast_is_expected_value':False,
                    'observed_at':now,'signal_id':signal.id}
            except (ValueError,ArithmeticError,KeyError,TypeError,httpx.HTTPError,TimeoutError) as error:
                return {**row,'status':'REJECTED','reason':'detail_data_unavailable:'+str(error),
                        'technical_passed':False}

    async def scan_once(self) -> None:
        started=clock_ms()
        async with self.ledger.factory() as session:
            saved=await session.get(MultiScan,1)
            prior=json.loads(saved.payload) if saved else {}
        assets=await dashboard_assets(self.ledger.factory)
        metadata,ticker_result=await asyncio.gather(self.market.instruments(),self.market.tickers())
        mapped,unsupported=map_universe(assets,metadata)
        selected,rows,rotation=screen(mapped,ticker_result[0],ticker_result[1],prior)
        detailed=await asyncio.gather(*(self.detailed(row) for row in selected))
        by_symbol={row['symbol']:row for row in detailed}
        rows=[by_symbol.get(row['symbol'],row) for row in rows]
        for row in detailed:rotation['revisits'][row['symbol']]=clock_ms()
        technical=sum(bool(row.get('technical_passed')) for row in detailed)
        filled=sum(row['status']=='PAPER_FILLED' for row in detailed)
        _,state=await self.ledger.load()
        payload={'at':clock_ms(),'started_at':started,'status':'COMPLETE','dashboard_assets':len(assets),
            'mapped_markets':len(mapped),'markets_screened':len(rows),'details_completed':len(detailed),
            'technical_passed':technical,'matched_opportunities_filled':filled,'unsupported':unsupported,
            'rows':rows,'top_opportunities':[r for r in detailed if r.get('plans')],**rotation,
            'summary':f'{filled} matched paper entries: {len(rows)} markets screened; {technical} passed technical screening; '
                      f'{len(detailed)} detailed evaluations. Entries '+('enabled.' if state['entries_enabled'] else 'paused.'),
            'ranking_basis':'Conditional net scenario/risk; positive expected value is unproven'}
        await self.ledger.record_scan(self.owner,payload)
        await self.review_forecasts()

    async def review_forecasts(self) -> None:
        due=await self.ledger.pending_reviews(clock_ms())
        # Group requests by coin; no data from the future enters an original signal.
        groups=defaultdict(list)
        for signal in due:groups[signal['symbol']].append(signal)
        for symbol,signals in list(groups.items())[:6]:
            first=min((s['decision_at']+MINUTE-1)//MINUTE*MINUTE for s in signals)
            signals=[s for s in signals if s['decision_at']+s['hold_minutes']*MINUTE<=first+999*MINUTE]
            end=max((s['decision_at']+s['hold_minutes']*MINUTE)//MINUTE*MINUTE for s in signals)-MINUTE
            try:
                bars=await self.market.bars(symbol,first,end)
                for s in signals:
                    begin=(s['decision_at']+MINUTE-1)//MINUTE*MINUTE
                    finish=(s['decision_at']+s['hold_minutes']*MINUTE)//MINUTE*MINUTE
                    window=[bars[t] for t in range(begin,finish,MINUTE)]
                    reference=D(s['reference']);side=s['side']
                    target,stop=D(s['target']),D(s['stop']);hit_target=hit_stop=False;ambiguous=False
                    for bar in window:
                        favorable=bar.high if side==1 else bar.low;adverse=bar.low if side==1 else bar.high
                        t=side*(favorable-target)>=0;r=side*(adverse-stop)<=0
                        if t or r:
                            hit_target,hit_stop,ambiguous=t,r,t and r;break
                    observation={'hypothetical_no_fill':True,'target_touched':hit_target,'stop_touched':hit_stop,
                        'ambiguous_first_barrier':ambiguous,'conservative_first_barrier':'STOP' if hit_stop else 'TARGET' if hit_target else 'TIME',
                        'signed_horizon_move_pct':side*(window[-1].close/reference-1)*100,
                        'forecast_move_pct':D(s['evidence']['forecast_signed_move_fraction'])*100,
                        'regime_correct':None,'positive_executable_return_proven':False}
                    await self.ledger.review(self.owner,s,observation)
            except (ValueError,ArithmeticError,KeyError,httpx.HTTPError):continue

    async def monitor_once(self) -> None:
        await self.ledger.expire(self.owner)
        _,state=await self.ledger.load();errors={}
        pending={i['signal']['id']:i for i in state['intents'].values()}
        for signal_id,intent in pending.items():
            try:
                book,ticker=await self.market.observation(intent['symbol'],protective=True)
                await self.ledger.fill(self.owner,signal_id,book,ticker)
            except (ValueError,ArithmeticError,httpx.HTTPError) as error:
                await self.ledger.cancel(self.owner,signal_id,str(error))
        _,state=await self.ledger.load()
        groups=defaultdict(list)
        for key,p in state['positions'].items():groups[p['symbol']].append((key,p))
        for symbol,positions in groups.items():
            try:
                metadata_missing=False
                try:live_contract=await self.market.contract(symbol,protective=True)
                except (ValueError,httpx.HTTPError):
                    live_contract=Contract.restore(positions[0][1]['contract']);metadata_missing=True
                end=(clock_ms()//MINUTE-1)*MINUTE
                start=min(int(p['last_candle'])+MINUTE for _,p in positions)
                mark_bars=trade_bars={};history_unknown=False
                if start<=end:
                    if end-start>=1000*MINUTE:history_unknown=True
                    else:
                        try:
                            mark_bars,trade_bars=await asyncio.gather(
                                self.market.bars(symbol,start,end,mark=True,protective=True),
                                self.market.bars(symbol,start,end,protective=True))
                        except (ValueError,httpx.HTTPError):history_unknown=True
                book,ticker=await self.market.observation(symbol,protective=True)
                for key,p in positions:
                    if p['observed_exit']:continue
                    qty,entry,margin=(D(p[k]) for k in ('quantity','entry','margin'))
                    side=p['side'];frozen=Contract.restore(p['contract']);reason=None;stress=None
                    relevant=[t for t in sorted(mark_bars) if t>p['last_candle'] and t>=p['opened_at']]
                    worst=min((mark_bars[t].low for t in relevant),default=ticker.mark) if side==1 else max((mark_bars[t].high for t in relevant),default=ticker.mark)
                    worst=min(worst,ticker.mark) if side==1 else max(worst,ticker.mark)
                    collateral=margin+D(p['funding'])+side*qty*(worst-entry)
                    required=max(maintenance(frozen,qty,worst),maintenance(live_contract,qty,worst))
                    if collateral<=required:reason='LIQUIDATION'
                    elif side*(worst-D(p['stop']))<=0:reason='STOP'
                    if reason and relevant:
                        stress=min((trade_bars[t].low for t in relevant),default=book.bids[0][0]) if side==1 else max((trade_bars[t].high for t in relevant),default=book.asks[0][0])
                    tail=[*p.get('context_tail',[]),*[{'start':t,'open':trade_bars[t].open,'close':trade_bars[t].close} for t in relevant]][-3:]
                    incomplete_gap=history_unknown or (clock_ms()-p['mark_at']>15000 and not relevant)
                    if not reason:
                        exit_price=vwap(book.bids if side==1 else book.asks,qty)*(1-side*SLIP)
                        if incomplete_gap:reason='DATA_GAP_RISK_EXIT'
                        elif metadata_missing:reason='CONTRACT_METADATA_UNAVAILABLE_RISK_EXIT'
                        elif side*(exit_price-D(p['target']))>=0:reason='TARGET'
                        elif clock_ms()-p['opened_at']>=p['signal']['hold_minutes']*MINUTE:reason='TIME'
                        elif book.spread>max(D(p['initial_spread'])*3,D('.002')):reason='SPREAD_RISK'
                        elif abs(ticker.mark/book.mid-1)>D('.0025'):reason='MARK_DIVERGENCE_RISK'
                        elif ticker.next_funding_at<=clock_ms()+MINUTE:reason='FUNDING_RISK_EXIT'
                        elif live_contract.identity!=frozen.identity:reason='CONTRACT_TERMS_CHANGED'
                    if not reason and len(tail)>=2:
                        policy=p['signal']['policy'];structure=p['signal']['evidence'].get('structure')
                        if structure is not None and all(side*(D(r['close'])-D(structure))<0 for r in tail[-2:]):
                            reason='REVERSAL_INVALIDATED_EXIT' if policy.endswith('REVERSAL_V1') else 'FAILED_STRUCTURE_EXIT'
                        elif policy=='MULTI_CONTINUATION_V1' and all(side*(D(r['close'])-D(r['open']))<0 for r in tail[-2:]):
                            reason='MOMENTUM_FADED_EXIT'
                        elif policy=='MULTI_RANGE_V1' and all(side*(D(r['close'])-D(r['open']))<0 for r in tail[-2:]):
                            reason='RANGE_REVERSION_FAILED_EXIT'
                    await self.ledger.observe(self.owner,key,ticker,candle_at=end if not history_unknown and start<=end else None,context_tail=tail)
                    if reason:await self.ledger.exit_intent(self.owner,key,reason,stress_price=stress)
            except (ValueError,ArithmeticError,KeyError,httpx.HTTPError) as error:
                errors[symbol]=type(error).__name__+':'+str(error)
        _,state=await self.ledger.load()
        # Exit observations are durably captured even when funding history is
        # delayed; settlement waits without inventing zero funding or releasing cash.
        for key,p in state['positions'].items():
            try:
                if p['exit_intent'] and not p['observed_exit']:
                    await self.ledger.refresh_exit_intent(self.owner,key)
                    book,ticker=await self.market.observation(p['symbol'],protective=True)
                    await self.ledger.quote_exit(self.owner,key,book,ticker)
                _,current=await self.ledger.load();p=current['positions'].get(key)
                if not p:continue
                until=p['observed_exit']['at'] if p['observed_exit'] else clock_ms()
                funding={}
                if until>=p['next_funding_at']:
                    funding=await self.market.funding(p['symbol'],int(p['funding_cursor'])+1,until)
                await self.ledger.settle_funding(self.owner,key,funding,until)
                if p['observed_exit']:await self.ledger.settle_exit(self.owner,key)
            except (ValueError,ArithmeticError,KeyError,httpx.HTTPError) as error:
                errors[key]=type(error).__name__+':'+str(error)
        await self.ledger.monitor_status(self.owner,errors)

    async def run(self, stopping: asyncio.Event) -> None:
        if not await self.ledger.provisioned():
            log.error('multi_perpetuals_schema_not_provisioned; existing BTC worker unaffected');return
        while not stopping.is_set() and not await self.ledger.acquire(self.owner):
            try:await asyncio.wait_for(stopping.wait(),timeout=5)
            except TimeoutError:pass
        lost_ownership=asyncio.Event()
        async def loop(operation,interval):
            while not stopping.is_set() and not lost_ownership.is_set():
                began=monotonic()
                try:await operation()
                except Exception as error:
                    log.exception('isolated_multi_paper_cycle_failed')
                    if isinstance(error,Refused) and ('lease' in str(error) or 'ownership' in str(error)):
                        lost_ownership.set();return
                    if operation==self.scan_once:
                        async with self.ledger.factory() as session:
                            previous=await session.get(MultiScan,1)
                            prior=json.loads(previous.payload) if previous else {}
                        await self.ledger.record_scan(self.owner,{'at':clock_ms(),'status':'ERROR','rows':[],
                            'top_opportunities':[],'error':type(error).__name__,
                            'samples':prior.get('samples',{}),'revisits':prior.get('revisits',{}),
                            'summary':'Scan incomplete; no current qualification counts are available.'})
                try:await asyncio.wait_for(stopping.wait(),timeout=max(.1,interval-(monotonic()-began)))
                except TimeoutError:pass
        async def renew():
            if not await self.ledger.acquire(self.owner):raise Refused('multi_worker_ownership_lost')
        tasks=[asyncio.create_task(loop(renew,5)),asyncio.create_task(loop(self.monitor_once,2)),
               asyncio.create_task(loop(self.scan_once,60))]
        watchers=[asyncio.create_task(stopping.wait()),asyncio.create_task(lost_ownership.wait())]
        try:await asyncio.wait(watchers,return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in [*tasks,*watchers]:task.cancel()
            await asyncio.gather(*tasks,*watchers,return_exceptions=True)
