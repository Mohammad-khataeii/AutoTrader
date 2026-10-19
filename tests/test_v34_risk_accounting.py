from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from autotrader.clock import at
from autotrader.domain import (
    OrderBook,
    OrderStatus,
    OrderType,
    Side,
    utc_now,
)
from autotrader.market_data.replay import FileReplayClient
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.models import FillModel, PositionModel
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.persistence.retry import retry_economic
from autotrader.position_manager import PositionManager
from process_support import WorkerProcess, replay_frame, wait_for, write_frame
from test_v34_acceptance import PAIR, book, buy, gateway

pytestmark = pytest.mark.asyncio


async def test_fees_cost_basis_realized_pnl_and_duplicate_fill(pg_repo: PersistentTradingRepository) -> None:
    repo = pg_repo
    await repo.initialize_portfolio(D(500))
    order = await repo.submit_order(PAIR,Side.BUY,OrderType.MARKET,D(9),D(100),book("10"),"fee-buy",fee_bps=D(10),slippage_bps=D(0),stop_loss=D("9.8"),targets=[D(11),D(12),D(13)])
    assert order.status is OrderStatus.FILLED
    position = (await repo.list_positions())[0]
    async with repo.session_factory() as s:
        entry = await s.scalar(select(FillModel).where(FillModel.order_id == order.order_id))
        opening_basis = entry.quantity * entry.price + entry.fee
    assert position.cost_basis == opening_basis
    sell = await repo.submit_order(PAIR,Side.SELL,OrderType.MARKET,D(3),D(0),book("11"),"fee-sell",fee_bps=D(10),slippage_bps=D(0),position_id=position.position_id,exit_reason="STOP")
    async with repo.session_factory() as s:
        closing = await s.scalar(select(FillModel).where(FillModel.order_id == sell.order_id))
        from autotrader.persistence.accounting import exact
        expected = closing.quantity*closing.price-closing.fee-exact(opening_basis/3)
    updated = (await repo.list_positions())[0]
    assert updated.realized_pnl == expected
    assert await repo.realized_pnl_since(utc_now()-timedelta(minutes=1)) == expected
    async with repo.session_factory() as s:
        with pytest.raises(IntegrityError):
            await s.execute(text("INSERT INTO fills SELECT * FROM fills LIMIT 1"))
        await s.rollback()
    assert await repo.verify_invariants(D(500)) == []


async def test_weekly_unrealized_loss_after_day_rollover(pg_repo: PersistentTradingRepository) -> None:
    # Tuesday -> Wednesday stays within one ISO week, regardless of execution day.
    with at(datetime(2026, 10, 13, 12, tzinfo=UTC)):
        await _weekly_loss_across_same_week_day(pg_repo)


async def _weekly_loss_across_same_week_day(pg_repo: PersistentTradingRepository) -> None:
    repo=pg_repo
    await repo.initialize_portfolio(D(500))
    assert (await buy(repo,symbol="BTC-EUR")).accepted
    assert (await buy(repo,"eth",symbol="ETH-EUR")).accepted
    now=utc_now()
    # End the previous day with the loss recorded through real market marks.
    for symbol in ("BTC-EUR","ETH-EUR"):
        b=book("8")
        await repo.record_mark(OrderBook(symbol,b.timestamp,b.bids,b.asks,b.source))
    assert D((await repo.snapshot())["equity"]) == 460
    with at(now+timedelta(days=1)):
        for symbol in ("BTC-EUR","ETH-EUR"):
            b=book("8")
            await repo.record_mark(OrderBook(symbol,b.timestamp,b.bids,b.asks,b.source))
        snapshot=await repo.snapshot()
        assert D(snapshot["daily_equity_change"]) == 0
        assert D(snapshot["weekly_equity_change"]) == -40
        assert snapshot["risk_state"] == "RISK_HALTED"
        assert await repo.reset_runtime_health_after_reconciliation(D(500)) == ["equity_loss_limit_still_breached"]


async def test_missing_or_stale_mark_blocks_entries(pg_repo: PersistentTradingRepository) -> None:
    repo=pg_repo
    await repo.initialize_portfolio(D(500))
    assert (await buy(repo)).accepted
    with at(utc_now()+timedelta(seconds=100)):
        snapshot=await repo.snapshot()
        assert snapshot["equity"] == "" and snapshot["valuation_degraded"] == "true"
        assert snapshot["risk_state"] == "DATA_DEGRADED"
        assert not (await buy(repo,"new",symbol="ETH-EUR")).accepted


