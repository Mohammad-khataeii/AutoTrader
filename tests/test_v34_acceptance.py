from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text

from autotrader.domain import (
    DecisionAction,
    OrderBook,
    OrderBookLevel,
    OrderType,
    RuntimeHealth,
    Side,
    TradingDecision,
    TradingPair,
    new_id,
    utc_now,
)
from autotrader.execution_gateway import PaperExecutionGateway
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.models import (
    CooldownModel,
    FillModel,
)
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.risk import RiskEngine, RiskLimits
from process_support import ApiProcess, WorkerProcess, replay_frame, wait_for, write_frame

pytestmark = pytest.mark.asyncio
PAIR = TradingPair("BTC-EUR", "BTC", "EUR", min_order_quote=D(1))


def book(price: str, qty: str = "100") -> OrderBook:
    p = D(price)
    return OrderBook(PAIR.symbol, utc_now(), (OrderBookLevel(p-D("0.001"),D(qty)),), (OrderBookLevel(p+D("0.001"), D(qty)),), "acceptance-replay")


def gateway(repo: PersistentTradingRepository) -> PaperExecutionGateway:
    return PaperExecutionGateway(repo, market_data=MarketDataService(None),  # type: ignore[arg-type]
        risk_engine=RiskEngine(RiskLimits()), initial_cash=D(500), fee_bps=D(0), slippage_bps=D(0))


async def buy(repo: PersistentTradingRepository, key: str = "open", *, symbol: str = "BTC-EUR", quote: str = "100"):
    price = D(10)
    pair = TradingPair(symbol, symbol.split("-")[0], "EUR", min_order_quote=D(1))
    b = OrderBook(symbol, utc_now(), (OrderBookLevel(D("9.998"), D(100)),), (OrderBookLevel(price, D(100)),), "acceptance-replay")
    decision = TradingDecision(new_id("dec"), symbol, utc_now(), DecisionAction.BUY, [], None,
        D(quote), D(quote)/price, price, D("9.8"), (D(11), D(12), D(13)), True, None, "Explicit accounting acceptance setup")
    await repo.store_analysis([], None, decision)
    return await gateway(repo).execute_entry_decision(pair, decision, b, key)


async def targets_equal(repo: PersistentTradingRepository, expected: list[D]) -> bool:
    rows = await repo.list_targets()
    return len(rows) == len(expected) and [D(t["filled_quantity"]) for t in rows] == expected


async def test_proof_a_targets_survive_actual_worker_restart_and_stop(pg_repo: PersistentTradingRepository, tmp_path: Path) -> None:
    repo = pg_repo
    await repo.initialize_portfolio(D(500))
    entry = await buy(repo)
    assert entry.order is not None and entry.order.filled_quantity == D(10)
    first = (await repo.list_positions())[0]
    replay = tmp_path / "replay.json"
    write_frame(replay, replay_frame("tp1", D("11.01")))
    worker = WorkerProcess(repo.test_database_url, replay)  # type: ignore[attr-defined]
    try:
        await wait_for(lambda: targets_equal(repo, [D(3), D(0), D(0)]), worker=worker)
        write_frame(replay, replay_frame("tp2-partial", D("12.01"), "1.5"))
        await wait_for(lambda: targets_equal(repo, [D(3), D("1.5"), D(0)]), worker=worker)
        old_pid = worker.kill()
        assert worker.process.returncode is not None
        worker = WorkerProcess(repo.test_database_url, replay)  # type: ignore[attr-defined]
        assert worker.process.pid != old_pid
        await asyncio.sleep(2)
        assert await targets_equal(repo, [D(3), D("1.5"), D(0)])
        write_frame(replay, replay_frame("tp2-complete", D("12.02"), "2.5"))
        await wait_for(lambda: targets_equal(repo, [D(3), D(4), D(0)]), worker=worker)
        write_frame(replay, replay_frame("stop", D("10.1"), "100"))
        async def closed() -> bool:
            return (await repo.list_positions())[0].quantity == 0
        await wait_for(closed, worker=worker)
    finally:
        worker.kill()
    assert await targets_equal(repo, [D(3), D(4), D(0)])
    targets = await repo.list_targets()
    assert [D(t["target_price"]) for t in targets] == [D(11), D(12), D(13)]
    assert (await repo.list_positions())[0].closed_at is not None
    async with repo.session_factory() as s, s.begin():
        # Advance only the external cooldown boundary; every position/fill came through execution.
        cooldown = await s.get(CooldownModel, "BTC-EUR")
        cooldown.expires_at = utc_now() - timedelta(seconds=1)
    again = await buy(repo, "fresh-setup")
    assert again.accepted
    second = next(p for p in await repo.list_positions() if p.closed_at is None)
    assert second.position_id != first.position_id
    assert all(D(t["filled_quantity"]) == 0 for t in await repo.list_targets(second.position_id))
    assert await repo.verify_invariants(D(500)) == []
    async with repo.session_factory() as s:
        stop = await s.scalar(select(FillModel).where(FillModel.side == "SELL", FillModel.exit_target_id.is_(None)))
        assert stop and stop.quantity == D(3) and stop.exit_intent_id
    print(f"PROOF_A worker killed pid={old_pid}; restarted pid={worker.process.pid}; TP=[3,4,0]; reconciliation=[]")


