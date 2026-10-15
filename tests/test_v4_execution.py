from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from decimal import Decimal as D

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
from autotrader.execution.pricing import quote_execution, target_gross_floor
from autotrader.execution.quality import ExecutionQualityEngine
from autotrader.execution_gateway import PaperExecutionGateway
from autotrader.market_data.revolut import MarketDataError
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.models import (
    FillModel,
    OrderModel,
    SystemIncidentModel,
    SystemStateModel,
)
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.position_manager import PositionManager
from autotrader.risk import RiskEngine, RiskLimits

PAIR = TradingPair("BTC-EUR", "BTC", "EUR", min_order_quote=D(1))


def book(bid: str, ask: str, depth: str = "100") -> OrderBook:
    return OrderBook(PAIR.symbol, utc_now(), (OrderBookLevel(D(bid), D(depth)),),
                     (OrderBookLevel(D(ask), D(100)),), "v4-external-book-fixture")


class Boundary(MarketDataService):
    def __init__(self, observation: OrderBook) -> None:
        super().__init__(None)  # type: ignore[arg-type]
        self.observation = observation
        self.outage = False

    async def get_position_book(self, pair: TradingPair) -> OrderBook:
        if self.outage:
            raise MarketDataError("provider_outage")
        return self.observation


async def setup(repo: PersistentTradingRepository, observation: OrderBook, *,
                entry: str = "100", stop: str = "98", target: str = "110", quantity: str = "1",
                fee: str = "0", slip: str = "0") -> tuple[Boundary, PositionManager]:
    await repo.initialize_portfolio(D(500))
    opening = book(str(D(entry) - D("0.01")), entry)
    order = await repo.submit_order(PAIR, Side.BUY, OrderType.MARKET, D(quantity), D(100),
        opening, "v4-seed", fee_bps=D(0), slippage_bps=D(0), stop_loss=D(stop), targets=[D(target)])
    assert order.status is OrderStatus.FILLED
    boundary = Boundary(observation)
    gateway = PaperExecutionGateway(repo, market_data=boundary, risk_engine=RiskEngine(RiskLimits()),
        initial_cash=D(500), fee_bps=D(fee), slippage_bps=D(slip))
    return boundary, PositionManager(repository=repo, market_data=boundary, execution_gateway=gateway)


def test_vwap_costs_finite_depth_and_partial_floor() -> None:
    observation = OrderBook(PAIR.symbol, utc_now(),
        (OrderBookLevel(D(100), D(2)), OrderBookLevel(D(99), D(3))),
        (OrderBookLevel(D(101), D(2)), OrderBookLevel(D(102), D(3))), "fixture")
    sell = quote_execution(observation, Side.SELL, D(10), fee_bps=D(10), slippage_bps=D(10))
    assert sell.fillable_quantity == 5 and sell.unfilled_quantity == 5
    assert sell.vwap == D("99.3006")
    assert sell.net_cash_change == D("496.006497")
    assert sell.depth_impact_bps == 60
    limit = quote_execution(observation, Side.SELL, D(5), fee_bps=D(10), slippage_bps=D(10),
                            limit_price=target_gross_floor(D("99.5"), D(10)))
    assert limit.fillable_quantity == 2 and limit.net_unit_proceeds >= D("99.5")
    consumed = quote_execution(observation, Side.SELL, D(10), consumed={0: D(2), 1: D(3)})
    assert consumed.fillable_quantity == 0


def test_entry_quality_rejects_spread_and_cost_destroyed_reward() -> None:
    engine = ExecutionQualityEngine()
    wide = engine.evaluate(PAIR, book("95", "105"), D("0.9"), D(100), D(10), D(8), [D(106)])
    assert "spread_exceeds_entry_limit" in wide.rejection_reasons
    tight = engine.evaluate(PAIR, book("100", "100.01"), D("0.9"), D(100), D(25), D(25), [D("100.1")])
    assert "first_target_destroyed_by_execution_costs" in tight.rejection_reasons
    assert tight.immediate_round_trip_net < 0
    assert tight.payload()["probability_estimate"] is None


