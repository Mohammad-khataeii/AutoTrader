from __future__ import annotations

import asyncio
import json
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from autotrader.domain import new_id
from autotrader.persistence.corrections import review_projection_repair
from autotrader.persistence.models import (
    BalanceModel,
    ExitTargetModel,
    JournalEventModel,
    PositionModel,
)
from autotrader.persistence.repository import PersistentTradingRepository
from process_support import ApiProcess, wait_for
from test_v34_acceptance import PAIR, book, buy, gateway

pytestmark=pytest.mark.asyncio


async def test_authenticated_reviewed_projection_repair_is_atomic_and_idempotent(pg_repo:PersistentTradingRepository,tmp_path:Path)->None:
    repo=pg_repo
    await repo.initialize_portfolio(D(500))
    assert (await buy(repo)).accepted
    position=(await repo.list_positions())[0]
    target=(await repo.list_targets())[0]
    # This proof needs an executable bid above the target, not a midpoint touch.
    assert (await gateway(repo).execute_exit(PAIR,D(3),book('11.01'),'target','take_profit_target',
        position_id=position.position_id,exit_target_id=target['target_id'])).accepted
    fills=await repo.list_fills()
    good=await repo.snapshot()
    async with repo.session_factory() as session,session.begin():
        balance=await session.get(BalanceModel,'EUR')
        balance.available,balance.reserved=D(123),D(9)
        row=await session.get(PositionModel,position.position_id)
        row.quantity,row.cost_basis,row.realized_pnl=D(20),D(12),D(999)
        target_row=await session.get(ExitTargetModel,target['target_id'])
        target_row.filled_quantity,target_row.remaining_quantity=D(1),D(2)
    await repo.reconcile_runtime_health(D(500))
    api=ApiProcess(repo.test_database_url,tmp_path)  # type: ignore[attr-defined]
    try:
        async with httpx.AsyncClient(base_url=api.url,auth=('admin','change-me')) as client:
            async def ready()->bool:
                try:
                    return (await client.get('/readyz')).status_code==200
                except httpx.HTTPError:
                    return False
            await wait_for(ready,worker=api)
            assert (await client.get('/api/reconciliation/repair-plan')).status_code==409
            await repo.set_control('pause')
            plan=(await client.get('/api/reconciliation/repair-plan')).json()
            assert len(plan['changes'])==3
            body={'request_id':'reviewed-correction','fingerprint':plan['fingerprint'],
                  'reason':'Restore projections to independently replayed confirmed fills and journal.'}
            async with httpx.AsyncClient(base_url=api.url) as unauthorized:
                assert (await unauthorized.post('/api/reconciliation/repair',json=body)).status_code==401
            # Intervening tampering invalidates the old reviewed plan.
            async with repo.session_factory() as session,session.begin():
                balance=await session.get(BalanceModel,'EUR')
                balance.available=D(124)
            assert (await client.post('/api/reconciliation/repair',json=body)).status_code==409
            plan=(await client.get('/api/reconciliation/repair-plan')).json()
            body['fingerprint']=plan['fingerprint']
            one,two=await asyncio.gather(client.post('/api/reconciliation/repair',json=body),client.post('/api/reconciliation/repair',json=body))
            assert one.status_code==two.status_code==200,(one.text,two.text)
            assert one.json()==two.json()
            body['reason']='Different meaning must not reuse the same correction identity.'
            assert (await client.post('/api/reconciliation/repair',json=body)).status_code==409
            assert await repo.verify_invariants(D(500))==[]
            assert await repo.list_fills()==fills
            repaired=await repo.snapshot()
            assert repaired['cash']==good['cash'] and repaired['reserved_cash']=='0E-12'
            assert repaired['risk_state']=='RECONCILIATION_REQUIRED'
            assert (await repo.list_positions())[0].quantity==7
            async with repo.session_factory() as session:
                audit=await session.scalar(select(JournalEventModel).where(JournalEventModel.event_type=='AUDITED_CORRECTION'))
                assert json.loads(audit.payload_json)['actor']=='admin'
                assert audit.cash_delta==audit.quantity_delta==0
                assert await session.scalar(select(func.count()).select_from(JournalEventModel).where(JournalEventModel.event_type=='BALANCE_ADJUSTMENT'))==1
    finally:
        api.kill()


@pytest.mark.parametrize('kind',['UNKNOWN_EVENT','BALANCE_ADJUSTMENT','FEE'])
async def test_projection_repair_cannot_invent_meaning_for_economic_history(pg_repo:PersistentTradingRepository,kind:str)->None:
    await pg_repo.initialize_portfolio(D(500))
    await pg_repo.set_control('pause')
    async with pg_repo.session_factory() as session,session.begin():
        session.add(JournalEventModel(ledger_event_id=new_id('jev'),event_key='unsupported',account_id='paper-eur',
            currency='EUR',event_type=kind,cash_delta=D(1),reserved_delta=D(0),quantity_delta=D(0),
            cost_basis_delta=D(0),realized_pnl_delta=D(0),reconciliation_state='CONFIRMED',payload_json='{}'))
    with pytest.raises(ValueError):
        await review_projection_repair(pg_repo)
    assert D((await pg_repo.snapshot())['cash'])==500