async def test_time_exit_and_cooldown_use_shared_clock(pg_repo: PersistentTradingRepository,tmp_path:Path) -> None:
    repo=pg_repo
    await repo.initialize_portfolio(D(500))
    assert (await buy(repo)).accepted
    replay=tmp_path/'time.json'
    with at(utc_now()+timedelta(hours=25)):
        write_frame(replay,replay_frame("time",D("10")))
        data=MarketDataService(FileReplayClient(str(replay)))  # type: ignore[arg-type]
        g=gateway(repo)
        g.market_data=data
        actions=await PositionManager(repository=repo,market_data=data,execution_gateway=g).monitor_once([])
        assert actions[0].reason == "time_exit"
        assert (await repo.list_positions())[0].quantity == 0
        assert not (await buy(repo,"cooldown-reentry")).accepted
        assert all(D(t['filled_quantity']) == 0 for t in await repo.list_targets())
    assert await repo.verify_invariants(D(500)) == []


async def test_real_postgres_deadlock_is_retried(pg_repo: PersistentTradingRepository) -> None:
    repo=pg_repo
    await repo.initialize_portfolio(D(500))
    async with repo.session_factory() as s,s.begin():
        await s.execute(text("CREATE TABLE retry_probe (id integer PRIMARY KEY, touches integer NOT NULL)"))
        await s.execute(text("INSERT INTO retry_probe VALUES (1,0),(2,0)"))
    barrier=asyncio.Barrier(2)
    attempts={1:0,2:0}
    @retry_economic
    async def transact(first:int,second:int)->None:
        attempts[first]+=1
        async with repo.session_factory() as s,s.begin():
            await s.execute(text("SELECT * FROM retry_probe WHERE id=:id FOR UPDATE"),{'id':first})
            if attempts[first]==1:
                await barrier.wait()
            await s.execute(text("UPDATE retry_probe SET touches=touches+1 WHERE id=:id"),{'id':second})
    await asyncio.gather(transact(1,2),transact(2,1))
    assert sum(attempts.values()) == 3
    async with repo.session_factory() as s:
        assert list((await s.execute(text("SELECT touches FROM retry_probe ORDER BY id"))).scalars()) == [1,1]
    assert await repo.verify_invariants(D(500)) == []


@pytest.mark.parametrize('point,price',[("during_target_completion","11.01"),("during_protective_stop_processing","9.7"),("after_reservation_persistence","11.01"),("after_ledger_commit","11.01")])
async def test_exit_process_crash_rolls_back_target_and_ledger(pg_repo:PersistentTradingRepository,tmp_path:Path,point:str,price:str)->None:
    repo=pg_repo
    await repo.initialize_portfolio(D(500))
    assert (await buy(repo)).accepted
    replay=tmp_path/'exit.json'
    write_frame(replay,replay_frame('exit',D(price)))
    worker=WorkerProcess(repo.test_database_url,replay,point)  # type: ignore[attr-defined]
    try:
        await asyncio.to_thread(worker.process.wait,30)
        assert worker.process.returncode==86,worker.log_path.read_text()
    finally:
        old_pid=worker.kill()
    worker=WorkerProcess(repo.test_database_url,replay)  # type: ignore[attr-defined]
    try:
        async def exited()->bool:
            return (await repo.list_positions())[0].quantity < 10
        await wait_for(exited,worker=worker)
        assert old_pid!=worker.process.pid
        assert await repo.verify_invariants(D(500))==[]
        targets=await repo.list_targets()
        assert [D(t['filled_quantity']) for t in targets]==([D(3),D(0),D(0)] if D(price)>10 else [D(0),D(0),D(0)])
    finally:
        worker.kill()


async def test_lost_database_connection_after_commit_does_not_duplicate_economics(pg_repo:PersistentTradingRepository)->None:
    repo=pg_repo
    await repo.initialize_portfolio(D(500))
    first=await buy(repo,'committed-key')
    assert first.accepted
    async with repo.session_factory.kw['bind'].connect() as lost:
        pid=await lost.scalar(text('SELECT pg_backend_pid()'))
        await lost.commit()
        async with repo.session_factory() as killer:
            await killer.execute(text('SELECT pg_terminate_backend(:pid)'),{'pid':pid})
            await killer.commit()
    duplicate=await buy(repo,'committed-key')
    assert duplicate.order.order_id==first.order.order_id
    assert len(await repo.list_fills())==1
    assert await repo.verify_invariants(D(500))==[]