@pytest.mark.parametrize("bid,ask", [("97.9", "98.3"), ("95", "105"), ("94", "94.2")])
async def test_bid_stop_triggers_even_with_mid_above_stop_and_gap(pg_repo: PersistentTradingRepository, bid: str, ask: str) -> None:
    _, manager = await setup(pg_repo, book(bid, ask), slip="10")
    actions = await manager.monitor_once([PAIR])
    assert actions[0].reason == "protective_stop"
    fills = await pg_repo.list_fills()
    closing = next(f for f in fills if f["side"] == "SELL")
    assert D(closing["price"]) == D(bid) * D("0.999")
    async with pg_repo.session_factory() as session:
        row = await session.get(FillModel, closing["fill_id"])
        assert row and row.exit_target_id is None
    assert await pg_repo.verify_invariants(D(500)) == []


async def test_midpoint_cannot_trigger_target_and_net_costs_delay_it(pg_repo: PersistentTradingRepository) -> None:
    boundary, manager = await setup(pg_repo, book("100.9", "101.3"), target="101", fee="10", slip="10")
    assert await manager.monitor_once([PAIR]) == []
    boundary.observation = book("101.1", "101.3")
    assert await manager.monitor_once([PAIR]) == []
    boundary.observation = book("101.3", "101.5")
    assert (await manager.monitor_once([PAIR]))[0].reason == "take_profit_target"
    fills = await pg_repo.list_fills()
    closing = next(f for f in fills if f["side"] == "SELL")
    assert (D(closing["price"]) * D(closing["quantity"]) - D(closing["fee"])) / D(closing["quantity"]) >= 101
    assert await pg_repo.verify_invariants(D(500)) == []


async def test_same_snapshot_depth_shared_across_intents_and_repository_restart(pg_repo: PersistentTradingRepository) -> None:
    observation = book("9.7", "9.9", "3")
    _, manager = await setup(pg_repo, observation, entry="10", stop="9.8", target="11", quantity="10")
    assert (await manager.monitor_once([PAIR]))[0].order.filled_quantity == 3  # type: ignore[union-attr]
    restarted = PersistentTradingRepository(pg_repo.session_factory)
    position = (await restarted.list_positions())[0]
    async def retry(key: str):
        return await restarted.submit_order(PAIR, Side.SELL, OrderType.MARKET, D(7), D(0), observation,
            key, position_id=position.position_id, exit_reason="STOP", fee_bps=D(0), slippage_bps=D(0))
    orders = await asyncio.gather(retry("new-intent-a"), retry("new-intent-b"))
    assert all(order.filled_quantity == 0 for order in orders)
    assert (await restarted.list_positions())[0].quantity == 7
    assert await restarted.verify_invariants(D(500)) == []


async def test_stale_protection_durable_critical_watch_then_fresh_exit(pg_repo: PersistentTradingRepository) -> None:
    observation = book("97.9", "98.3")
    stale = OrderBook(observation.symbol, utc_now() - timedelta(seconds=120), observation.bids, observation.asks, observation.source)
    boundary, manager = await setup(pg_repo, stale)
    for _ in range(2):
        assert "stale_or_future_order_book" in (await manager.monitor_once([PAIR]))[0].reason
    async with pg_repo.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(FillModel)) == 1
        watch = await session.scalar(select(SystemStateModel).where(SystemStateModel.state == "WAITING_FOR_DATA"))
        assert watch and json.loads(watch.payload_json)["protective_stop"] == "98.000000000000"
        assert await session.scalar(select(func.count()).select_from(SystemIncidentModel).where(SystemIncidentModel.severity == "CRITICAL")) == 1
    boundary.observation = book("97.9", "98.3")
    assert (await manager.monitor_once([PAIR]))[0].reason == "protective_stop"
    assert (await pg_repo.list_positions())[0].quantity == 0
    assert await pg_repo.verify_invariants(D(500)) == []


async def test_repository_enforces_target_floor_even_for_direct_market_caller(pg_repo: PersistentTradingRepository) -> None:
    await setup(pg_repo, book("110", "110.2"))
    position = (await pg_repo.list_positions())[0]
    target_id = position.target_ids[0]
    order = await pg_repo.submit_order(PAIR, Side.SELL, OrderType.MARKET, D(1), D(0), book("109.9", "110.3"),
        "direct-target", position_id=position.position_id, exit_target_id=target_id, exit_reason="TAKE_PROFIT")
    assert order.status is OrderStatus.CANCELLED and order.filled_quantity == 0
    async with pg_repo.session_factory() as session:
        row = await session.get(OrderModel, order.order_id)
        assert row and row.order_type == "LIMIT" and "execution_quality" in json.loads(row.execution_json)
    assert (await pg_repo.list_targets())[0]["filled_quantity"] == "0E-12"
    assert await pg_repo.verify_invariants(D(500)) == []