async def test_proof_b_unrealized_equity_halt_survives_process_restart(pg_repo: PersistentTradingRepository, tmp_path: Path) -> None:
    repo = pg_repo
    await repo.initialize_portfolio(D(500))
    assert (await buy(repo, "btc", symbol="BTC-EUR")).accepted
    assert (await buy(repo, "eth", symbol="ETH-EUR")).accepted
    for symbol in ("BTC-EUR", "ETH-EUR"):
        b = book("9")
        await repo.record_mark(OrderBook(symbol,b.timestamp,b.bids,b.asks,b.source))
    snapshot = await repo.snapshot()
    assert D(snapshot["cash"]) == 300 and D(snapshot["open_exposure"]) == 180
    assert D(snapshot["equity"]) == 480 and D(snapshot["daily_equity_change"]) == -20
    assert snapshot["risk_state"] == "RISK_HALTED"
    assert not (await buy(repo, "blocked", symbol="SOL-EUR")).accepted
    replay = tmp_path / "halt.json"
    write_frame(replay, replay_frame("halt", D("9")))
    process1 = WorkerProcess(repo.test_database_url, replay)  # type: ignore[attr-defined]
    await asyncio.sleep(2)
    old_pid = process1.kill()
    process2 = WorkerProcess(repo.test_database_url, replay)  # type: ignore[attr-defined]
    try:
        await asyncio.sleep(2)
        assert await repo.get_runtime_health() is RuntimeHealth.RISK_HALTED
        p = next(p for p in await repo.list_positions() if p.symbol == "ETH-EUR")
        exit_result = await gateway(repo).execute_exit(TradingPair("ETH-EUR","ETH","EUR"), p.quantity,
            OrderBook("ETH-EUR",utc_now(),book("9").bids,book("9").asks,"acceptance-replay"), "protect-eth", "protective_stop", position_id=p.position_id)
        assert exit_result.accepted
        assert await repo.get_runtime_health() is RuntimeHealth.RISK_HALTED
    finally:
        process2.kill()
    assert process2.process.pid != old_pid
    assert await repo.verify_invariants(D(500)) == []


async def test_proof_d_concurrent_buys_idempotency_and_sell_race(pg_repo: PersistentTradingRepository) -> None:
    repo = pg_repo
    await repo.initialize_portfolio(D(500))
    results = await asyncio.gather(buy(repo,"one",symbol="BTC-EUR"),buy(repo,"two",symbol="ETH-EUR"))
    assert all(r.accepted for r in results)
    # Duplicate the identical durable intention through independent sessions.
    duplicates = await asyncio.gather(*(buy(repo,"one",symbol="BTC-EUR") for _ in range(3)))
    assert len({r.order.order_id for r in duplicates}) == 1
    position = next(p for p in await repo.list_positions() if p.symbol == "BTC-EUR")
    target = (await repo.list_targets(position.position_id))[0]
    exits = await asyncio.gather(
        repo.submit_order(PAIR,Side.SELL,OrderType.MARKET,D(3),D(0),book("11.1"),"tp-race",position_id=position.position_id,exit_target_id=target["target_id"],exit_reason="TAKE_PROFIT",fee_bps=D(0),slippage_bps=D(0)),
        repo.submit_order(PAIR,Side.SELL,OrderType.MARKET,D(10),D(0),book("9.7"),"stop-race",position_id=position.position_id,exit_reason="STOP",fee_bps=D(0),slippage_bps=D(0)))
    assert sum((o.filled_quantity for o in exits), D(0)) <= 10
    assert await repo.verify_invariants(D(500)) == []
    async with repo.session_factory() as s:
        assert await s.scalar(select(func.count()).select_from(FillModel).where(FillModel.side == "BUY")) == 2


