"""Pure Decimal postings, shared by transactional runtime and historical simulation."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from autotrader.execution.pricing import exact


@dataclass(frozen=True)
class ClosingPosting:
    released_basis: Decimal
    cash_credit: Decimal
    realized_pnl: Decimal
    remaining_quantity: Decimal
    remaining_basis: Decimal


def closing_posting(quantity: Decimal, basis: Decimal, filled: Decimal,
                    gross_notional: Decimal, fee: Decimal) -> ClosingPosting:
    if not all(v.is_finite() for v in (quantity, basis, filled, gross_notional, fee)):
        raise ValueError("non_finite_posting")
    if quantity <= 0 or not 0 < filled <= quantity or min(basis, gross_notional, fee) < 0:
        raise ValueError("invalid_closing_posting")
    released = basis if filled == quantity else exact(basis * filled / quantity)
    credit = gross_notional - fee
    return ClosingPosting(released, credit, credit - released, quantity - filled, basis - released)
