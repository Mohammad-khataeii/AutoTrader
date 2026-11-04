"""Atomic, generation-safe virtual accounting and durable, idempotent order lifecycle."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from autotrader.perpetuals.market import clock_ms
from autotrader.perpetuals.micro.execution import estimate
from autotrader.perpetuals.micro.types import Book, Intent, Ticker
from autotrader.perpetuals.multi.contracts import Contract, liquidation, maintenance
from autotrader.perpetuals.multi.evidence import decision, decision_counts, realized_distribution
from autotrader.perpetuals.multi.models import MultiEvent, MultiScan, MultiSignal, MultiState
from autotrader.perpetuals.multi.policy import (
    COHORTS,D,EXPERIMENT,FEE,FINGERPRINT,INITIAL,INTENT_TTL,MARK_MAX_AGE,MAX_DRAWDOWN,
    MAX_POSITIONS,MAX_TOTAL_MARGIN,MAX_TOTAL_NOTIONAL,MAX_ASSET_NOTIONAL,
    MAX_SAME_DIRECTION_EQUITY,MAX_TRADE_MARGIN,RISK,SLIP,POLICIES,encode,digest,initial_state,
)


class Refused(ValueError):
    pass


def event(key: str, kind: str, at: int, **payload: Any) -> dict[str,Any]:
    return {'event_key':key,'kind':kind,'at':at,**payload}


def equity(state: dict[str,Any], cohort: str, *, now: int | None = None):
    total=D(state['accounts'][cohort]['cash'])
    total+=sum((D(i['reserved']) for i in state['intents'].values() if str(i['leverage'])==cohort),D(0))
    for p in state['positions'].values():
        if str(p['leverage'])!=cohort:continue
        if now is not None and (p.get('observed_exit') is None and not 0<=now-int(p['mark_at'])<=MARK_MAX_AGE):
            raise Refused('open_position_valuation_stale')
        mark=D(p['mark']);exit_proxy=D(p['observed_exit']['price']) if p.get('observed_exit') else mark*(1-p['side']*SLIP)
        gross=p['side']*D(p['quantity'])*(exit_proxy-D(p['entry']))
        total+=max(D(0),D(p['margin'])+D(p['funding'])+gross-exit_proxy*D(p['quantity'])*FEE)
    return total


def reconcile(state: dict[str,Any]) -> None:
    if state['experiment']!=EXPERIMENT or state['policy_hash']!=FINGERPRINT or set(state['accounts'])!={str(n) for n in COHORTS}:
        raise Refused('multi_experiment_identity_changed')
    for key,a in state['accounts'].items():
        cash=D(a['cash']);locked=D(0);assets=[]
        for p in state['positions'].values():
            if str(p['leverage'])==key:
                if D(p['quantity'])<=0 or D(p['margin'])<=0 or p['side'] not in (-1,1):raise Refused('invalid_position')
                if (p['signal']['policy'] not in POLICIES or p['signal']['symbol']!=p['symbol']
                        or Contract.restore(p['contract']).identity!=p['contract_hash']):
                    raise Refused('position_contract_or_policy_changed')
                locked+=D(p['margin'])+D(p['entry_fee']);assets.append(p['symbol'])
        for i in state['intents'].values():
            if str(i['leverage'])==key:
                if D(i['reserved'])<=0:raise Refused('invalid_reservation')
                locked+=D(i['reserved']);assets.append(i['symbol'])
        if (not cash.is_finite() or cash<0 or abs(cash+locked-INITIAL-D(a['realized']))>D('1e-12')
                or len(assets)!=len(set(assets))):raise Refused('multi_collateral_reconciliation_failed')


def risk_check(state: dict[str,Any], proposal: dict[str,Any], symbol: str, side: int, now: int) -> None:
    cohort=str(proposal['leverage']);a=state['accounts'][cohort];eq=equity(state,cohort,now=now)
    if not state['entries_enabled'] or a['halted']:raise Refused('entries_paused_or_risk_halted')
    if eq<=0 or 1-eq/D(a['peak'])>=MAX_DRAWDOWN:raise Refused('portfolio_drawdown_limit')
    positions=[p for p in state['positions'].values() if str(p['leverage'])==cohort]
    intents=[i for i in state['intents'].values() if str(i['leverage'])==cohort]
    if len(positions)+len(intents)>=MAX_POSITIONS:raise Refused('concurrent_position_cap')
    if any(p['symbol']==symbol for p in [*positions,*intents]):raise Refused('existing_asset_exposure')
    margin=sum((D(p.get('margin',p.get('margin_estimate','0'))) for p in [*positions,*intents]),D(0))
    notional=sum((D(p.get('notional',D(p['quantity'])*D(p.get('mark',p.get('entry_estimate','0'))))) for p in [*positions,*intents]),D(0))
    correlated=sum((D(p.get('notional',D(p['quantity'])*D(p.get('mark',p.get('entry_estimate','0'))))) for p in [*positions,*intents] if p['side']==side),D(0))
    planned=sum((D(p['planned_loss']) for p in [*positions,*intents]),D(0))
    n,m,loss=(D(proposal[k]) for k in ('notional','margin_estimate','planned_loss'))
    if (n>MAX_ASSET_NOTIONAL or notional+n>min(eq*2,MAX_TOTAL_NOTIONAL)
            or margin+m>eq*MAX_TOTAL_MARGIN or m>eq*MAX_TRADE_MARGIN
            or correlated+n>eq*MAX_SAME_DIRECTION_EQUITY
            or loss>eq*RISK or planned+loss>eq*RISK*MAX_POSITIONS
            or D(proposal['reserved'])>D(a['cash'])):raise Refused('aggregate_exposure_margin_or_risk_cap')


class MultiLedger:
    def __init__(self, factory: async_sessionmaker[AsyncSession]):self.factory=factory

    async def provisioned(self) -> bool:
        async with self.factory() as session:
            c=await session.connection()
            return await c.run_sync(lambda connection:inspect(connection).has_table('paper_multi_state'))

    async def load(self) -> tuple[int,dict[str,Any]]:
        async with self.factory() as session:
            row=await session.get(MultiState,1)
            if row is None:raise Refused('multi_schema_not_provisioned')
            state=json.loads(row.payload) if row.payload else initial_state();reconcile(state)
            return row.generation,state

    async def atomic(self, owner: str | None, action: Callable, *, signal: dict[str,Any] | None = None,
                     event_key: str | None = None):
        for _ in range(8):
            async with self.factory() as session,session.begin():
                if session.bind.dialect.name=='sqlite':
                    await session.execute(text('BEGIN IMMEDIATE'))
                row=await session.scalar(select(MultiState).where(MultiState.id==1).with_for_update())
                if row is None:raise Refused('multi_schema_not_provisioned')
                state=json.loads(row.payload) if row.payload else initial_state()
                reconcile(state)
                if row.payload is not None:
                    cash_rows=(await session.execute(select(MultiEvent.cohort,func.sum(MultiEvent.cash_delta))
                        .where(MultiEvent.cohort.is_not(None)).group_by(MultiEvent.cohort))).all()
                    posted={k:D(str(v)) for k,v in cash_rows}
                    if any(abs(posted.get(k,D(0))-D(a['cash']))>D('1e-10') for k,a in state['accounts'].items()):
                        raise Refused('append_only_cash_journal_mismatch')
                now=clock_ms();lease=state.get('lease') or {}
                if owner is not None and (lease.get('owner')!=owner or lease.get('expires_at',0)<=now):
                    raise Refused('multi_worker_lease_expired')
                if signal is not None and await session.get(MultiSignal,signal['id']):return False
                if event_key is not None and await session.scalar(select(MultiEvent.id).where(MultiEvent.event_key==event_key)):
                    return False
                events=[]
                if row.payload is None:
                    events=[event('initial:'+str(n),'INITIAL_FUNDING',now,cohort=str(n),cash_delta=INITIAL) for n in COHORTS]
                outcome,posted=action(state,now);events.extend(posted);reconcile(state)
                result=await session.execute(update(MultiState).where(MultiState.id==1,MultiState.generation==row.generation)
                    .values(generation=row.generation+1,payload=encode(state)))
                if result.rowcount!=1:continue
                if signal is not None:session.add(MultiSignal(id=signal['id'],cutoff=signal['cutoff'],
                    due_at=signal['cutoff']+(signal['hold_minutes']+1)*60_000,payload=encode(signal)))
                session.add_all(MultiEvent(event_key=e['event_key'],kind=e['kind'],cohort=e.get('cohort'),
                    cash_delta=D(e.get('cash_delta','0')),payload=encode(e)) for e in events)
                # Commit precedes the return, and therefore any subsequent quote request.
                return outcome
        raise Refused('multi_generation_contention')

    async def acquire(self, owner: str) -> bool:
        def action(s,now):
            lease=s.get('lease') or {}
            if lease.get('owner') not in (None,owner) and lease.get('expires_at',0)>now:return False,[]
            s['lease']={'owner':owner,'expires_at':now+20_000};return True,[]
        return await self.atomic(None,action)

    async def control(self, enabled: bool) -> bool:
        control_key='control:'+uuid4().hex
        def action(s,now):
            lease=s.get('lease') or {}
            if enabled and lease.get('expires_at',0)<=now:raise Refused('multi_worker_not_current')
            s['entries_enabled']=enabled
            events=[event(control_key,'RESUME_ENTRIES' if enabled else 'PAUSE_ENTRIES',now)]
            if not enabled:
                for key,i in list(s['intents'].items()):
                    a=s['accounts'][str(i['leverage'])];a['cash']=D(a['cash'])+D(i['reserved']);del s['intents'][key]
                    events.append(event('expire:'+key,'ENTRY_CANCELLED',now,cohort=str(i['leverage']),cash_delta=D(i['reserved']),intent=key,reason='entries_paused'))
            return True,events
        return await self.atomic(None,action)

    async def reserve(self, owner: str, signal: dict[str,Any], plans: list[dict[str,Any]], contract: Contract) -> bool:
        def action(s,now):
            if signal['policy'] not in POLICIES or signal.get('evidence',{}).get('research_only'):
                raise Refused('research_policy_has_no_entry_authority')
            if len(plans)!=len(COHORTS) or set(p['leverage'] for p in plans)!=set(COHORTS):raise Refused('matched_cohorts_required')
            if now-signal['decision_at']>INTENT_TTL:raise Refused('signal_expired_before_reservation')
            failures=[]
            for proposal in plans:
                try: risk_check(s,proposal,signal['symbol'],signal['side'],now)
                except Refused as error: failures.append(f"cohort_{proposal['leverage']}:{error}")
            if failures:raise Refused(';'.join(failures))
            events=[]
            for p in plans:
                key=signal['id']+':'+str(p['leverage']);cohort=str(p['leverage'])
                s['accounts'][cohort]['cash']=D(s['accounts'][cohort]['cash'])-D(p['reserved'])
                s['intents'][key]={**p,'id':key,'signal':signal,'symbol':signal['symbol'],'side':signal['side'],
                    'created_at':now,'expires_at':now+INTENT_TTL,'contract':contract.payload(),
                    'contract_hash':contract.identity}
                events.append(event('reserve:'+key,'ENTRY_RESERVED',now,cohort=cohort,cash_delta=-D(p['reserved']),intent=key,signal_id=signal['id']))
            signal['decision_context']=signal.get('decision_context') or signal.get('evidence',{}).get('decision_context',{})
            signal['decision']=decision(signal,s,'matched_intents_reserved',admitted=True)
            return True,events
        return await self.atomic(owner,action,signal=signal)

    async def expire(self, owner: str) -> int:
        def action(s,now):
            events=[]
            for key,i in list(s['intents'].items()):
                if now>i['expires_at'] or not s['entries_enabled']:
                    cohort=str(i['leverage']);amount=D(i['reserved'])
                    s['accounts'][cohort]['cash']=D(s['accounts'][cohort]['cash'])+amount;del s['intents'][key]
                    events.append(event('expire:'+key,'ENTRY_EXPIRED',now,cohort=cohort,cash_delta=amount,intent=key,signal_id=i['signal']['id']))
            return len(events),events
        return await self.atomic(owner,action)

    async def fill(self, owner: str, signal_id: str, book: Book, ticker: Ticker) -> bool:
        def action(s,now):
            intents=[i for i in s['intents'].values() if i['signal']['id']==signal_id]
            if not intents:return False,[]
            if not s['entries_enabled']:raise Refused('entries_paused')
            entries=[]
            for i in intents:
                c=Contract.restore(i['contract']);side=i['side'];qty=D(i['quantity'])
                if not i['created_at']<=ticker.exchange_at<=ticker.received_at<=now or now-ticker.exchange_at>3000:
                    raise Refused('fill_mark_stale_or_predates_reservation')
                q=estimate(Intent(i['id'],i['signal']['policy'],side,qty,i['created_at'],i['expires_at']),book,now)
                c.validate_size(qty,q.entry,i['leverage'])
                if abs(q.entry/D(i['entry_estimate'])-1)>D('.001'):raise Refused('entry_reprice_limit')
                notional=qty*q.entry;margin=notional/i['leverage'];fee=notional*FEE
                stop,target=D(i['stop']),D(i['target']);exit_factor=q.exit_now/q.mid
                latency=D(now-i['signal']['decision_at'])/60_000*D(i['signal']['evidence']['atr_fraction'])
                loss=max(D(0),-qty*(side*(stop*exit_factor-q.entry)-FEE*(q.entry+stop*exit_factor)-q.mid*latency))
                gain=qty*(side*(target*exit_factor-q.entry)-FEE*(q.entry+target*exit_factor)-q.mid*latency)
                if (loss>D(i['initial_account_equity'])*RISK or loss<=0 or gain<=0 or gain/loss<D('1.1')
                        or side*(q.entry-stop)<=0 or side*(target-q.entry)<=0
                        or not D('.005')<=side*(target/q.mid-1)<=D('.01')
                        or margin+fee>D(i['reserved']) or abs(ticker.mark/q.mid-1)>D('.0025')
                        or ticker.next_funding_at<=now+i['signal']['hold_minutes']*60_000):
                    raise Refused('fill_economic_or_funding_requalification_failed')
                p={**i,'entry':q.entry,'quantity':qty,'margin':margin,'entry_fee':fee,'funding':'0',
                    'opened_at':q.quoted_at,'mark':ticker.mark,'mark_at':ticker.received_at,'notional':notional,
                    'planned_loss':loss,'next_funding_at':ticker.next_funding_at,'funding_cursor':q.quoted_at,
                    'last_candle':q.quoted_at//60_000*60_000,'entry_proxy':q.__dict__,
                    'entry_book':book.__dict__,'mae':'0','mfe':'0','exit_intent':None,'observed_exit':None}
                liq=liquidation(c,p)
                if side*(stop-liq)/ticker.mark<max(D(i['signal']['evidence']['atr_fraction'])*2,book.spread*4):
                    raise Refused('fill_liquidation_buffer')
                entries.append((i,p))
            check=deepcopy(s)
            for i,p in entries:
                cohort=str(i['leverage']);key=i['id']
                del check['intents'][key]
                check['accounts'][cohort]['cash']=D(check['accounts'][cohort]['cash'])+D(i['reserved'])
                p['initial_account_equity']=equity(check,cohort,now=now)
                current={**p,'margin_estimate':p['margin'],'reserved':D(p['margin'])+D(p['entry_fee'])}
                risk_check(check,current,p['symbol'],p['side'],now)
                check['positions'][key]=p
                check['accounts'][cohort]['cash']=D(check['accounts'][cohort]['cash'])-current['reserved']
            events=[]
            for i,p in entries:
                key=i['id'];cohort=str(i['leverage']);a=s['accounts'][cohort]
                refund=D(i['reserved'])-D(p['margin'])-D(p['entry_fee'])
                a['cash']=D(a['cash'])+refund;a['fees']=D(a['fees'])+D(p['entry_fee'])
                a['slippage']=D(a['slippage'])+abs(D(p['entry'])-D(p['entry'])/(1+p['side']*SLIP))*D(p['quantity'])
                del s['intents'][key];s['positions'][key]=p
                events.append(event('open:'+key,'ENTRY_FILLED',now,cohort=cohort,cash_delta=refund,position=p,
                    classification='LIVE_OBSERVED_POST_INTENT_DEPTH_PROXY',slippage=SLIP,signal_id=signal_id))
            return True,events
        return await self.atomic(owner,action)

    async def observe(self, owner: str, position_id: str, ticker: Ticker, *, candle_at: int | None = None, context_tail: list[dict[str,Any]] | None = None) -> bool:
        def action(s,now):
            p=s['positions'].get(position_id)
            if not p or p['observed_exit']:return False,[]
            if not 0<=now-ticker.exchange_at<=MARK_MAX_AGE:raise Refused('stale_monitor_mark')
            if ticker.received_at<p['mark_at']:return False,[]
            p['mark'],p['mark_at']=ticker.mark,ticker.received_at;p['notional']=D(p['quantity'])*ticker.mark
            signed=p['side']*(ticker.mark/D(p['entry'])-1)
            p['mae']=max(D(p['mae']),-signed);p['mfe']=max(D(p['mfe']),signed)
            if candle_at is not None:p['last_candle']=candle_at
            if context_tail is not None:p['context_tail']=context_tail[-3:]
            a=s['accounts'][str(p['leverage'])];eq=equity(s,str(p['leverage']))
            a['peak']=max(D(a['peak']),eq);a['drawdown']=max(D(a['drawdown']),1-eq/D(a['peak']))
            if D(a['drawdown'])>=MAX_DRAWDOWN:a['halted']=True
            return True,[]
        return await self.atomic(owner,action)

    async def exit_intent(self, owner: str, position_id: str, reason: str, *, stress_price=None) -> bool:
        def action(s,now):
            p=s['positions'].get(position_id)
            if not p or p['exit_intent']:return False,[]
            p['exit_intent']={'at':now,'expires_at':now+INTENT_TTL,'reason':reason,'stress_price':stress_price}
            return True,[event('exit-intent:'+position_id,'EXIT_RESERVED',now,position_id=position_id,reason=reason)]
        return await self.atomic(owner,action)

    async def refresh_exit_intent(self, owner: str, position_id: str) -> None:
        def action(s,now):
            p=s['positions'].get(position_id)
            if p and p['exit_intent'] and not p['observed_exit'] and p['exit_intent']['expires_at']<now:
                p['exit_intent']['at']=now;p['exit_intent']['expires_at']=now+INTENT_TTL
            return None,[]
        await self.atomic(owner,action)

    async def quote_exit(self, owner: str, position_id: str, book: Book, ticker: Ticker) -> bool:
        def action(s,now):
            p=s['positions'].get(position_id)
            if not p or p['observed_exit']:return False,[]
            i=p['exit_intent']
            if not i:raise Refused('durable_exit_intent_required')
            q=estimate(Intent('exit:'+position_id,p['signal']['policy'],-p['side'],D(p['quantity']),i['at'],i['expires_at']),book,now)
            price=q.entry;classification='LIVE_OBSERVED_POST_INTENT_DEPTH_PROXY'
            if i['stress_price'] is not None:
                stress=D(i['stress_price'])*(1-p['side']*SLIP)
                price=min(price,stress) if p['side']==1 else max(price,stress)
                classification='GAP_OHLC_ADVERSE_STRESS_PROXY_NOT_HISTORICAL_EXECUTION'
            if not i['at']<=ticker.exchange_at<=now or now-ticker.exchange_at>3000:raise Refused('exit_mark_stale')
            p['mark'],p['mark_at']=ticker.mark,ticker.received_at
            p['observed_exit']={'price':price,'at':q.quoted_at,'reason':i['reason'],
                'classification':('LIVE_RECONNECT_DEPTH_PROXY_PATH_UNKNOWN' if i['reason']=='DATA_GAP_RISK_EXIT' and i['stress_price'] is None else classification),'book':book.__dict__,'quote':q.__dict__,'mark':ticker.mark}
            return True,[event('exit-observed:'+position_id,'EXIT_PRICE_OBSERVED',now,position_id=position_id,observation=p['observed_exit'])]
        return await self.atomic(owner,action)

    async def settle_funding(self, owner: str, position_id: str, events: dict[int,tuple[Any,Any]], checked_through: int) -> bool:
        def action(s,now):
            p=s['positions'].get(position_id)
            if not p:return False,[]
            end=min(checked_through,p['observed_exit']['at'] if p['observed_exit'] else checked_through)
            interval=Contract.restore(p['contract']).funding_minutes*60_000
            expected=set(range(int(p['next_funding_at']),end+1,interval)) if end>=p['next_funding_at'] else set()
            supplied={t for t in events if D(p['funding_cursor'])<t<=end}
            if supplied!=expected:raise Refused('funding_events_missing_or_schedule_changed')
            posted=[]
            for t in sorted(supplied):
                rate,mark=(D(str(v)) for v in events[t]);amount=-p['side']*D(p['quantity'])*mark*rate
                p['funding']=D(p['funding'])+amount
                a=s['accounts'][str(p['leverage'])];a['funding']=D(a['funding'])+amount
                posted.append(event('funding:'+position_id+':'+str(t),'FUNDING',t,cohort=str(p['leverage']),
                    position_id=position_id,amount=amount,rate=rate,mark=mark,cash_delta='0'))
            if expected:p['next_funding_at']=max(expected)+interval
            p['funding_cursor']=max(int(p['funding_cursor']),end)
            return True,posted
        return await self.atomic(owner,action)

    async def settle_exit(self, owner: str, position_id: str) -> bool:
        def action(s,now):
            p=s['positions'].get(position_id)
            if not p or not p['observed_exit']:return False,[]
            x=p['observed_exit'];end=x['at']
            if p['funding_cursor']<end:raise Refused('exit_funding_unreconciled')
            qty,entry,margin,price=D(p['quantity']),D(p['entry']),D(p['margin']),D(x['price'])
            gross=p['side']*qty*(price-entry);fee=qty*price*FEE
            raw=margin+D(p['funding'])+gross-fee
            returned=D(0) if x['reason']=='LIQUIDATION' else max(D(0),raw)
            net=returned-margin-D(p['entry_fee']);cohort=str(p['leverage']);a=s['accounts'][cohort]
            a['cash']=D(a['cash'])+returned;a['realized']=D(a['realized'])+net;a['closed']+=1
            a['fees']=D(a['fees'])+fee
            a['slippage']=D(a['slippage'])+abs(D(x['quote']['entry'])-D(x['quote']['entry'])/(1-p['side']*SLIP))*qty
            a['liquidations']+=int(x['reason']=='LIQUIDATION')
            del s['positions'][position_id]
            eq=equity(s,cohort);a['peak']=max(D(a['peak']),eq)
            a['drawdown']=max(D(a['drawdown']),1-eq/D(a['peak']))
            if D(a['drawdown'])>=MAX_DRAWDOWN:a['halted']=True
            return True,[event('close:'+position_id,'EXIT_SETTLED',now,cohort=cohort,position_id=position_id,
                cash_delta=returned,net=net,gross=gross,exit_fee=fee,entry_fee=p['entry_fee'],funding=p['funding'],
                settlement_adjustment=returned-raw,reason=x['reason'],position=p,
                underlying_move_pct=(price/entry-1)*100,margin_roi_pct=net/margin*100,
                account_roi_pct=net/D(p['initial_account_equity'])*100,
                planned_risk_exceeded=-net>D(p['planned_loss']),mae=p['mae'],mfe=p['mfe'])]
        return await self.atomic(owner,action)

    async def record_signal(self, owner: str, signal: dict[str,Any], reason: str) -> bool:
        def action(s,now):
            signal['decision_context']=signal.get('decision_context') or signal.get('evidence',{}).get('decision_context',{})
            signal['decision']=decision(signal,s,reason)
            kind='RESEARCH_OBSERVED' if signal.get('evidence',{}).get('research_only') else 'SIGNAL_REJECTED'
            return True,[event('rejected:'+signal['id'],kind,now,signal=signal,reason=reason)]
        return await self.atomic(owner,action,signal=signal)

    async def record_scan(self, owner: str, payload: dict[str,Any]) -> None:
        async with self.factory() as session,session.begin():
            current=await session.scalar(select(MultiState).where(MultiState.id==1).with_for_update())
            state=json.loads(current.payload) if current and current.payload else {}
            lease=state.get('lease') or {}
            if lease.get('owner')!=owner or lease.get('expires_at',0)<=clock_ms():raise Refused('scan_lease_expired')
            row=await session.get(MultiScan,1)
            if row:row.payload=encode(payload)
            else:session.add(MultiScan(id=1,payload=encode(payload)))

    async def monitor_status(self, owner: str, errors: dict[str,str]) -> None:
        def action(s,now):
            s['monitor']={'at':now,'errors':errors}
            return None,[]
        await self.atomic(owner,action)

    async def review(self, owner: str, signal: dict[str,Any], observed: dict[str,Any]) -> bool:
        key='review:'+signal['id']
        # Link committed financial facts without folding them into a no-fill
        # candle proxy. Later settlements remain separate append-only events.
        keys=[prefix+signal['id']+':'+str(n) for prefix in ('open:','close:') for n in COHORTS]
        async with self.factory() as session:
            facts=(await session.execute(select(MultiEvent.payload).where(MultiEvent.event_key.in_(keys)))).scalars().all()
        actual=[json.loads(row) for row in facts]
        observed={**observed,'actual_simulated_outcomes': {
            'facts_observed_at':clock_ms(),
            'fill_event_keys':[e['event_key'] for e in actual if e['kind']=='ENTRY_FILLED'],
            'settlements':[{'event_key':e['event_key'],'cohort':e['cohort'],'net':e['net'],'reason':e['reason']}
                           for e in actual if e['kind']=='EXIT_SETTLED'],
            'status':'SIMULATED_FILL_RECORDED' if any(e['kind']=='ENTRY_FILLED' for e in actual) else 'NO_FILL_RECORDED_AT_FACT_CUTOFF',
            'scope':'Independent ledger facts; candle proxy is never substituted for these outcomes'}}
        def action(s,now):
            return True,[event(key,'HYPOTHETICAL_FORECAST_REVIEW',now,signal_id=signal['id'],
                symbol=signal['symbol'],policy=signal['policy'],
                decision_group=signal.get('decision',{}).get('group','LEGACY_CONTEXT_UNKNOWN'),observed=observed)]
        return await self.atomic(owner,action,event_key=key)

    async def pending_reviews(self, now: int, limit: int = 60) -> list[dict[str,Any]]:
        # Signals remain immutable; completed reviews are append-only journal entries.
        async with self.factory() as session:
            rows=(await session.execute(select(MultiSignal.payload).outerjoin(MultiEvent,
                MultiEvent.event_key=='review:'+MultiSignal.id).where(MultiEvent.id.is_(None),MultiSignal.due_at<=now)
                .order_by(MultiSignal.cutoff,MultiSignal.id).limit(limit))).scalars().all()
        due=[json.loads(row) for row in rows]
        return sorted([s for s in due if s['cutoff']+s['hold_minutes']*60_000+60_000<=now],
                      key=lambda s:s['cutoff'])[:limit]

    async def cancel(self, owner: str, signal_id: str, reason: str) -> None:
        def action(s,now):
            events=[]
            for key,i in list(s['intents'].items()):
                if i['signal']['id']!=signal_id:continue
                cohort=str(i['leverage']);amount=D(i['reserved'])
                s['accounts'][cohort]['cash']=D(s['accounts'][cohort]['cash'])+amount;del s['intents'][key]
                events.append(event('cancel:'+key,'ENTRY_MISSED',now,cohort=cohort,cash_delta=amount,
                    signal_id=signal_id,intent=key,reason=reason))
            return None,events
        await self.atomic(owner,action)

    async def snapshot(self) -> dict[str,Any]:
        if not await self.provisioned():
            return {'status':'NOT_PROVISIONED','experiment':EXPERIMENT,'accounts':[],'positions':[],
                    'events':[],'learning':[],'scan':None,'entries_enabled':False}
        async with self.factory() as session,session.begin():
            if session.bind.dialect.name=='postgresql':
                await session.connection(execution_options={'isolation_level':'REPEATABLE READ'})
            row=await session.get(MultiState,1)
            s=json.loads(row.payload) if row and row.payload else None
            scan=await session.get(MultiScan,1)
            rows=(await session.execute(select(MultiEvent.payload).order_by(MultiEvent.id.desc()).limit(100))).scalars().all()
            closed=(await session.execute(select(MultiEvent.payload).where(MultiEvent.kind=='EXIT_SETTLED')
                .order_by(MultiEvent.id.desc()).limit(500))).scalars().all()
        if s is None:
            return {'status':'NOT_INITIALIZED','experiment':EXPERIMENT,'accounts':[],'positions':[],
                    'events':[],'learning':[],'scan':None,'entries_enabled':False}
        reconcile(s);now=clock_ms();accounts=[];positions=[]
        for cohort,a in s['accounts'].items():
            eq=equity(s,cohort)
            used=sum((D(p['margin']) for p in s['positions'].values() if str(p['leverage'])==cohort),D(0))
            unrealized=eq-INITIAL-D(a['realized'])
            accounts.append({**a,'leverage':int(cohort),'equity':eq,
                'estimated_net_unrealized':unrealized,'open_margin_roi_pct':unrealized/used*100 if used else None,
                'margin_utilization_pct':used/eq*100 if eq>0 else None,
                'free_collateral':a['cash'],'account_roi_pct':(eq/INITIAL-1)*100,
                'margin_used':used,
                'reserved':sum((D(i['reserved']) for i in s['intents'].values() if str(i['leverage'])==cohort),D(0))})
        for key,p in s['positions'].items():
            mark,qty,entry=(D(p[k]) for k in ('mark','quantity','entry'))
            gross=p['side']*qty*(mark-entry)
            exit_proxy=D(p['observed_exit']['price']) if p.get('observed_exit') else mark*(1-p['side']*SLIP)
            closing_fee=exit_proxy*qty*FEE
            net=p['side']*qty*(exit_proxy-entry)+D(p['funding'])-D(p['entry_fee'])-closing_fee
            try:liq=liquidation(Contract.restore(p['contract']),p)
            except ValueError:liq=None
            positions.append({**p,'id':key,'gross_unrealized':gross,'estimated_net_unrealized':net,
                'margin_roi_pct':net/D(p['margin'])*100,'position_account_roi_pct':net/D(p['initial_account_equity'])*100,
                'underlying_move_pct':(mark/entry-1)*100,'liquidation_mark':liq,
                'liquidation_distance_pct':p['side']*(mark-liq)/mark*100 if liq is not None else None,
                'age_minutes':D(now-p['opened_at'])/60_000,'valuation_fresh':0<=now-p['mark_at']<=MARK_MAX_AGE,
                'status':'FUNDING_PENDING_SETTLEMENT' if p['observed_exit'] else 'EXIT_PENDING' if p['exit_intent'] else 'OPEN'})
        events=[json.loads(r) for r in rows]
        performance={}
        for raw in closed:
            item=json.loads(raw);p=item['position'];key=(p['symbol'],p['signal']['policy'],p['leverage'])
            stats=performance.setdefault(key,{'symbol':key[0],'policy':key[1],'leverage':key[2],
                'closed':0,'wins':0,'losses':0,'net':D(0),'fees':D(0),'funding':D(0),
                'stop_outs':0,'target_exits':0,'time_exits':0,'regime_accuracy':None})
            net=D(item['net']);stats['closed']+=1;stats['wins']+=int(net>0);stats['losses']+=int(net<0)
            stats['net']+=net;stats['fees']+=D(item['entry_fee'])+D(item['exit_fee']);stats['funding']+=D(item['funding'])
            stats['stop_outs']+=int(item['reason']=='STOP');stats['target_exits']+=int(item['reason']=='TARGET');stats['time_exits']+=int(item['reason']=='TIME')
        return {'status':'ACTIVE' if (s.get('lease') or {}).get('expires_at',0)>now else 'WORKER_STALE',
            'experiment':EXPERIMENT,'entries_enabled':s['entries_enabled'],'accounts':accounts,'positions':positions,
            'intents':list(s['intents'].values()),'events':events,
            'performance':list(performance.values()),'performance_scope':'Last 500 recorded settlements, grouped by symbol/policy/cohort; cohorts are not independent samples',
            'realized_distributions':realized_distribution([json.loads(r) for r in closed]),
            'decision_counts':decision_counts(events),
            'learning':[e for e in events if e['kind'] in ('EXIT_SETTLED','HYPOTHETICAL_FORECAST_REVIEW','SIGNAL_REJECTED','RESEARCH_OBSERVED','ENTRY_MISSED','ENTRY_EXPIRED')],
            'scan':{k:v for k,v in json.loads(scan.payload).items() if k not in ('samples','revisits','feature_cache')} if scan else None,
            'scan_fresh':bool(scan and json.loads(scan.payload).get('status')=='COMPLETE'
                and 0<=now-json.loads(scan.payload)['at']<=120_000),
            'monitor':s.get('monitor'),
            'qualification':'EXPERIMENTAL_DETERMINISTIC_NOT_PROVEN_POSITIVE_EV','reconciliation':[]}
