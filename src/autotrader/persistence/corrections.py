"""Explicit, reviewed projection repair; immutable economics are never rewritten.

This is deliberately unable to guess legacy attribution or create cash funding.
An operator first reviews a fingerprinted plan, then explicitly applies that
exact plan while entries are paused. Any intervening financial change rejects it.
"""
from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256
from typing import Any

from sqlalchemy import select

from autotrader.domain import new_id, utc_now
from autotrader.persistence.accounting import SCALE, ZERO
from autotrader.persistence.models import (
    BalanceModel,
    CapitalReservationModel,
    ExitIntentModel,
    ExitTargetModel,
    FillModel,
    JournalEventModel,
    OrderModel,
    PositionModel,
)


async def _plan(repo:Any,session:Any,account:Any)->dict[str,Any]:
    from autotrader.persistence.repository import _json
    if account.control not in {'PAUSED','STOPPED','EMERGENCY'}:
        raise ValueError('Pause new entries before reviewing a correction.')
    if await session.scalar(select(OrderModel.order_id).where(OrderModel.status.in_(['PENDING','ACCEPTED'])).limit(1)):
        raise ValueError('Resolve pending orders before projection repair.')
    if await session.scalar(select(CapitalReservationModel.reservation_id).where(CapitalReservationModel.status=='OPEN').limit(1)):
        raise ValueError('Resolve cash reservations before projection repair.')
    if await session.scalar(select(ExitIntentModel.exit_intent_id).where(ExitIntentModel.status=='OPEN').limit(1)):
        raise ValueError('Resolve exit intentions before projection repair.')
    issues=await repo._verify(session,account.initial_cash)
    allowed=('cash_balance_does_not_match_journal_replay','reserved_cash_does_not_match_journal_replay',
             'negative_cash','position_quantity_does_not_match_fill_replay:',
             'position_cost_or_pnl_does_not_match_journal:','target_progress_does_not_match_linked_fills:')
    if any(not issue.startswith(allowed) for issue in issues):
        raise ValueError('Immutable history requires reviewed remediation: '+','.join(issues))
    fills=list((await session.scalars(select(FillModel).order_by(FillModel.fill_id))).all())
    events=list((await session.scalars(select(JournalEventModel).order_by(JournalEventModel.ledger_event_id))).all())
    supported={'INITIAL_FUNDING','CASH_RESERVATION','RESERVATION_RELEASE','BUY_FILL','SELL_FILL','FEE','AUDITED_CORRECTION','BALANCE_ADJUSTMENT'}
    if any(e.event_type not in supported or e.account_id!=repo.account_id for e in events):
        raise ValueError('Unsupported financial history; no correction can invent its meaning.')
    if any(f.account_id!=repo.account_id for f in fills):
        raise ValueError('Unresolved account attribution; refusing projection repair.')
    if sum(e.event_type=='INITIAL_FUNDING' for e in events)!=1:
        raise ValueError('Initial funding must have exactly one proven event.')
    if any(e.event_type in {'BUY_FILL','SELL_FILL','FEE'} and not e.fill_id for e in events):
        raise ValueError('Unlinked economic event; refusing projection repair.')
    if any(e.event_type in {'AUDITED_CORRECTION','BALANCE_ADJUSTMENT'} and
           any((e.cash_delta,e.reserved_delta,e.quantity_delta,e.cost_basis_delta,e.realized_pnl_delta)) for e in events):
        raise ValueError('Unsupported economic adjustment; this repair cannot invent funding.')
    cash=sum((e.cash_delta for e in events),ZERO)
    reserved=sum((e.reserved_delta for e in events),ZERO)
    if cash<0 or reserved!=0:
        raise ValueError('History does not support a nonnegative unreserved balance.')
    changes=[]
    def patch(entity:str,key:str,row:Any,values:dict[str,Any])->None:
        fields={name:{'before':str(getattr(row,name)),'after':str(value)} for name,value in values.items() if getattr(row,name)!=value}
        if fields:
            changes.append({'entity':entity,'id':key,'fields':fields})
    balance=await session.get(BalanceModel,repo.quote_asset)
    patch('balance',repo.quote_asset,balance,{'available':cash,'reserved':ZERO})
    for position in (await session.scalars(select(PositionModel).order_by(PositionModel.position_id))).all():
        if position.account_id!=repo.account_id:
            raise ValueError('Unresolved position account; refusing projection repair.')
        pf=[f for f in fills if f.position_id==position.position_id]
        pe=[e for e in events if e.position_id==position.position_id]
        quantity=sum((f.quantity if f.side=='BUY' else -f.quantity for f in pf),ZERO)
        journal_quantity=sum((e.quantity_delta for e in pe),ZERO)
        basis=sum((e.cost_basis_delta for e in pe),ZERO)
        pnl=sum((e.realized_pnl_delta for e in pe),ZERO)
        if quantity!=journal_quantity or quantity<0 or basis < -SCALE:
            raise ValueError('Fill and journal history disagree; refusing projection repair.')
        patch('position',position.position_id,position,{'quantity':quantity,'cost_basis':basis,'realized_pnl':pnl})
    for target in (await session.scalars(select(ExitTargetModel).order_by(ExitTargetModel.target_id))).all():
        filled=sum((f.quantity for f in fills if f.exit_target_id==target.target_id and f.position_id==target.position_id),ZERO)
        remaining=target.original_planned_quantity-filled
        if remaining<0:
            raise ValueError('Immutable target history is overfilled.')
        patch('target',target.target_id,target,{'filled_quantity':filled,'remaining_quantity':remaining,'reserved_quantity':ZERO,
            'status':'COMPLETED' if remaining==0 else 'PARTIAL' if filled else 'PENDING'})
    history=sha256(_json([[[getattr(row,c.name) for c in row.__table__.columns] for row in rows] for rows in (events,fills)]).encode()).hexdigest()
    plan={'account_id':repo.account_id,'changes':changes,'problems':issues,'history_digest':history}
    plan['fingerprint']=sha256(_json(plan).encode()).hexdigest()
    return plan


