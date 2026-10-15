from __future__ import annotations

import asyncio
import getpass
import os
import subprocess
from collections.abc import AsyncIterator
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from autotrader.domain import (
    OrderBook,
    OrderBookLevel,
    OrderStatus,
    OrderType,
    Side,
    TradingPair,
    utc_now,
)
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.models import (
    BalanceModel,
    CapitalReservationModel,
    FillModel,
    PositionModel,
)
from autotrader.persistence.repository import PersistentTradingRepository

pytestmark = pytest.mark.asyncio

PAIR = TradingPair("BTC-EUR", "BTC", "EUR", quantity_step=Decimal("0.00000001"), min_order_quote=Decimal("1"))


def pg_admin_url() -> str:
    return os.environ.get("AUTOTRADER_TEST_PG_ADMIN_URL", f"postgresql://{getpass.getuser()}@127.0.0.1:5432/postgres")


def pg_async_url(db_name: str) -> str:
    return os.environ.get("AUTOTRADER_TEST_DATABASE_URL", f"postgresql+asyncpg://{getpass.getuser()}@127.0.0.1:5432/{db_name}")


@pytest.fixture()
async def pg_repo() -> AsyncIterator[PersistentTradingRepository]:
    db_name = f"autotrader_v33_{uuid4().hex[:12]}"
    try:
        await asyncio.to_thread(
            subprocess.run,
            ["createdb", "-h", "127.0.0.1", db_name],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"PostgreSQL database creation unavailable: {exc}")
    engine = make_engine(SimpleNamespace(database_url=pg_async_url(db_name)))  # type: ignore[arg-type]
    try:
        await create_schema(engine)
        yield PersistentTradingRepository(make_session_factory(engine))
    finally:
        await engine.dispose()
        await asyncio.to_thread(
            subprocess.run,
            ["dropdb", "-h", "127.0.0.1", "--if-exists", db_name],
            check=False,
            capture_output=True,
            text=True,
        )


def book(price: Decimal, bid_qty: Decimal = Decimal("10"), ask_qty: Decimal = Decimal("10")) -> OrderBook:
    return OrderBook(
        PAIR.symbol,
        utc_now(),
        bids=(OrderBookLevel(price, bid_qty),) if bid_qty > 0 else (),
        asks=(OrderBookLevel(price, ask_qty),) if ask_qty > 0 else (),
        source="postgres-fixture",
    )


async def ledger(repo: PersistentTradingRepository) -> tuple[Decimal, dict[str, Decimal], int, int]:
    async with repo.session_factory() as session:
        balance = await session.get(BalanceModel, "EUR")
        assert balance is not None
        fills = list((await session.scalars(select(FillModel))).all())
        positions = list((await session.scalars(select(PositionModel))).all())
        open_reservations = int(
            await session.scalar(select(func.count()).select_from(CapitalReservationModel).where(CapitalReservationModel.status == "OPEN"))
            or 0
        )
    cash = Decimal("500")
    quantities: dict[str, Decimal] = {}
    for fill in fills:
        notional = fill.quantity * fill.price
        cash += (-notional - fill.fee) if fill.side == Side.BUY.value else (notional - fill.fee)
        if fill.position_id:
            signed_qty = fill.quantity if fill.side == Side.BUY.value else -fill.quantity
            quantities[fill.position_id] = quantities.get(fill.position_id, Decimal("0")) + signed_qty
    persisted = {position.position_id: position.quantity for position in positions}
    assert balance.available + balance.reserved == cash
    assert persisted == quantities
    return cash, quantities, len(fills), open_reservations


async def count_open_reservations(repo: PersistentTradingRepository) -> int:
    async with repo.session_factory() as session:
        reservations = list(
            (
                await session.scalars(
                    select(CapitalReservationModel).where(CapitalReservationModel.status == "OPEN")
                )
            ).all()
        )
        return len(reservations)


