"""Fixed versioned hypothesis and conservative candle-based margin model."""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Any

from autotrader.perpetuals.market import MINUTE, Bar, Instrument

D = Decimal
POLICY = "BTC_15M_BREAKOUT_ISOLATED_V1"
LEVERAGES = (1, 3, 10)
INITIAL = D("1000")
FEE = D(".0006")
SLIP = D(".0005")
MAINTENANCE = D(".005")
RISK = D(".005")
DRAWDOWN_LIMIT = D(".10")
SIGNAL_PERIOD = 15 * MINUTE
SIGNAL_MINUTES = 25 * 15
MAX_HOLD = 360 * MINUTE
State = dict[str, Any]


def initial_state() -> State:
    return {
        "policy": POLICY,
        "entries_enabled": False,
        "cursor": None,
        "mark": None,
        "pending": None,
        "accounts": [
            {"leverage": n, "cash": INITIAL, "peak": INITIAL, "max_drawdown": D(0),
             "realized": D(0), "closed": 0, "liquidations": 0, "halted": False, "position": None}
            for n in LEVERAGES
        ],
    }


def signal(bars: dict[int, Bar], close_at: int) -> tuple[int, Decimal, Decimal] | None:
    """Use only completed 15-minute trade candles available at the decision."""
    if close_at % SIGNAL_PERIOD:
        return None
    minute_rows = [bars.get(t) for t in range(close_at - SIGNAL_MINUTES * MINUTE, close_at, MINUTE)]
    if any(bar is None for bar in minute_rows):
        return None
    rows = [bar for bar in minute_rows if bar is not None]
    groups = [rows[i:i + 15] for i in range(0, len(rows), 15)]
    highs = [max(bar.high for bar in group) for group in groups]
    lows = [min(bar.low for bar in group) for group in groups]
    closes = [group[-1].close for group in groups]
    price = closes[-1]
    fast, slow = sum(closes[-8:]) / 8, sum(closes[-24:]) / 24
    side = (1 if price > max(highs[-21:-1]) and fast > slow else
            -1 if price < min(lows[-21:-1]) and fast < slow else 0)
    if not side:
        return None
    tr = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
          for i in range(len(closes) - 14, len(closes))]
    distance = max(D(".01"), D("2") * sum(tr) / 14 / price)
    return (side, distance, price) if distance <= D(".03") else None


def open_position(account: State, order: State, bar: Bar, mark: Bar, instrument: Instrument) -> State | None:
    side, stop_pct = order["side"], D(order["distance"])
    if (abs(bar.open / D(order["reference"]) - 1) > stop_pct / 2
            or abs(bar.open / mark.open - 1) > D(".0025")):
        return None
    cash, leverage = D(account["cash"]), account["leverage"]
    entry = bar.open * (1 + side * SLIP)
    budget = min(
        cash * RISK / (stop_pct + (2 + stop_pct) * (FEE + SLIP)),
        cash * D(".25") * leverage, cash * 2, D(2000),
    )
    qty = (budget / entry / instrument.step).to_integral_value(rounding=ROUND_DOWN) * instrument.step
    notional = qty * entry
    if qty < instrument.min_qty or notional < instrument.min_notional:
        return None
    margin, fee = notional / leverage, notional * FEE
    position = {
        "side": side, "qty": qty, "entry": entry, "margin": margin, "entry_fee": fee,
        "stop": entry * (1 - side * stop_pct), "target": entry * (1 + side * 2 * stop_pct),
        "opened_at": bar.start, "signal_at": order["signal_at"], "funding": D(0),
    }
    liquidation = liquidation_mark(position)
    stop = position["stop"]
    if margin + fee > cash or side * (stop - liquidation) <= 0 or side * (mark.open - stop) <= 0:
        return None
    account["cash"] = cash - margin - fee
    account["position"] = position
    return position


def liquidation_mark(p: State) -> Decimal:
    """Solve isolated equity = mark notional × (maintenance + exit fee reserve)."""
    side, qty = p["side"], D(p["qty"])
    collateral = (D(p["margin"]) + D(p["funding"])) / qty
    return max(D(0), (side * D(p["entry"]) - collateral) / (side - MAINTENANCE - FEE))


def position_value(p: State, mark: Decimal) -> Decimal:
    return max(D(0), D(p["margin"]) + D(p["funding"])
               + p["side"] * D(p["qty"]) * (mark - D(p["entry"])) - mark * D(p["qty"]) * FEE)