async def review_projection_repair(repo:Any)->dict[str,Any]:
    async with repo.session_factory() as session,session.begin():
        account=await repo._lock_account(session)
        return await _plan(repo,session,account)


async def apply_projection_repair(repo:Any,*,request_id:str,fingerprint:str,actor:str,reason:str)->dict[str,str]:
    if not request_id or len(request_id)>64 or len(reason.strip())<20 or not actor.strip():
        raise ValueError('Correction identity, operator and a meaningful audit reason are required.')
    from autotrader.persistence.repository import _json
    async with repo.session_factory() as session,session.begin():
        account=await repo._lock_account(session)
        key='correction:'+request_id
        existing=await session.scalar(select(JournalEventModel).where(JournalEventModel.event_key==key))
        if existing:
            payload=json.loads(existing.payload_json)
            if (payload['plan']['fingerprint'],payload['actor'],payload['reason'])!=(fingerprint,actor,reason):
                raise ValueError('Correction request identity was reused with different content.')
            return {'status':'APPLIED','ledger_event_id':existing.ledger_event_id}
        plan=await _plan(repo,session,account)
        if plan['fingerprint']!=fingerprint:
            raise ValueError('Stale correction plan; review current state again.')
        if not plan['changes']:
            raise ValueError('No projection changes are required.')
        models={'balance':BalanceModel,'position':PositionModel,'target':ExitTargetModel}
        for change in plan['changes']:
            row=await session.get(models[change['entity']],change['id'])
            for name,values in change['fields'].items():
                setattr(row,name,values['after'] if name=='status' else Decimal(values['after']))
        audit=new_id('jev')
        session.add(JournalEventModel(ledger_event_id=audit,event_key=key,account_id=repo.account_id,currency=repo.quote_asset,
            event_type='AUDITED_CORRECTION',cash_delta=ZERO,reserved_delta=ZERO,quantity_delta=ZERO,
            cost_basis_delta=ZERO,realized_pnl_delta=ZERO,reconciliation_state='CONFIRMED',created_at=utc_now(),
            payload_json=_json({'actor':actor,'reason':reason,'plan':plan})))
        if any(change['entity']=='balance' for change in plan['changes']):
            session.add(JournalEventModel(ledger_event_id=new_id('jev'),event_key='balance-repair:'+request_id,
                account_id=repo.account_id,currency=repo.quote_asset,event_type='BALANCE_ADJUSTMENT',
                cash_delta=ZERO,reserved_delta=ZERO,quantity_delta=ZERO,cost_basis_delta=ZERO,realized_pnl_delta=ZERO,
                reconciliation_state='CONFIRMED',created_at=utc_now(),payload_json=_json({'audit_event_id':audit,
                    'meaning':'Materialized balance restored to immutable economics; no cash flow created.'})))
        await session.flush()
        if await repo._verify(session,account.initial_cash):
            raise ValueError('Correction did not reconcile completely; transaction rolled back.')
        return {'status':'APPLIED','ledger_event_id':audit}