async def test_postgres_50_step_lifecycle_restart_replay_and_symbol_reuse(pg_repo: PersistentTradingRepository) -> None:
    repo = pg_repo
    await repo.initialize_portfolio(Decimal("500"))
    executed_steps = 0

    buy_1 = await repo.submit_order(PAIR, Side.BUY, OrderType.MARKET, Decimal("1"), Decimal("100"), book(Decimal("100")), "buy-1", fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    executed_steps += 1
    assert buy_1.status is OrderStatus.FILLED
    await repo.set_position_exit_plan(PAIR.symbol, Decimal("90"), [Decimal("110"), Decimal("120"), Decimal("130")], PAIR.quantity_step)
    executed_steps += 1
    first_position = (await repo.list_positions())[0]
    assert first_position.original_quantity == Decimal("1.000000000000")

    for key, qty, price in [("tp1", Decimal("0.3"), Decimal("110")), ("tp2", Decimal("0.4"), Decimal("120")), ("tp3", Decimal("0.3"), Decimal("130"))]:
        order = await repo.submit_order(PAIR, Side.SELL, OrderType.MARKET, qty, Decimal("0"), book(price), key, fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
        executed_steps += 1
        assert order.status is OrderStatus.FILLED
        duplicate = await repo.submit_order(PAIR, Side.SELL, OrderType.MARKET, qty, Decimal("0"), book(price), key, fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
        executed_steps += 1
        assert duplicate.order_id == order.order_id
        await repo.sync_exit_plan_from_fills(PAIR.symbol)
        executed_steps += 1

    closed = next(position for position in await repo.list_positions() if position.position_id == first_position.position_id)
    assert closed.quantity == Decimal("0E-12")
    assert closed.closed_at is not None

    restarted = PersistentTradingRepository(repo.session_factory)
    buy_2 = await restarted.submit_order(PAIR, Side.BUY, OrderType.MARKET, Decimal("1"), Decimal("80"), book(Decimal("80")), "buy-2", fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    executed_steps += 1
    assert buy_2.status is OrderStatus.FILLED
    await restarted.set_position_exit_plan(PAIR.symbol, Decimal("70"), [Decimal("85"), Decimal("90"), Decimal("95")], PAIR.quantity_step)
    executed_steps += 1
    second_open = next(position for position in await restarted.list_positions() if position.closed_at is None)
    assert second_open.position_id != first_position.position_id
    assert second_open.take_profit_targets[0] == Decimal("85.000000000000")

    for index in range(39):
        assert await restarted.verify_invariants(Decimal("500")) == []
        executed_steps += 1
        assert await restarted.unrealized_pnl({PAIR.symbol: Decimal("75")}) == Decimal("-5.000000000000")
        executed_steps += 1
        assert await count_open_reservations(restarted) == 0
        executed_steps += 1
        if executed_steps >= 50:
            break

    cash, quantities, fill_count, open_reservations = await ledger(restarted)
    assert executed_steps >= 50
    assert cash == Decimal("440.000000000000000000000000")
    assert quantities[second_open.position_id] == Decimal("1.000000000000")
    assert cash + (quantities[second_open.position_id] * Decimal("80")) == Decimal("520.000000000000000000000000")
    assert fill_count == 5
    assert open_reservations == 0


async def test_postgres_parallel_buy_reservations_cannot_make_negative_cash(pg_repo: PersistentTradingRepository) -> None:
    repo = pg_repo
    await repo.initialize_portfolio(Decimal("500"))

    async def buy(index: int) -> OrderStatus:
        order = await repo.submit_order(PAIR, Side.BUY, OrderType.MARKET, Decimal("1"), Decimal("100"), book(Decimal("100")), f"parallel-buy-{index}", fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
        return order.status

    statuses = await asyncio.gather(*(buy(index) for index in range(10)))

    assert statuses.count(OrderStatus.FILLED) == 5
    assert statuses.count(OrderStatus.REJECTED) == 5
    snapshot = await repo.snapshot()
    assert Decimal(snapshot["available_cash"]) == Decimal("0E-12")
    assert Decimal(snapshot["reserved_cash"]) == Decimal("0E-12")
    assert await repo.verify_invariants(Decimal("500")) == []


async def test_postgres_stop_and_target_race_cannot_oversell(pg_repo: PersistentTradingRepository) -> None:
    repo = pg_repo
    await repo.initialize_portfolio(Decimal("500"))
    await repo.submit_order(PAIR, Side.BUY, OrderType.MARKET, Decimal("1"), Decimal("100"), book(Decimal("100")), "race-buy", fee_bps=Decimal("0"), slippage_bps=Decimal("0"))

    async def sell(key: str) -> OrderStatus:
        order = await repo.submit_order(PAIR, Side.SELL, OrderType.MARKET, Decimal("1"), Decimal("0"), book(Decimal("105")), key, fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
        return order.status

    statuses = await asyncio.gather(sell("race-stop"), sell("race-target"))

    assert statuses.count(OrderStatus.FILLED) == 1
    assert statuses.count(OrderStatus.REJECTED) == 1
    assert (await repo.list_positions())[0].quantity == Decimal("0E-12")
    assert await repo.verify_invariants(Decimal("500")) == []


async def test_postgres_unfilled_buy_releases_pending_reservation(pg_repo: PersistentTradingRepository) -> None:
    repo = pg_repo
    await repo.initialize_portfolio(Decimal("500"))
    order = await repo.submit_order(PAIR, Side.BUY, OrderType.MARKET, Decimal("1"), Decimal("100"), book(Decimal("100"), ask_qty=Decimal("0")), "unfilled-buy", fee_bps=Decimal("0"), slippage_bps=Decimal("0"))

    assert order.status is OrderStatus.REJECTED
    assert await count_open_reservations(repo) == 0
    snapshot = await repo.snapshot()
    assert Decimal(snapshot["available_cash"]) == Decimal("500.000000000000")
    assert Decimal(snapshot["reserved_cash"]) == Decimal("0E-12")
