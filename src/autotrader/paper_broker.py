from __future__ import annotations

from decimal import Decimal

from autotrader.domain import (
    Fill,
    Order,
    OrderBook,
    OrderStatus,
    OrderType,
    Side,
    TradingPair,
    new_id,
    quantize_down,
    utc_now,
)
from autotrader.portfolio import Portfolio


class PaperBroker:
    """Simulated exchange. This class has no live-order dependency by design."""

    def __init__(self, portfolio: Portfolio, fee_bps: Decimal = Decimal("10"), slippage_bps: Decimal = Decimal("8")) -> None:
        self.portfolio = portfolio
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.orders: dict[str, Order] = {}
        self.fills: dict[str, Fill] = {}

    def submit_order(
        self,
        pair: TradingPair,
        side: Side,
        order_type: OrderType,
        quantity: Decimal,
        quote_amount: Decimal,
        order_book: OrderBook,
        limit_price: Decimal | None = None,
        decision_id: str | None = None,
    ) -> Order:
        order = Order(
            order_id=new_id("ord"),
            client_order_id=new_id("client"),
            symbol=pair.symbol,
            side=side,
            order_type=order_type,
            quantity=quantize_down(quantity, pair.quantity_step),
            quote_amount=quote_amount,
            limit_price=limit_price,
            status=OrderStatus.PENDING,
            created_at=utc_now(),
            decision_id=decision_id,
            simulated=True,
        )
        try:
            self._accept(order, pair, order_book)
        except ValueError as exc:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = str(exc)
        self.orders[order.order_id] = order
        return order

    def cancel(self, order_id: str) -> Order:
        order = self.orders[order_id]
        if order.status in {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}:
            return order
        order.status = OrderStatus.CANCELLED
        if order.side is Side.BUY:
            self.portfolio.release_cash(order.quote_amount)
        return order

    def _accept(self, order: Order, pair: TradingPair, order_book: OrderBook) -> None:
        if order.quantity <= 0:
            raise ValueError("Order quantity rounds to zero.")
        if order.side is Side.BUY:
            self.portfolio.reserve_cash(order.quote_amount)
        order.status = OrderStatus.ACCEPTED
        self._try_fill(order, pair, order_book)

    def _try_fill(self, order: Order, pair: TradingPair, order_book: OrderBook) -> None:
        book_side = order_book.asks if order.side is Side.BUY else order_book.bids
        if not book_side:
            return
        remaining = order.quantity - order.filled_quantity
        filled_qty = Decimal("0")
        cost = Decimal("0")
        for level in book_side:
            if remaining <= 0:
                break
            if order.order_type is OrderType.LIMIT and order.limit_price is not None:
                crosses = level.price <= order.limit_price if order.side is Side.BUY else level.price >= order.limit_price
                if not crosses:
                    continue
            qty = min(remaining, level.quantity)
            fill_price = self._with_slippage(level.price, order.side)
            filled_qty += qty
            cost += qty * fill_price
            remaining -= qty
        if filled_qty == 0:
            return
        avg_price = cost / filled_qty
        fee = cost * self.fee_bps / Decimal("10000")
        fill = Fill(new_id("fill"), order.order_id, order.symbol, order.side, filled_qty, avg_price, fee, utc_now(), simulated=True)
        self.fills[fill.fill_id] = fill
        self.portfolio.apply_fill(fill)
        order.filled_quantity += filled_qty
        order.average_fill_price = avg_price
        order.status = OrderStatus.FILLED if order.filled_quantity >= order.quantity else OrderStatus.PARTIALLY_FILLED
        if order.side is Side.BUY and order.status is OrderStatus.FILLED:
            unspent = max(order.quote_amount - cost - fee, Decimal("0"))
            self.portfolio.release_cash(unspent)

    def _with_slippage(self, price: Decimal, side: Side) -> Decimal:
        multiplier = Decimal("1") + (self.slippage_bps / Decimal("10000"))
        if side is Side.SELL:
            multiplier = Decimal("1") - (self.slippage_bps / Decimal("10000"))
        return price * multiplier

