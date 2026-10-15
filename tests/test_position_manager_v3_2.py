from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from autotrader.domain import (
    DataQuality,
    Order,
    OrderBook,
    OrderBookLevel,
    OrderStatus,
    OrderType,
    Side,
    TradingPair,
    utc_now,
)
from autotrader.execution_gateway import ExecutionResult, PaperExecutionGateway
from autotrader.market_data.service import OrderBookMetrics, ValidatedMarket
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.position_manager import PositionManager
from autotrader.risk import RiskEngine, RiskLimits

PAIR = TradingPair(
    "BTC-EUR",
    "BTC",
    "EUR",
    price_step=Decimal("0.01"),
    quantity_step=Decimal("0.00000001"),
    min_order_quote=Decimal("5"),
    min_order_base=Decimal("0.00000001"),
)


class NoopMarketClient:
    async def close(self) -> None:
        return None


class FakeMarketData:
    def __init__(self, pair: TradingPair, order_book: OrderBook) -> None:
        self.pair = pair
        self.order_book = order_book

    async def resolve_pair(self, symbol: str) -> TradingPair | None:
        return self.pair if symbol == self.pair.symbol else None

    async def get_validated_market(self, pair: TradingPair) -> ValidatedMarket:
        return ValidatedMarket(
            pair=pair,
            candles=[],
            order_book=self.order_book,
            metrics=OrderBookMetrics(
                best_bid=self.order_book.best_bid or Decimal("0"),
                best_ask=self.order_book.best_ask or Decimal("0"),
                mid=self.order_book.mid or Decimal("0"),
                spread=self.order_book.spread or Decimal("0"),
                spread_bps=Decimal("1"),
                bid_depth=Decimal("10"),
                ask_depth=Decimal("10"),
                imbalance=Decimal("0"),
                liquidity_quote=Decimal("1000"),
                age_seconds=Decimal("0"),
                provider_latency_ms=Decimal("1"),
            ),
            quality=DataQuality.GOOD,
            rejected_reasons=[],
        )

    def validate_order_book(self, _order_book: OrderBook) -> tuple[list[str], OrderBookMetrics]:
        return [], OrderBookMetrics(
            best_bid=self.order_book.best_bid or Decimal("0"),
            best_ask=self.order_book.best_ask or Decimal("0"),
            mid=self.order_book.mid or Decimal("0"),
            spread=self.order_book.spread or Decimal("0"),
            spread_bps=Decimal("1"),
            bid_depth=Decimal("10"),
            ask_depth=Decimal("10"),
            imbalance=Decimal("0"),
            liquidity_quote=Decimal("1000"),
            age_seconds=Decimal("0"),
            provider_latency_ms=Decimal("1"),
        )


class RejectingGateway:
    def cycle_key(self, prefix: str, symbol: str) -> str:
        return f"{prefix}-{symbol}"

    async def execute_exit(
        self,
        _pair: TradingPair,
        _quantity: Decimal,
        _order_book: OrderBook,
        _idempotency_key: str,
        _reason: str,
    ) -> ExecutionResult:
        return ExecutionResult(
            accepted=False,
            reason="simulated_rejection",
            order=Order(
                order_id="ord_rejected",
                client_order_id="reject",
                symbol=PAIR.symbol,
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=_quantity,
                quote_amount=Decimal("0"),
                limit_price=None,
                status=OrderStatus.REJECTED,
                created_at=utc_now(),
            ),
        )


def book(symbol: str = "BTC-EUR", price: Decimal = Decimal("100"), qty: Decimal = Decimal("10")) -> OrderBook:
    return OrderBook(
        symbol=symbol,
        timestamp=utc_now(),
        bids=(OrderBookLevel(price - Decimal("0.05"), qty),),
        asks=(OrderBookLevel(price + Decimal("0.05"), qty),),
        source="fixture",
    )


async def make_repo(tmp_path: Any) -> PersistentTradingRepository:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'positions.db'}"

    class _Settings:
        pass

    settings = _Settings()
    settings.database_url = database_url
    engine = make_engine(settings)  # type: ignore[arg-type]
    await create_schema(engine)
    return PersistentTradingRepository(make_session_factory(engine))


async def seed_position(repo: PersistentTradingRepository) -> None:
    await repo.initialize_portfolio(Decimal("500"))
    await repo.submit_order(
        pair=PAIR,
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        quote_amount=Decimal("101"),
        order_book=book(price=Decimal("100")),
        idempotency_key="seed-buy",
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
    )
    await repo.set_position_exit_plan(
        PAIR.symbol,
        stop_loss=Decimal("90"),
        targets=[Decimal("101"), Decimal("200"), Decimal("300")],
        quantity_step=PAIR.quantity_step,
    )


@pytest.mark.asyncio
async def test_position_manager_monitors_open_position_absent_from_scanner_shortlist(tmp_path: Any) -> None:
    repo = await make_repo(tmp_path)
    await seed_position(repo)
    gateway = PaperExecutionGateway(
        repo,
        market_data=FakeMarketData(PAIR, book(price=Decimal("105"))),  # type: ignore[arg-type]
        risk_engine=RiskEngine(RiskLimits()),
        initial_cash=Decimal("500"),
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
    )
    manager = PositionManager(
        repository=repo,
        market_data=FakeMarketData(PAIR, book(price=Decimal("105"))),  # type: ignore[arg-type]
        execution_gateway=gateway,
    )

    actions = await manager.monitor_once([])

    positions = await repo.list_positions()
    assert actions[0].reason == "take_profit_target"
    assert positions[0].quantity == Decimal("0.700000000000")
    assert positions[0].take_profit_targets == [Decimal("200.000000000000"), Decimal("300.000000000000")]

    restarted_repo = await make_repo(tmp_path)
    restarted_gateway = PaperExecutionGateway(
        restarted_repo,
        market_data=FakeMarketData(PAIR, book(price=Decimal("105"))),  # type: ignore[arg-type]
        risk_engine=RiskEngine(RiskLimits()),
        initial_cash=Decimal("500"),
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
    )
    restarted_manager = PositionManager(
        repository=restarted_repo,
        market_data=FakeMarketData(PAIR, book(price=Decimal("105"))),  # type: ignore[arg-type]
        execution_gateway=restarted_gateway,
    )

    duplicate_actions = await restarted_manager.monitor_once([])

    assert duplicate_actions == []
    assert (await restarted_repo.list_positions())[0].quantity == Decimal("0.700000000000")


@pytest.mark.asyncio
async def test_position_manager_does_not_advance_target_without_fill(tmp_path: Any) -> None:
    repo = await make_repo(tmp_path)
    await seed_position(repo)
    manager = PositionManager(
        repository=repo,
        market_data=FakeMarketData(PAIR, book(price=Decimal("105"))),  # type: ignore[arg-type]
        execution_gateway=RejectingGateway(),  # type: ignore[arg-type]
    )

    actions = await manager.monitor_once([])

    positions = await repo.list_positions()
    assert actions[0].reason == "simulated_rejection"
    assert positions[0].quantity == Decimal("1.000000000000")
    assert positions[0].take_profit_targets[0] == Decimal("101.000000000000")
