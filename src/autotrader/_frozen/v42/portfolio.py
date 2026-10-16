from __future__ import annotations

from decimal import Decimal

from autotrader.domain import Balance, Fill, Position


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
        """Compatibility check for an already persisted projection.

        Economic effects belong to PersistentTradingRepository, where database
        uniqueness and journal transactions establish idempotency across processes.
        """
        if fill.fill_id in self.processed_fill_ids:
            return
        raise ValueError("Unpersisted fills must go through the authoritative paper repository.")

    def snapshot(self) -> dict[str, str]:
        return {
            "available_cash": str(self.cash),
            "reserved_cash": str(self.reserved_cash),
            "open_exposure": str(self.open_exposure),
            "positions": str(len([p for p in self.positions.values() if p.closed_at is None])),
        }