async def test_trailing_stop_never_moves_down_and_cooldown_survives_repository_reopen(pg_repo:PersistentTradingRepository,tmp_path:Path)->None:
    repo=pg_repo
    await repo.initialize_portfolio(D(500))
    assert (await buy(repo)).accepted
    p=(await repo.list_positions())[0]
    t=(await repo.list_targets(p.position_id))[0]
    await gateway(repo).execute_exit(PAIR,D(3),book('11.01'),'tp1','take_profit_target',position_id=p.position_id,exit_target_id=t['target_id'])
    await repo.record_mark(book('12'))
    await repo.update_position_monitor(p.position_id,D(12))
    stop=(await repo.list_positions())[0].protective_stop
    await repo.record_mark(book('11.8'))
    await repo.update_position_monitor(p.position_id,D('11.8'))
    updated=(await repo.list_positions())[0]
    assert updated.protective_stop==stop and updated.highest_price==12
    assert updated.protective_stop>=updated.average_entry_price


async def test_worker_crash_during_cancellation_recovers_reservation(pg_repo:PersistentTradingRepository,tmp_path:Path)->None:
    repo=pg_repo
    replay=tmp_path/'cancel.json'
    write_frame(replay,replay_frame('entry',D('9.92'),qualifying=True))
    worker=WorkerProcess(repo.test_database_url,replay,'after_reservation_persistence')  # type: ignore[attr-defined]
    await asyncio.to_thread(worker.process.wait,30)
    assert worker.process.returncode==86
    worker.kill()
    import json

    from autotrader.persistence.models import OrderModel
    async with repo.session_factory() as s,s.begin():
        order=await s.scalar(select(OrderModel))
        payload=json.loads(order.execution_json)
        payload['book']['timestamp']=(utc_now()-timedelta(minutes=10)).isoformat()
        order.execution_json=json.dumps(payload)
    worker=WorkerProcess(repo.test_database_url,replay,'during_cancellation')  # type: ignore[attr-defined]
    await asyncio.to_thread(worker.process.wait,30)
    assert worker.process.returncode==86
    worker.kill()
    worker=WorkerProcess(repo.test_database_url,replay)  # type: ignore[attr-defined]
    try:
        async def recovered()->bool:
            return any(p.quantity>0 for p in await repo.list_positions())
        await wait_for(recovered,worker=worker)
        assert D((await repo.snapshot())['reserved_cash'])==0
        assert await repo.verify_invariants(D(500))==[]
        assert len(await repo.list_fills())==1
    finally:
        worker.kill()


async def test_corrupt_position_projection_cannot_authorize_oversell(pg_repo:PersistentTradingRepository)->None:
    repo=pg_repo
    await repo.initialize_portfolio(D(500))
    assert (await buy(repo)).accepted
    p=(await repo.list_positions())[0]
    cash=(await repo.snapshot())['cash']
    async with repo.session_factory() as s,s.begin():
        row=await s.get(PositionModel,p.position_id)
        row.quantity=D(20)
    result=await gateway(repo).execute_exit(PAIR,D(20),book('9.7'),'corrupt-exit','protective_stop',position_id=p.position_id)
    assert not result.accepted
    assert len(await repo.list_fills())==1
    assert (await repo.snapshot())['cash']==cash
    assert (await repo.get_runtime_health()).value=='RECONCILIATION_REQUIRED'


async def test_marked_exposure_and_pending_dispatch_are_risk_checked(pg_repo:PersistentTradingRepository,tmp_path:Path)->None:
    repo=pg_repo
    await repo.initialize_portfolio(D(500))
    assert (await buy(repo,'btc')).accepted
    assert (await buy(repo,'eth',symbol='ETH-EUR')).accepted
    replay=tmp_path/'dispatch.json'
    frame=replay_frame('sol-setup',D('9.92'),qualifying=True)
    frame['pairs'][0].update(symbol='SOL-EUR',base_asset='SOL')
    frame['markets']={'SOL-EUR':frame['markets']['BTC-EUR']}
    write_frame(replay,frame)
    worker=WorkerProcess(repo.test_database_url,replay,'after_reservation_persistence')  # type: ignore[attr-defined]
    await asyncio.to_thread(worker.process.wait,30)
    assert worker.process.returncode==86,worker.log_path.read_text()
    worker.kill()
    # Existing assets appreciate after the intention commits, before execution.
    await repo.record_mark(book('25'))
    from dataclasses import replace
    await repo.record_mark(replace(book('10'),symbol='ETH-EUR'))
    worker=WorkerProcess(repo.test_database_url,replay)  # type: ignore[attr-defined]
    try:
        async def processed()->bool:
            return await repo.last_worker_frame()=='sol-setup'
        await wait_for(processed,worker=worker)
        assert len(await repo.list_fills())==2
        assert D((await repo.snapshot())['reserved_cash'])==0
        assert await repo.verify_invariants(D(500))==[]
        # This assertion isolates exposure risk. Refresh the external marks after
        # process/lease waits so a slower host cannot turn it into a stale-data test.
        await repo.record_mark(book('25'))
        await repo.record_mark(replace(book('10'),symbol='ETH-EUR'))
        denied=await buy(repo,'new-sol',symbol='SOL-EUR')
        assert not denied.accepted and 'total_exposure' in denied.reason
    finally:
        worker.kill()