def account_equity(a: State, mark: Decimal | None) -> Decimal:
    return D(a["cash"]) + (position_value(a["position"], mark) if a["position"] and mark is not None else D(0))


def advance(state: State, trade: Bar, mark: Bar, rate: Decimal | None, instrument: Instrument,
            *, can_fill: bool) -> list[State]:
    """Advance one aligned closed minute. Funding and exits precede any fresh signal."""
    events: list[State] = []
    pending = state["pending"]
    fill_due = pending is not None and trade.start == pending["fill_at"]
    if pending and trade.start >= pending["fill_at"]:
        state["pending"] = None

    for account in state["accounts"]:
        def event(kind: str, **detail: Any) -> None:
            events.append({"kind": kind, "leverage": account["leverage"], "minute": trade.start, **detail})

        p = account["position"]
        if p and rate is not None:
            funding = -p["side"] * D(p["qty"]) * mark.open * rate
            p["funding"] = D(p["funding"]) + funding
            event("FUNDING", rate=rate, mark=mark.open, amount=funding, opened_at=p["opened_at"])
        if not p and fill_due and can_fill and state["entries_enabled"] and not account["halted"]:
            p = open_position(account, pending, trade, mark, instrument)
            if p:
                event("OPEN", **p)
            else:
                event("ENTRY_SKIPPED", reason="risk_size_minimum_or_price_gap", signal_at=pending["signal_at"])
        if p:
            side = p["side"]
            adverse_mark = mark.low if side == 1 else mark.high
            adverse_trade = trade.low if side == 1 else trade.high
            favorable_trade = trade.high if side == 1 else trade.low
            stop, target = D(p["stop"]), D(p["target"])
            liquidation = liquidation_mark(p)
            reason = None
            price = trade.close
            if side * (adverse_mark - liquidation) <= 0:
                reason, price = "LIQUIDATION", adverse_trade
            elif side * (adverse_mark - stop) <= 0:
                reason = "STOP"
                price = min(stop, adverse_trade) if side == 1 else max(stop, adverse_trade)
            elif side * (favorable_trade - target) > 0:
                reason, price = "TARGET", target
            elif trade.start + MINUTE - p["opened_at"] >= MAX_HOLD:
                reason = "TIME_EXIT"
            if reason:
                price *= 1 - side * SLIP
                qty, margin = D(p["qty"]), D(p["margin"])
                gross = side * qty * (price - D(p["entry"]))
                exit_fee = qty * price * FEE
                uncapped = margin + D(p["funding"]) + gross - exit_fee
                returned = D(0) if reason == "LIQUIDATION" else max(D(0), uncapped)
                net = returned - margin - D(p["entry_fee"])
                account["cash"] = D(account["cash"]) + returned
                account["realized"] = D(account["realized"]) + net
                account["closed"] += 1
                account["liquidations"] += int(reason == "LIQUIDATION")
                account["position"] = None
                event(reason, price=price, liquidation_mark=liquidation, adverse_mark=adverse_mark,
                      gross=gross, exit_fee=exit_fee, net=net, settlement_adjustment=returned - uncapped,
                      position=p)
        equity = account_equity(account, mark.close)
        account["peak"] = max(D(account["peak"]), equity)
        dd = 1 - equity / account["peak"]
        account["max_drawdown"] = max(D(account["max_drawdown"]), dd)
        if dd >= DRAWDOWN_LIMIT and not account["halted"]:
            account["halted"] = True
            event("RISK_HALT", drawdown=dd)

    state["mark"], state["cursor"] = mark.close, trade.start
    return events


def reconcile(state: State) -> None:
    """Check simulator accounting independently of the spot reconciliation."""
    if state["policy"] != POLICY or tuple(a["leverage"] for a in state["accounts"]) != LEVERAGES:
        raise ValueError("Unexpected perpetuals account identity")
    for a in state["accounts"]:
        position = a["position"]
        locked = D(position["margin"]) + D(position["entry_fee"]) if position else D(0)
        expected = INITIAL + D(a["realized"]) - locked
        if abs(D(a["cash"]) - expected) > D("1e-12") or D(a["cash"]) < 0:
            raise ValueError("Perpetuals cash and isolated collateral do not reconcile")
        if position and (position["side"] not in {-1, 1} or D(position["qty"]) <= 0
                         or position["opened_at"] > state["cursor"]):
            raise ValueError("Perpetuals open position does not reconcile")