@pytest.mark.parametrize("point", ["before_capital_reservation", "after_reservation_persistence", "before_order_dispatch", "after_order_dispatch", "before_fill_persistence", "after_fill_persistence", "before_ledger_posting", "after_ledger_commit"])
async def test_worker_entry_crash_boundaries_recover(pg_repo: PersistentTradingRepository, tmp_path: Path, point: str) -> None:
    repo = pg_repo
    replay = tmp_path / "crash.json"
    write_frame(replay, replay_frame("entry", D("9.92"), qualifying=True))
    worker = WorkerProcess(repo.test_database_url, replay, point)  # type: ignore[attr-defined]
    try:
        await asyncio.to_thread(worker.process.wait, 30)
        assert worker.process.returncode == 86, worker.log_path.read_text()
    finally:
        old_pid = worker.kill()
    worker = WorkerProcess(repo.test_database_url, replay)  # type: ignore[attr-defined]
    try:
        async def filled() -> bool:
            return any(p.quantity > 0 for p in await repo.list_positions())
        await wait_for(filled,worker=worker)
        assert worker.process.pid != old_pid
        assert await repo.verify_invariants(D(500)) == []
        async with repo.session_factory() as s:
            assert await s.scalar(select(func.count()).select_from(FillModel).where(FillModel.side == "BUY")) == 1
        assert D((await repo.snapshot())["reserved_cash"]) == 0
    finally:
        worker.kill()


async def test_journal_and_fills_are_immutable_in_database(pg_repo: PersistentTradingRepository) -> None:
    await pg_repo.initialize_portfolio(D(500))
    assert (await buy(pg_repo)).accepted
    for table in ("fills", "financial_journal"):
        async with pg_repo.session_factory() as s:
            with pytest.raises(Exception, match="immutable financial history"):
                await s.execute(text(f"DELETE FROM {table}"))
            await s.rollback()


async def test_proof_c_full_autonomous_lifecycle_and_authenticated_api(pg_repo: PersistentTradingRepository, tmp_path: Path) -> None:
    repo = pg_repo
    api = ApiProcess(repo.test_database_url, tmp_path)  # type: ignore[attr-defined]
    replay = tmp_path / "lifecycle.json"
    write_frame(replay, replay_frame("qualifying-setup", D("9.92"), qualifying=True))
    worker = WorkerProcess(repo.test_database_url, replay)  # type: ignore[attr-defined]
    try:
        async with httpx.AsyncClient(base_url=api.url, timeout=5) as client:
            async def ready() -> bool:
                try:
                    return (await client.get("/readyz")).status_code == 200
                except httpx.TransportError:
                    return False
            await wait_for(ready, worker=api)
            async def opened() -> bool:
                return any(p.quantity > 0 for p in await repo.list_positions())
            await wait_for(opened, worker=worker)
            position = (await repo.list_positions())[0]
            targets = await repo.list_targets(position.position_id)
            assert len(targets) == 3
            q1, q2 = D(targets[0]["original_planned_quantity"]), D(targets[1]["original_planned_quantity"])
            write_frame(replay, replay_frame("autonomous-tp1", D(targets[0]["target_price"]) + D("0.002")))
            await wait_for(lambda: targets_equal(repo, [q1,D(0),D(0)]),worker=worker)
            old_pid = worker.kill()
            worker = WorkerProcess(repo.test_database_url, replay)  # type: ignore[attr-defined]
            assert worker.process.pid != old_pid
            async def recovered_frame() -> bool:
                return await repo.last_worker_frame() == "autonomous-tp1"
            await wait_for(recovered_frame,worker=worker)
            write_frame(replay, replay_frame("autonomous-tp2", D(targets[1]["target_price"]) + D("0.002")))
            await wait_for(lambda: targets_equal(repo,[q1,q2,D(0)]),worker=worker)
            write_frame(replay, replay_frame("autonomous-stop", D("9.85")))
            async def closed() -> bool:
                return (await repo.list_positions())[0].quantity == 0
            await wait_for(closed,worker=worker)
            assert await repo.verify_invariants(D(500)) == []
            assert (await client.get("/api/overview")).status_code == 401
            auth = ("admin","change-me")
            overview = (await client.get("/api/overview",auth=auth)).json()
            assert overview["portfolio"]["positions"] == "0"
            assert D(overview["portfolio"]["reserved_cash"]) == 0
            assert overview["health"]["mode"] == "paper"
            assert len(overview["fills"]) == 4
            assert len({f["fill_id"] for f in overview["fills"]}) == 4
            assert all(f["simulated"] == "True" for f in overview["fills"])
            assert [D(t["filled_quantity"]) for t in overview["targets"]] == [q1,q2,D(0)]
            history = (await client.get("/api/history",auth=auth)).json()
            assert history["signals"] and any(d["accepted"] for d in history["decisions"])
            assert any(e["event_type"] == "BUY_FILL" for e in history["journal"])
            assert any(e["event_type"] == "SELL_FILL" for e in history["journal"])
            assert (await client.post("/api/controls/pause")).status_code == 401
            assert (await client.post("/api/controls/pause",auth=auth)).json()["control"] == "PAUSED"
            assert (await client.post("/api/controls/resume",auth=auth)).json()["control"] == "RUNNING"
            assert D(overview["portfolio"]["available_cash"]) >= 150
            print(f"PROOF_C API pid={api.process.pid}; worker restart {old_pid}->{worker.process.pid}; fills=4; targets=[{q1},{q2},0]; journal replay=[]")
    finally:
        worker.kill()
        api.kill()
