from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from autotrader.ai import MockAIProvider
from autotrader.decision import DecisionEngine
from autotrader.domain import (
    Candle,
    DataQuality,
    DecisionAction,
    OrderBook,
    OrderBookLevel,
    OrderStatus,
    RuntimeHealth,
    StrategySignal,
    TradingPair,
    new_id,
    utc_now,
)
from autotrader.execution_gateway import PaperExecutionGateway
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.models import BalanceModel, PositionModel
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.risk import RiskEngine, RiskLimits
from autotrader.runtime import PaperTradingRuntime


class ForceBuyStrategy:
    def generate(self, *_args: Any, **_kwargs: Any) -> list[StrategySignal]:
        return [
            StrategySignal(
                signal_id=new_id("sig"),
                strategy_id="V2_FORCE_BUY",
                symbol="BTC-EUR",
                timestamp=utc_now(),
                score=Decimal("2.0"),
                data_quality=DataQuality.GOOD,
                evidence={"fixture": "deterministic opportunity"},
                entry_conditions=["fixture entry"],
                invalidation_conditions=["fixture invalidation"],
                estimated_cost_bps=Decimal("10"),
                explanation="Deterministic V2 acceptance-test signal.",
            )
        ]


class NoopMarketClient:
    async def close(self) -> None:
        return None


def candles(symbol: str = "BTC-EUR", close: Decimal = Decimal("100")) -> list[Candle]:
    start = utc_now()
    return [
        Candle(
            symbol=symbol,
            timestamp=start + timedelta(minutes=index),
            open=close - Decimal("1"),
            high=close + Decimal("2"),
            low=close - Decimal("2"),
            close=close + (Decimal(index) / Decimal("100")),
            volume=Decimal("100") + Decimal(index),
            source="fixture",
        )
        for index in range(240)
    ]


def book(symbol: str = "BTC-EUR", price: Decimal = Decimal("100"), qty: Decimal = Decimal("10")) -> OrderBook:
    return OrderBook(
        symbol=symbol,
        timestamp=utc_now(),
        bids=(OrderBookLevel(price - Decimal("0.05"), qty),),
        asks=(OrderBookLevel(price + Decimal("0.05"), qty),),
        source="fixture",
    )


async def make_repo(tmp_path: Any) -> PersistentTradingRepository:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    class _Settings:
        pass

    settings = _Settings()
    settings.database_url = database_url
    engine = make_engine(settings)  # type: ignore[arg-type]
    await create_schema(engine)
    return PersistentTradingRepository(make_session_factory(engine))


def runtime(repo: PersistentTradingRepository) -> PaperTradingRuntime:
    risk = RiskEngine(RiskLimits(max_planned_loss_per_trade=Decimal("10")))
    market_data = MarketDataService(NoopMarketClient())  # type: ignore[arg-type]
    gateway = PaperExecutionGateway(
        repo,
        market_data=market_data,
        risk_engine=risk,
        initial_cash=Decimal("500"),
        fee_bps=Decimal("10"),
        slippage_bps=Decimal("8"),
    )
    return PaperTradingRuntime(
        repository=repo,
        strategy_engine=ForceBuyStrategy(),  # type: ignore[arg-type]
        decision_engine=DecisionEngine(risk, default_quote_amount=Decimal("80")),
        risk_engine=risk,
        ai_provider=MockAIProvider(),
        initial_cash=Decimal("500"),
        execution_gateway=gateway,
    )


@pytest.mark.asyncio
async def test_v2_persistent_buy_restart_sell_and_reconcile(tmp_path: Any) -> None:
    pair = TradingPair("BTC-EUR", "BTC", "EUR")
    repo = await make_repo(tmp_path)
    first_runtime = runtime(repo)

    buy = await first_runtime.run_market_cycle(
        pair=pair,
        candles=candles(),
        order_book=book(),
        idempotency_key="fixture-buy-1",
    )

    assert buy.decision.action is DecisionAction.BUY
    assert buy.order is not None
    assert buy.order.status is OrderStatus.FILLED

    restarted_repo = await make_repo(tmp_path)
    restarted_runtime = runtime(restarted_repo)
    positions = await restarted_repo.list_positions()
    assert len([position for position in positions if position.closed_at is None]) == 1
    open_position = positions[0]

    sell = await restarted_runtime.exit_position(
        pair=pair,
        quantity=open_position.quantity,
        order_book=book(price=Decimal("106")),
        idempotency_key="fixture-sell-1",
    )

    assert sell.status is OrderStatus.FILLED
    final_snapshot = await restarted_repo.snapshot()
    assert final_snapshot["positions"] == "0"
    assert Decimal(final_snapshot["available_cash"]) > Decimal("500")
    assert await restarted_repo.verify_invariants(Decimal("500")) == []


@pytest.mark.asyncio
async def test_v2_duplicate_order_submission_is_idempotent(tmp_path: Any) -> None:
    pair = TradingPair("BTC-EUR", "BTC", "EUR")
    repo = await make_repo(tmp_path)
    service = runtime(repo)

    first = await service.run_market_cycle(pair, candles(), book(), idempotency_key="same-key")
    second = await service.run_market_cycle(pair, candles(), book(), idempotency_key="same-key")

    assert first.order is not None
    assert second.order is not None
    assert first.order.order_id == second.order.order_id
    orders = await repo.list_orders()
    assert len(orders) == 1
    assert await repo.verify_invariants(Decimal("500")) == []


@pytest.mark.asyncio
async def test_reconciliation_failure_persists_halt_and_blocks_restart_entries(tmp_path: Any) -> None:
    pair = TradingPair("BTC-EUR", "BTC", "EUR")
    repo = await make_repo(tmp_path)
    service = runtime(repo)
    await repo.initialize_portfolio(Decimal("500"))
    async with repo.session_factory() as session, session.begin():
        balance = await session.get(BalanceModel, "EUR")
        assert balance is not None
        balance.available += Decimal("1")

    result = await service.run_market_cycle(pair, candles(), book(), idempotency_key="halted-buy-1")

    assert result.decision.action is DecisionAction.BUY
    assert result.order is None
    assert await repo.get_runtime_health() is RuntimeHealth.RECONCILIATION_REQUIRED

    restarted_repo = await make_repo(tmp_path)
    restarted_service = runtime(restarted_repo)
    restarted = await restarted_service.run_market_cycle(pair, candles(), book(), idempotency_key="halted-buy-2")

    assert restarted.order is None
    assert await restarted_repo.get_runtime_health() is RuntimeHealth.RECONCILIATION_REQUIRED


@pytest.mark.asyncio
async def test_realized_pnl_since_uses_closing_fill_timestamp_not_open_date(tmp_path: Any) -> None:
    pair = TradingPair("BTC-EUR", "BTC", "EUR")
    repo = await make_repo(tmp_path)
    service = runtime(repo)
    buy = await service.run_market_cycle(pair, candles(), book(price=Decimal("100")), idempotency_key="old-buy")
    assert buy.order is not None
    position_id = (await repo.list_positions())[0].position_id
    async with repo.session_factory() as session, session.begin():
        position = await session.get(PositionModel, position_id)
        assert position is not None
        position.opened_at = datetime.now(tz=UTC) - timedelta(days=10)

    open_position = (await repo.list_positions())[0]
    sell = await service.exit_position(
        pair=pair,
        quantity=open_position.quantity,
        order_book=book(price=Decimal("90")),
        idempotency_key="today-loss",
    )
    assert sell.status is OrderStatus.FILLED

    today_start = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    assert await repo.realized_pnl_since(today_start) < Decimal("0")
