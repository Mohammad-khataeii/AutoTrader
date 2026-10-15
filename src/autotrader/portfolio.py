from __future__ import annotations

from decimal import Decimal

from autotrader.domain import Balance, Fill, Position, Side, new_id, utc_now


class Portfolio:
    def __init__(self, initial_cash: Decimal, quote_asset: str = "EUR") -> None:
        self.quote_asset = quote_asset
        self.balances: dict[str, Balance] = {quote_asset: Balance(quote_asset, initial_cash)}
        self.positions: dict[str, Position] = {}
        self.processed_fill_ids: set[str] = set()

    @property
    def cash(self) -> Decimal:
        return self.balances[self.quote_asset].available

    @property
    def reserved_cash(self) -> Decimal:
        return self.balances[self.quote_asset].reserved

    @property
    def open_exposure(self) -> Decimal:
        return sum(
            (position.exposure for position in self.positions.values() if position.closed_at is None),
            Decimal("0"),
        )

    def reserve_cash(self, amount: Decimal) -> None:
        balance = self.balances[self.quote_asset]
        if amount < 0:
            raise ValueError("Cannot reserve a negative amount.")
        if balance.available < amount:
            raise ValueError("Insufficient available cash.")
        balance.available -= amount
        balance.reserved += amount

    def release_cash(self, amount: Decimal) -> None:
        balance = self.balances[self.quote_asset]
        released = min(amount, balance.reserved)
        balance.reserved -= released
        balance.available += released

    def apply_fill(self, fill: Fill) -> None:
        if fill.fill_id in self.processed_fill_ids:
            return
        self.processed_fill_ids.add(fill.fill_id)
        notional = fill.quantity * fill.price
        quote = self.balances[self.quote_asset]
        if fill.side is Side.BUY:
            quote.reserved = max(quote.reserved - notional - fill.fee, Decimal("0"))
            position = self.positions.get(fill.symbol)
            if position is None or position.closed_at is not None:
                self.positions[fill.symbol] = Position(new_id("pos"), fill.symbol, fill.quantity, fill.price, fill.timestamp)
            else:
                total_quantity = position.quantity + fill.quantity
                position.average_entry_price = ((position.quantity * position.average_entry_price) + notional) / total_quantity
                position.quantity = total_quantity
        else:
            position = self.positions.get(fill.symbol)
            if position is None or position.quantity < fill.quantity:
                raise ValueError("Cannot sell more than the available position quantity.")
            proceeds = notional - fill.fee
            quote.available += proceeds
            position.quantity -= fill.quantity
            position.realized_pnl += proceeds - (fill.quantity * position.average_entry_price)
            if position.quantity <= 0:
                position.quantity = Decimal("0")
                position.closed_at = utc_now()

    def snapshot(self) -> dict[str, str]:
        return {
            "available_cash": str(self.cash),
            "reserved_cash": str(self.reserved_cash),
            "open_exposure": str(self.open_exposure),
            "positions": str(len([p for p in self.positions.values() if p.closed_at is None])),
        }