async def test_strategy_cooldown_persists_across_symbols(pg_repo:PersistentTradingRepository)->None:
    repo=pg_repo
    await repo.initialize_portfolio(D(500))
    assert (await buy(repo,'entry')).accepted
    p=(await repo.list_positions())[0]
    assert (await gateway(repo).execute_exit(PAIR,p.quantity,book('9.9'),'close','protective_stop',position_id=p.position_id)).accepted
    reopened=PersistentTradingRepository(repo.session_factory)
    denied=await buy(reopened,'other-symbol',symbol='ETH-EUR')
    assert not denied.accepted and denied.reason=='strategy_cooldown'
    with at(utc_now()+timedelta(minutes=6)):
        assert (await buy(reopened,'fresh-qualifying-proposal',symbol='ETH-EUR')).accepted
    assert await repo.verify_invariants(D(500))==[]


@pytest.mark.parametrize('reason',['TIME_EXIT','EMERGENCY','MARKET_RISK'])
async def test_worker_protective_policies_use_durable_positions(pg_repo:PersistentTradingRepository,tmp_path:Path,reason:str)->None:
    repo=pg_repo
    entry_time=utc_now()-timedelta(hours=25) if reason=='TIME_EXIT' else utc_now()
    with at(entry_time):
        await repo.initialize_portfolio(D(500))
        assert (await buy(repo)).accepted
    if reason=='EMERGENCY':
        await repo.set_control('emergency')
    frame=replay_frame('protective',D(10))
    if reason=='MARKET_RISK':
        # The actual scanner computes/persists the bearish features; no internal
        # regime or position state is mocked or pre-completed.
        for index,candle in enumerate(frame['markets']['BTC-EUR']['candles']):
            price=D(15)-D(index)/50
            candle.update(open=str(price),high=str(price+D('.02')),low=str(price-D('.02')),close=str(price))
        frame['markets']['BTC-EUR']['candles'][-1].update(open='10',high='10.02',low='9.98',close='10')
    replay=tmp_path/'protective.json'
    write_frame(replay,frame)
    worker=WorkerProcess(repo.test_database_url,replay)  # type: ignore[attr-defined]
    try:
        await worker.wait_started(repo)
        if reason=='MARKET_RISK':
            async def scanned()->bool:
                return await repo.last_worker_frame()=='protective'
            await wait_for(scanned,worker=worker)
            frame['frame_id']='regime-exit'
            write_frame(replay,frame)
        async def closed()->bool:
            return (await repo.list_positions())[0].quantity==0
        await wait_for(closed,worker=worker)
        from autotrader.persistence.models import ExitIntentModel
        async with repo.session_factory() as session:
            intent=await session.scalar(select(ExitIntentModel))
            assert intent.reason==reason
        assert all(D(t['filled_quantity'])==0 for t in await repo.list_targets())
        assert await repo.verify_invariants(D(500))==[]
        assert not (await buy(repo,'blocked-reentry',symbol='ETH-EUR')).accepted
    finally:
        worker.kill()


async def test_public_rate_gate_is_shared_by_independent_sessions(pg_repo:PersistentTradingRepository)->None:
    await pg_repo.initialize_portfolio(D(500))
    other=PersistentTradingRepository(pg_repo.session_factory)
    first,second=await asyncio.gather(pg_repo.reserve_public_request('candles'),other.reserve_public_request('candles'))
    assert min(first,second)==0
    assert D('.5')<D(str(max(first,second)))<=1
    assert await other.reserve_public_request('orderbook')==0
    with at(utc_now()+timedelta(seconds=2)):
        assert await other.reserve_public_request('candles')==0
