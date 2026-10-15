from __future__ import annotations

from decimal import Decimal

from autotrader.domain import (
    OrderBook,
    OrderBookLevel,
    OrderStatus,
    OrderType,
    Side,
    TradingPair,
    utc_now,
)
from autotrader.paper_broker import PaperBroker
from autotrader.portfolio import Portfolio
from autotrader.risk import RiskEngine, RiskLimits

PAIR = TradingPair("BTC-EUR", "BTC", "EUR", min_order_quote=Decimal("5"))


def book(price: Decimal = Decimal("50000"), ask_qty: Decimal = Decimal("1")) -> OrderBook:
    return OrderBook(
        PAIR.symbol,
        utc_now(),
        bids=(OrderBookLevel(price - Decimal("10"), Decimal("1")),),
        asks=(OrderBookLevel(price + Decimal("10"), ask_qty),),
        source="test",
    )


def test_risk_preserves_minimum_cash_reserve() -> None:
    portfolio = Portfolio(Decimal("500"))
    risk = RiskEngine(RiskLimits())
    evaluation = risk.evaluate_entry(
        portfolio,
        PAIR,
        Decimal("400"),
        Decimal("50000"),
        Decimal("49000"),
        entries_today=0,
    )
    assert not evaluation.accepted
    assert "position_size" in evaluation.reasons
    assert "reserve_preserved" in evaluation.reasons


def test_risk_rejects_stop_loss_at_or_above_long_entry() -> None:
    portfolio = Portfolio(Decimal("500"))
    risk = RiskEngine(RiskLimits())

    equal_stop = risk.evaluate_entry(
        portfolio,
        PAIR,
        Decimal("75"),
        Decimal("100"),
        Decimal("100"),
        entries_today=0,
    )
    above_stop = risk.evaluate_entry(
        portfolio,
        PAIR,
        Decimal("75"),
        Decimal("100"),
        Decimal("110"),
        entries_today=0,
    )

    assert not equal_stop.accepted
    assert not above_stop.accepted
    assert "long_stop_below_entry" in equal_stop.reasons
    assert "long_stop_below_entry" in above_stop.reasons


def test_risk_rejects_planned_loss_after_execution_cost_allowance() -> None:
    portfolio = Portfolio(Decimal("500"))
    risk = RiskEngine(RiskLimits(max_planned_loss_per_trade=Decimal("5"), planned_loss_cost_bps=Decimal("50")))
    evaluation = risk.evaluate_entry(
        portfolio,
        PAIR,
        Decimal("100"),
        Decimal("100"),
        Decimal("95"),
        entries_today=0,
    )

    assert not evaluation.accepted
    assert "planned_loss" in evaluation.reasons


def test_paper_buy_cannot_make_cash_negative() -> None:
    portfolio = Portfolio(Decimal("500"))
    broker = PaperBroker(portfolio, fee_bps=Decimal("10"), slippage_bps=Decimal("0"))
    order = broker.submit_order(PAIR, Side.BUY, OrderType.MARKET, Decimal("0.001"), Decimal("55"), book())
    assert order.status is OrderStatus.FILLED
    assert portfolio.cash >= 0
    assert portfolio.positions[PAIR.symbol].quantity == Decimal("0.001")


def test_partial_fill_status_and_no_live_flag() -> None:
    portfolio = Portfolio(Decimal("500"))
    broker = PaperBroker(portfolio, fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    order = broker.submit_order(PAIR, Side.BUY, OrderType.MARKET, Decimal("0.01"), Decimal("500"), book(ask_qty=Decimal("0.001")))
    assert order.status is OrderStatus.PARTIALLY_FILLED
    assert order.simulated is True
    assert next(iter(broker.fills.values())).simulated is True


def test_duplicate_fill_event_is_idempotent() -> None:
    portfolio = Portfolio(Decimal("500"))
    broker = PaperBroker(portfolio, fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    broker.submit_order(PAIR, Side.BUY, OrderType.MARKET, Decimal("0.001"), Decimal("55"), book())
    fill = next(iter(broker.fills.values()))
    quantity = portfolio.positions[PAIR.symbol].quantity
    portfolio.apply_fill(fill)
    assert portfolio.positions[PAIR.symbol].quantity == quantity
