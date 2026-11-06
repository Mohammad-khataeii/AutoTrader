"""Explicit position actions and FIFO economics for broker-confirmed stock fills."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

D = Decimal
SHORT_PREFIX = "sws1-"


class Action(StrEnum):
    BUY_TO_OPEN_LONG = "BUY_TO_OPEN_LONG"
    SELL_TO_CLOSE_LONG = "SELL_TO_CLOSE_LONG"
    SELL_TO_OPEN_SHORT = "SELL_TO_OPEN_SHORT"
    BUY_TO_COVER_SHORT = "BUY_TO_COVER_SHORT"

    @property
    def broker_side(self):
        return self.value.split("_", 1)[0].lower()

    @property
    def opening(self):
        return self in {self.BUY_TO_OPEN_LONG, self.SELL_TO_OPEN_SHORT}

    @property
    def direction(self):
        return "SHORT" if self in {self.SELL_TO_OPEN_SHORT, self.BUY_TO_COVER_SHORT} else "LONG"


def number(value):
    try:
        n = D(str(value))
        if n.is_finite():
            return n
    except InvalidOperation:
        pass
    raise ValueError("invalid_position_number")


def intent_action(cid, side):
    if side not in {"BUY", "SELL", "buy", "sell"}:
        raise ValueError("invalid_intent_side")
    if cid.startswith(SHORT_PREFIX):
        return Action.SELL_TO_OPEN_SHORT if side.lower() == "sell" else Action.BUY_TO_COVER_SHORT
    if cid.startswith(("swp2-", "swx1-")):
        return Action.BUY_TO_OPEN_LONG if side.lower() == "buy" else Action.SELL_TO_CLOSE_LONG
    raise ValueError("unknown_intent_owner")


@dataclass(frozen=True)
class Position:
    direction: str
    signed_qty: D
    available: D | None
    gross: D
    entry: D

    @property
    def quantity(self):
        return abs(self.signed_qty)

    @property
    def proceeds(self):
        return self.entry * self.quantity if self.direction == "SHORT" else D(0)


def position(raw):
    side = raw.get("side")
    qty = number(raw.get("qty"))
    value = number(raw.get("market_value"))
    avg = number(raw.get("avg_entry_price"))
    available = None if raw.get("qty_available") is None else abs(number(raw["qty_available"]))
    if (
        side not in {"short", "long"}
        or raw.get("asset_class") != "us_equity"
        or not qty
        or not value
        or avg <= 0
        or (side == "long" and (qty <= 0 or value <= 0))
        or (available is not None and available > abs(qty))
    ):
        raise ValueError("invalid_position_direction_or_quantity")
    return Position(
        side.upper(), abs(qty) * (-1 if side == "short" else 1), available, abs(value), avg
    )


def fill_pnl(action, entry, exit_price, qty):
    return (exit_price - entry) * qty * (1 if action.direction == "LONG" else -1)


def fifo(fills):
    """One strategy/account at a time. Reject unowned closes and position flips."""
    realized = D(0)
    inventory = {}
    for action, symbol, qty, price in fills:
        if qty <= 0 or price <= 0:
            raise ValueError("invalid_fill_value")
        lots = inventory.setdefault(symbol, [])
        if lots and lots[0][0].direction != action.direction:
            raise ValueError("unreconciled_position_flip")
        if action.opening:
            lots.append([action, qty, price])
            continue
        while qty and lots:
            opened, size, basis = lots[0]
            used = min(qty, size)
            realized += fill_pnl(opened, basis, price, used)
            qty -= used
            if size == used:
                lots.pop(0)
            else:
                lots[0][1] -= used
        if qty:
            raise ValueError("unowned_close")
    return realized, inventory
