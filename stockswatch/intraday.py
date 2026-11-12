"""Independent deterministic intraday decisions, sharing only Alpaca paper authority."""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from . import alpaca_paper as paper
from . import intraday_store as journal
from . import shorts
from .direction import SHORT_PREFIX, Action, position
from .intraday_market import FEEDS, MINUTE, IntradayData, ObservationError, observe, positive
from .intraday_policy import (
    ORDER_PREFIX,
    STRATEGY,
    TRADABLE_PHASES,
    order_gate,
    phase_at,
    previous_regular_day,
    short_gate,
)
from .sessions import instant
from .storage import connect, one, rows

D = Decimal
from .universe import BENCHMARKS, NEW, REGISTRY

MAX_OBSERVATION_AGE = timedelta(seconds=12)


def decide(observations):
    """Rank independently of broker state. Only entitled SIP can propose orders."""
    by_symbol = {r["symbol"]: r for r in observations}
    peers = [by_symbol.get(s, {}) for s in sorted(BENCHMARKS)]
    macro = "UNKNOWN"
    if all(r.get("valid") for r in peers):
        macro = (
            "RISK_OFF"
            if all(D(r["momentum"]) < D("-.0015") for r in peers)
            else "MIXED_OR_SUPPORTIVE"
        )
    long_floor = D(os.getenv("STOCKSWATCH_INTRADAY_LONG_MIN_EDGE_BPS", "0"))
    if not long_floor.is_finite() or not 0 <= long_floor <= 150:
        raise ValueError("intraday_long_edge_threshold_outside_reviewed_range")
    for row in observations:
        if not row["valid"]:
            continue
        symbol = row["symbol"]
        gap, move, turnover, cost = (
            D(row[k]) for k in ("gap", "momentum", "turnover_3m", "cost_bps")
        )
        catalyst = row.get("catalyst")
        # A filing adds provenance and a small ranking tie-break, never overrides risk.
        setup = (
            gap >= D(".003")
            and move >= D(".0012")
            and row["higher_closes"] >= 3
            and turnover >= 250_000
            and (gap + move) * 10000 >= 2 * cost
        )
        row.update(
            setup=setup,
            score=str((gap + move) * 10000 - cost + D(bool(catalyst))),
            stressed_cost_bps=str(cost + D(20)),
            market_risk=macro,
        )
        if symbol in BENCHMARKS:
            reason = "benchmark_observation"
        elif row.get("enabled") is False:
            reason = "intraday_symbol_disabled"
        elif row["session"] == "OVERNIGHT":
            reason = "overnight_monitor_only"
        elif row["feed"] != "sip":
            reason = (
                "iex_single_venue_observation_only"
                if row["feed"] == "iex"
                else "feed_observation_only"
            )
        elif macro != "MIXED_OR_SUPPORTIVE":
            reason = "intraday_benchmark_risk_off_or_unknown"
        elif not setup:
            reason = "intraday_momentum_persistence_or_cost_gate"
        elif (gap + move) * 10000 < cost + D(20) + long_floor:
            reason = "intraday_adverse_cost_gate"
        else:
            reason = "intraday_entry_candidate"
            row["candidate"] = True
        row["reason"] = reason
    eligible = sorted(
        (r for r in observations if r.get("candidate")), key=lambda r: (-D(r["score"]), r["symbol"])
    )
    for i, row in enumerate(eligible, 1):
        row["rank"] = i
    return macro, eligible


def client_id(account_id, phase, symbol, side, now):
    # One buy intent per trade date and symbol. A sell may re-evaluate later
    # after a confirmed terminal order, with available inventory checked again.
    key = phase.day if side == "buy" else now.replace(second=0, microsecond=0).isoformat()
    return (
        ORDER_PREFIX
        + hashlib.sha256(f"{STRATEGY}|{account_id}|{symbol}|{side}|{key}".encode()).hexdigest()[:40]
    )


def _owned_entry(symbol, account_id):
    return one(
        """SELECT * FROM sw_alpaca_intents WHERE symbol=? AND account_id=?
        AND client_id LIKE ? AND side='BUY' AND broker_order_id IS NOT NULL
        ORDER BY created_at DESC,client_id DESC LIMIT 1""",
        (symbol, account_id, ORDER_PREFIX + "%"),
    )


def _store_fills(account_id, fills):
    linked = {
        o["broker_order_id"]: o
        for o in rows(
            """SELECT client_id,broker_order_id,symbol,
        side,created_at,detail_json FROM sw_alpaca_intents WHERE account_id=? AND (client_id LIKE ? OR client_id LIKE ?)
        AND broker_order_id IS NOT NULL""",
            (account_id, ORDER_PREFIX + "%", SHORT_PREFIX + "%"),
        )
    }
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        for f in fills:
            order = linked.get(f.get("order_id"))
            if not order:
                continue
            try:
                at = instant(f["transaction_time"])
                if (
                    f["symbol"] != order["symbol"]
                    or f["side"] != order["side"].lower()
                    or not isinstance(f["id"], str)
                    or not f["id"]
                    or at < instant(order["created_at"])
                ):
                    raise ValueError
                values = (
                    f["id"],
                    order["client_id"],
                    f["symbol"],
                    at.isoformat(),
                    f["side"],
                    str(positive(f["qty"])),
                    str(positive(f["price"])),
                )
            except (KeyError, ValueError, TypeError, ObservationError):
                raise paper.PaperError("intraday_broker_fill_identity_unverified") from None
            existing = c.execute(
                "SELECT * FROM sw_intraday_fills WHERE id=?", (values[0],)
            ).fetchone()
            if existing and tuple(existing) != values:
                raise paper.PaperError("intraday_broker_fill_revision_unverified")
            c.execute("INSERT OR IGNORE INTO sw_intraday_fills VALUES(?,?,?,?,?,?,?)", values)
            for component in ("fee", "commission"):
                if f.get(component) is None:
                    continue
                cost = paper.money(f[component])
                existing_cost = c.execute(
                    """SELECT usd FROM sw_intraday_fill_costs
                    WHERE fill_id=? AND component=?""",
                    (f["id"], component),
                ).fetchone()
                if cost < 0 or (existing_cost and D(existing_cost["usd"]) != cost):
                    raise paper.PaperError("intraday_broker_fill_cost_unverified")
                c.execute(
                    "INSERT OR IGNORE INTO sw_intraday_fill_costs VALUES(?,?,?)",
                    (f["id"], component, str(cost)),
                )
        c.commit()


def _snapshot(client):
    snapshot = client.snapshot()
    account = snapshot["account"]
    paper._linked_account(account["id"])
    active = snapshot["open_orders"]
    if (
        snapshot["warnings"].get("open_orders")
        or snapshot["fills"] is None
        or any(
            not o.get("id") or not o.get("symbol") or not o.get("client_order_id") for o in active
        )
        or len({o["id"] for o in active}) != len(active)
        or len({o["client_order_id"] for o in active}) != len(active)
    ):
        raise paper.PaperError("intraday_broker_snapshot_incomplete")
    positions = snapshot["positions"]
    if any(not p.get("symbol") or not p.get("asset_id") for p in positions) or len(
        {p["symbol"] for p in positions}
    ) != len(positions):
        raise paper.PaperError("intraday_broker_snapshot_incomplete")
    if paper._reconcile(client, account["id"], active):
        raise paper.PaperError("intraday_uncertain_broker_intent")
    if any(not isinstance(f.get("id"), str) or not f["id"] for f in snapshot["fills"]):
        raise paper.PaperError("intraday_broker_snapshot_incomplete")
    _store_fills(account["id"], snapshot["fills"])
    if (
        account.get("status") != "ACTIVE"
        or account.get("trading_blocked") is not False
        or account.get("account_blocked") is not False
        or account.get("trade_suspended_by_user") is True
    ):
        raise paper.PaperError("intraday_account_blocked")
    return snapshot


def _daily_loss(account, phase, now):
    equity, last = (paper.money(account.get(k)) for k in ("equity", "last_equity"))
    if min(equity, last) <= 0:
        raise paper.PaperError("intraday_equity_unavailable")
    return journal.daily_loss_paused(account["id"], phase.day, equity <= last * D(".98"), now)


def _budget(snapshot, symbol, phase, sectors, now):
    account = snapshot["account"]
    account_id = account["id"]
    eq = paper.money(account.get("equity"))
    if _daily_loss(account, phase, now):
        raise paper.PaperError("intraday_daily_loss_pause")
    trades = one(
        """SELECT COUNT(*) AS n FROM sw_alpaca_intents WHERE account_id=?
        AND signal_day=? AND side='BUY' AND client_id LIKE ?""",
        (account_id, phase.day, ORDER_PREFIX + "%"),
    )
    if trades["n"] >= 2:
        raise paper.PaperError("intraday_daily_entry_cap")
    known = {p["symbol"]: p for p in snapshot["positions"]}
    ids = {
        i["broker_order_id"]: i["client_id"]
        for i in rows(
            """
        SELECT broker_order_id,client_id FROM sw_alpaca_intents WHERE account_id=? AND state='ACKNOWLEDGED'
    """,
            (account_id,),
        )
    }
    active = [{**o, "owned_intent": o["id"] in ids} for o in snapshot["open_orders"]]
    gross = sum(
        paper.money(p["market_value"])
        for p in known.values()
        if _owned_entry(p["symbol"], account_id)
    )
    reserved = sum(
        paper.money(o["limit_price"]) * (paper.money(o["qty"]) - paper.money(o["filled_qty"]))
        for o in active
        if ids.get(o["id"], "").startswith(ORDER_PREFIX) and o["side"] == "buy"
    )
    return min(
        paper._entry_budget(snapshot, sectors, sectors[symbol], active, known),
        eq * D(".05"),
        eq * D(".15") - gross - reserved,
        eq * D(".01") / D(".05"),
    )


def _verify_clock(client, phase):
    clock = client.clock()
    now = client.now()
    try:
        stamp = instant(clock["timestamp"])
        if (
            not timedelta(0) <= now - stamp <= timedelta(seconds=8)
            or not phase.contains(stamp)
            or clock.get("is_open") is not (phase.name == "CORE")
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise paper.PaperError("intraday_broker_clock_stale_or_phase_mismatch") from None


def _asset(client, symbol):
    asset = client.asset(symbol)
    if (
        not isinstance(asset, dict)
        or asset.get("symbol") != symbol
        or asset.get("class") != "us_equity"
        or asset.get("status") != "active"
        or asset.get("tradable") is not True
        or not asset.get("id")
        or asset.get("halted") is True
        or asset.get("trading_halted") is True
        or asset.get("exchange") in {"OTC", "CRYPTO"}
    ):
        raise paper.PaperError("intraday_asset_halted_or_unverified")
    if symbol in NEW and not shorts.backfill.asset_evidence(symbol, asset)["verified"]:
        raise paper.PaperError("intraday_new_listing_unverified")
    return asset


def _exit_trigger(row, pos, entry, now):
    bid = positive(row["quote"]["bp"])
    avg = paper.money(pos["avg_entry_price"])
    if avg <= 0:
        raise paper.PaperError("intraday_cost_basis_unavailable")
    if bid <= avg * D(".985"):
        return "intraday_software_stop"
    if bid >= avg * D("1.025"):
        return "intraday_profit_target"
    if now - instant(entry["created_at"]) >= timedelta(minutes=90):
        return "intraday_time_exit"
    if row["market_risk"] == "RISK_OFF" and D(row["momentum"]) < 0:
        return "intraday_benchmark_exit"
    return None


def _eligible_order(client, snapshot, row, phase, side, now, asset, sectors):
    symbol = row["symbol"]
    account_id = snapshot["account"]["id"]
    if any(o["symbol"] == symbol for o in snapshot["open_orders"]):
        raise paper.PaperError("intraday_symbol_open_order_conflict")
    pos = next((p for p in snapshot["positions"] if p["symbol"] == symbol), None)
    quote = row["quote"]
    if side == "buy":
        if pos or one(
            """SELECT 1 FROM sw_alpaca_intents WHERE account_id=? AND symbol=?
                AND (signal_day=? OR substr(created_at,1,10)=?) LIMIT 1""",
            (account_id, symbol, phase.day, phase.day),
        ):
            raise paper.PaperError("intraday_position_or_same_day_intent_conflict")
        limit = (positive(quote["ap"]) * D("1.001")).quantize(D(".01"), rounding=ROUND_UP)
        budget = _budget(snapshot, symbol, phase, sectors, now)
        quantity = min(int(max(D(0), budget) / limit), int(positive(quote["as"]) / 4))
    else:
        entry = _owned_entry(symbol, account_id)
        if (
            not pos
            or not entry
            or pos.get("asset_id") != asset["id"]
            or pos.get("side") != "long"
            or pos.get("asset_class") != "us_equity"
            or not paper._position_owned(pos, snapshot["fills"], account_id, prefix=ORDER_PREFIX)
            or not _exit_trigger(row, pos, entry, now)
        ):
            raise paper.PaperError("intraday_exit_ownership_or_trigger_unverified")
        limit = (positive(quote["bp"]) * D(".999")).quantize(D(".01"), rounding=ROUND_DOWN)
        quantity = min(int(paper.money(pos.get("qty_available"))), int(positive(quote["bs"]) / 4))
    if quantity <= 0 or limit < 1:
        raise paper.PaperError("intraday_budget_or_depth_cap")
    return {
        "symbol": symbol,
        "side": side,
        "qty": str(quantity),
        "limit_price": str(limit),
        "type": "limit",
        "time_in_force": "day",
        "extended_hours": phase.name != "CORE",
        "client_order_id": client_id(account_id, phase, symbol, side, now),
    }


def _submit(client, data, snapshot, row, raw_bars, phase, side, reason, sectors, action=None):
    symbol = row["symbol"]
    account_id = snapshot["account"]["id"]
    now = client.now()
    if phase_at(now) != phase or not phase.start + timedelta(
        seconds=15
    ) <= now < phase.end - timedelta(seconds=45):
        raise paper.PaperError("intraday_session_transition")
    start = previous_regular_day(phase)
    if action == Action.BUY_TO_COVER_SHORT:
        raw = next((p for p in snapshot["positions"] if p["symbol"] == symbol), None)
        entry = shorts.owned(raw, snapshot["fills"], account_id) if raw else None
        if not entry:
            raise paper.PaperError("short_cover_ownership_unverified")
        start = min(start, entry["signal_day"])
    elif action is None and side == "sell":
        start = min(start, _owned_entry(symbol, account_id)["signal_day"])
    events = data.corporate_actions(symbol, start, phase.day)
    if events:
        row["corporate_actions"] = events
        raise paper.PaperError("intraday_corporate_action_review_required")
    if action == Action.SELL_TO_OPEN_SHORT:
        if phase.name != "CORE" or short_gate():
            raise paper.PaperError("short_entry_disabled_or_phase")
        if not shorts.backfill.short_history_ready(symbol, now):
            raise paper.PaperError("short_history_or_listing_unverified")
        row["short_price_test"] = shorts.restriction_check(data, symbol, phase, now)
    # Fresh broker state, quote and clock immediately before persisting the intent.
    fresh = _snapshot(client)
    if fresh["account"]["id"] != account_id:
        raise paper.PaperError("intraday_account_changed")
    asset = _asset(client, symbol)
    asset_received = client.now()
    if action:
        row.update(borrow=shorts.borrow(asset), borrow_verified_at=asset_received.isoformat())
    raw = data.snapshots([symbol], "sip").get(symbol)
    now = client.now()
    refreshed = observe(symbol, raw, raw_bars, row["previous_regular_close"], phase, "sip", now)
    if action == Action.BUY_TO_COVER_SHORT:
        valid = refreshed.get("quote_ready")
    else:
        valid = (
            refreshed["valid"] and refreshed["latest_completed_at"] == row["latest_completed_at"]
        )
    if not valid:
        raise paper.PaperError("intraday_dispatch_quote_or_context_stale")
    key = "ap" if side == "buy" else "bp"
    if abs(positive(refreshed["quote"][key]) / positive(row["quote"][key]) - 1) > (
        D(".005") if action == Action.BUY_TO_COVER_SHORT else D(".0015")
    ):
        raise paper.PaperError("intraday_price_moved_recheck")
    refreshed["market_risk"] = row.get("market_risk")
    details = {"session": phase.name}
    if action:
        refreshed["short_price_test"] = row.get("short_price_test")
        if action.opening and _daily_loss(fresh["account"], phase, now):
            raise paper.PaperError("short_daily_loss_pause")
        payload, risk = shorts.payload(
            client, fresh, refreshed, phase, action, now, asset, sectors, reason
        )
        details.update(action=action.value, risk=risk)
    else:
        payload = _eligible_order(client, fresh, refreshed, phase, side, now, asset, sectors)
    cid = payload["client_order_id"]
    if one("SELECT 1 FROM sw_alpaca_intents WHERE client_id=?", (cid,)):
        raise paper.PaperError("intraday_existing_intent")
    if client.by_client_id(cid):
        with connect() as c:
            c.execute("PRAGMA synchronous=FULL")
            paper._intent(
                c,
                cid,
                account_id,
                phase.day,
                symbol,
                side.upper(),
                payload["qty"],
                "broker_order_without_local_intent",
                {**payload, **details},
            )
        paper._state(cid, "UNKNOWN", reason="broker_order_without_local_intent")
        raise paper.PaperError("intraday_broker_order_without_local_intent")
    _verify_clock(client, phase)
    with paper._admission:
        now = client.now()
        if (one("SELECT paused FROM sw_alpaca_state WHERE id=1") or {}).get("paused", 1):
            raise paper.PaperError("intraday_paper_kill_switch")
        if (
            phase_at(now) != phase
            or (
                action == Action.SELL_TO_OPEN_SHORT and now - asset_received > timedelta(seconds=15)
            )
            or not timedelta(0) <= now - instant(refreshed["quote"]["t"]) <= MAX_OBSERVATION_AGE
        ):
            raise paper.PaperError("intraday_dispatch_quote_or_context_stale")
        with connect() as c:
            c.execute("PRAGMA synchronous=FULL")
            if not paper._intent(
                c,
                cid,
                account_id,
                phase.day,
                symbol,
                side.upper(),
                payload["qty"],
                reason,
                {**payload, **details},
            ):
                raise paper.PaperError("intraday_existing_intent")
        intent = one("SELECT * FROM sw_alpaca_intents WHERE client_id=?", (cid,))
        try:
            order = paper._validated_order(client.submit(payload, phase=phase), intent)
        except (paper.PaperRejection, paper.PaperLocalRefusal) as exc:
            paper._state(cid, "REJECTED", reason=str(exc))
            row.update(reason=str(exc), client_id=cid, risk_decision="BROKER_REJECTED")
            return "BROKER_REJECTED"
        except paper.PaperError as exc:
            paper._state(cid, "UNKNOWN", reason=str(exc))
            row.update(reason=str(exc), client_id=cid, risk_decision="BROKER_ORDER_UNCERTAIN")
            return "BROKER_ORDER_UNCERTAIN"
        status = order["status"]
        paper._state(cid, "TERMINAL" if status in paper.TERMINAL else "ACKNOWLEDGED", order, reason)
        row.update(
            action=(("SHORT" if action.opening else "COVER_SHORT") if action else side.upper()),
            reason=reason,
            client_id=cid,
            risk_decision=f"broker_{status}",
        )
        return f"BROKER_{status.upper()}"


def _cancel_resting_short(client, snapshot, phase):
    now = client.now()
    for order in snapshot["open_orders"]:
        cid = order["client_order_id"]
        if not cid.startswith(SHORT_PREFIX) or order.get("side") != "sell":
            continue
        intent = one(
            "SELECT * FROM sw_alpaca_intents WHERE client_id=? AND account_id=?",
            (cid, snapshot["account"]["id"]),
        )
        if not intent:
            raise paper.PaperError("short_open_order_without_local_intent")
        detail = json.loads(intent["detail_json"])
        if detail.get("cancel_requested_at"):
            return "SHORT_CANCEL_AWAITING_BROKER_TERMINAL"
        if now < phase.end - shorts.FLATTEN_BEFORE and now - instant(
            intent["created_at"]
        ) < timedelta(seconds=90):
            continue
        with paper._admission, connect() as c:
            if (one("SELECT paused FROM sw_alpaca_state WHERE id=1") or {}).get("paused", 1):
                return "intraday_paper_kill_switch"
            c.execute("PRAGMA synchronous=FULL")
            c.execute(
                "UPDATE sw_alpaca_intents SET detail_json=json_set(detail_json,'$.cancel_requested_at',?) WHERE client_id=?",
                (now.isoformat(), cid),
            )
            try:
                client.cancel_short_entry(order, intent)
            except paper.PaperError:
                return "SHORT_CANCEL_UNCERTAIN_AWAITING_BROKER_TERMINAL"
        return "SHORT_CANCEL_REQUESTED"
    return None


def execute(client, data, report, candidates, all_bars, phase, sectors):
    with paper.broker_cycle_lock:
        return _execute(client, data, report, candidates, all_bars, phase, sectors)


def _execute(client, data, report, candidates, all_bars, phase, sectors):
    snapshot = _snapshot(client)
    account_id = snapshot["account"]["id"]
    owned = {
        p["symbol"]: p
        for p in snapshot["positions"]
        if paper._position_owned(p, snapshot["fills"], account_id, prefix=ORDER_PREFIX)
    }
    ownership = {
        p["symbol"]: (
            "INTRADAY"
            if p["symbol"] in owned
            else "EOD"
            if paper._position_owned(p, snapshot["fills"], account_id)
            else "EXTERNAL_OR_UNVERIFIED"
        )
        for p in snapshot["positions"]
    }
    short_positions = {}
    account_short_gross = D(0)
    for p in snapshot["positions"]:
        if p.get("side") == "short":
            account_short_gross += position(p).gross
            if entry := shorts.owned(p, snapshot["fills"], account_id):
                short_positions[p["symbol"]] = (p, entry)
                ownership[p["symbol"]] = "SHORT"
    for row in report["rows"]:
        row["position_owner"] = ownership.get(row["symbol"])
    short_pnl = journal.pnl(account_id, SHORT_PREFIX)
    if (
        short_positions
        and set(short_positions) == set(short_pnl.get("open_quantity", {}))
        and all(
            position(p).quantity == D(short_pnl["open_quantity"][s])
            for s, (p, _) in short_positions.items()
        )
    ):
        short_pnl["unrealized_usd"] = str(
            D(short_pnl["open_cost_basis_usd"])
            - sum(position(p).gross for p, _ in short_positions.values())
        )
    report["short_pnl"] = short_pnl
    report["short_positions"] = [
        {
            "symbol": s,
            "direction": "SHORT",
            "quantity": str(position(p).quantity),
            "entry_price": str(position(p).entry),
            "gross": str(position(p).gross),
            "broker_unrealized": p.get("unrealized_pl"),
        }
        for s, (p, _) in short_positions.items()
    ]
    pnl = journal.pnl(account_id)
    quantities = pnl.get("open_quantity", {})
    if (
        quantities
        and set(quantities) == set(owned)
        and all(D(qty) == paper.money(owned[symbol]["qty"]) for symbol, qty in quantities.items())
    ):
        market_values = [paper.money(p.get("market_value"), D(0)) for p in owned.values()]
        if min(market_values) > 0:
            pnl["unrealized_usd"] = str(sum(market_values) - D(pnl["open_cost_basis_usd"]))
    report["pnl"] = pnl
    report["daily_loss_paused"] = _daily_loss(snapshot["account"], phase, client.now())
    gate = order_gate()
    if not paper.orders_enabled() or gate:
        return gate or "alpaca_paper_orders_disabled"
    if (one("SELECT paused FROM sw_alpaca_state WHERE id=1") or {}).get("paused", 1):
        return "intraday_paper_kill_switch"
    if phase.name not in TRADABLE_PHASES:
        return "intraday_session_observation_only"
    if report["feed"] != "sip":
        return "intraday_realtime_sip_required"
    by_symbol = {r["symbol"]: r for r in report["rows"]}
    if (
        phase.name == "CORE"
        and not short_gate(cover=True)
        and (cancellation := _cancel_resting_short(client, snapshot, phase))
    ):
        return cancellation
    attempts = []
    if phase.name == "CORE" and short_positions and not short_gate(cover=True):
        for symbol, (pos, entry) in short_positions.items():
            row = by_symbol.get(symbol)
            if not row:
                continue
            try:
                asset = _asset(client, symbol)
                status = shorts.borrow(asset)
            except paper.PaperError:
                status = "UNKNOWN"
            row.update(borrow=status, borrow_verified_at=client.now().isoformat())
            if not row.get("quote_ready"):
                row["short_risk"] = (
                    "short_cover_quote_unavailable"
                    if status == "ETB"
                    else "short_borrow_and_cover_quote_unverified"
                )
                row["short_risk_priority"] = "HIGH"
                continue
            reason = shorts.cover_trigger(
                row,
                pos,
                entry,
                phase,
                client.now(),
                status,
                report["daily_loss_paused"],
                account_short_gross / paper.money(snapshot["account"]["equity"]),
            )
            if reason:
                row["short_risk"] = reason
                row["short_risk_priority"] = (
                    "HIGH" if "borrow" in reason or "risk" in reason else "NORMAL"
                )
                attempts.append((row, "buy", reason, Action.BUY_TO_COVER_SHORT))
    for pos in snapshot["positions"]:
        row = by_symbol.get(pos["symbol"])
        entry = _owned_entry(pos["symbol"], account_id)
        if row and entry and row["valid"] and pos["symbol"] in owned:
            reason = _exit_trigger(row, pos, entry, client.now())
            if reason:
                attempts.append((row, "sell", reason, None))
    if not attempts:
        short_candidates = [r for r in report["rows"] if r.get("short_reason") == "short_candidate"]
        if short_gate():
            short_candidates = []
        if not candidates and not short_candidates:
            return "WAIT"
        if (
            report["valid"] < report["required_confidence"]
            or report["snapshot_symbols"] != report["tracked"]
        ):
            return "intraday_universe_confidence_insufficient"
        ranked = [
            (D(row["score"]), row, "buy", "intraday_cost_adjusted_momentum", None)
            for row in candidates
        ]
        ranked += [
            (
                D(row["short_score"]),
                row,
                "sell",
                "intraday_short_breakdown",
                Action.SELL_TO_OPEN_SHORT,
            )
            for row in short_candidates
        ]
        ranked.sort(key=lambda r: (-r[0], r[1]["symbol"]))
        attempts = [(row, side, reason, action) for _, row, side, reason, action in ranked]
    for row, side, reason, action in attempts[:2]:
        try:
            return _submit(
                client,
                data,
                snapshot,
                row,
                all_bars[row["symbol"]],
                phase,
                side,
                reason,
                sectors,
                action,
            )
        except (paper.PaperError, ObservationError) as exc:
            row["risk_decision"] = str(exc)
            if any(
                part in str(exc)
                for part in (
                    "uncertain",
                    "without_local_intent",
                    "clock",
                    "http_",
                    "account",
                    "transport",
                )
            ):
                return str(exc)
    return "WAIT"


class IntradayEngine:
    def __init__(self):
        self.data = None
        self.previous_error = None

    def close(self):
        if self.data:
            self.data.close()

    def cycle(self, *, clock=None, broker_factory=None):
        clock = clock or (lambda: datetime.now(UTC))
        broker_factory = broker_factory or (
            lambda: paper.PaperClient(retry_reads=True, clock=clock)
        )
        at = clock()
        phase = phase_at(at)
        assets = rows("SELECT symbol,sector,enabled FROM assets ORDER BY symbol")
        sectors = {r["symbol"]: r["sector"] for r in assets}
        enabled = {r["symbol"] for r in assets if r["enabled"]}
        symbols = list(sectors)
        feed = (
            os.getenv("STOCKSWATCH_INTRADAY_OVERNIGHT_FEED", "overnight")
            if phase.name == "OVERNIGHT"
            else os.getenv("STOCKSWATCH_INTRADAY_FEED", "iex")
        )
        confidence = (
            len(symbols)
            if os.getenv("STOCKSWATCH_INTRADAY_REQUIRE_ALL_VALID") == "1"
            else (4 * len(symbols) + 4) // 5
        )
        report = {
            "strategy": STRATEGY,
            "at": at.isoformat(),
            "phase": phase.name,
            "trade_date": phase.day,
            "feed": feed,
            "tracked": len(symbols),
            "valid": 0,
            "snapshot_symbols": 0,
            "required_confidence": confidence,
            "rows": [],
            "status": "SESSION_CLOSED",
            "order_gate": order_gate(),
            "short_order_gate": short_gate(),
            "paper_only": True,
            "feed_scope": {
                "iex": "IEX_SINGLE_VENUE",
                "sip": "REALTIME_SIP_ENTITLEMENT_CHECKED_PER_REQUEST",
                "overnight": "DERIVED_OVERNIGHT_INDICATIVE",
                "boats": "BOATS_MONITOR_ONLY",
                "delayed_sip": "SIP_15_MINUTE_DELAY",
            }.get(feed, "UNSUPPORTED"),
        }
        overnight = phase.name == "OVERNIGHT"
        snapshot_only = overnight and feed == "overnight"
        if overnight:
            report["execution"] = "overnight_monitor_only"
        data_sources = report["data_sources"] = {}
        snapshots, bars, reference = {}, {}, {}
        if phase.start:
            try:
                if feed not in FEEDS or set(symbols) != REGISTRY.keys():
                    raise ObservationError("intraday_feed_or_universe_invalid")
                if self.data is None:
                    try:
                        self.data = IntradayData()
                    except RuntimeError as exc:
                        raise ObservationError(str(exc)) from None
                end = at.replace(second=0, microsecond=0)
                reference_day = (
                    phase.day if phase.name == "AFTERHOURS" else previous_regular_day(phase)
                )
                fetches = [
                    ("reference", lambda: self.data.regular_closes(symbols, feed, reference_day)),
                    ("snapshots", lambda: self.data.snapshots(symbols, feed)),
                ]
                if snapshot_only:
                    data_sources["bars"] = {
                        "status": "NOT_REQUESTED", "reason": "optional_overnight_history",
                    }
                elif end > phase.start:
                    fetches.insert(
                        0,
                        (
                            "bars",
                            lambda: self.data.bars(
                                symbols, feed, max(phase.start, end - 20 * MINUTE), end
                            ),
                        ),
                    )
                if overnight:
                    fetches.sort(key=lambda item: item[0] != "snapshots")
                fetched = {}
                for kind, fetch in fetches:
                    try:
                        fetched[kind] = fetch()
                        data_sources[kind] = {
                            "status": "AVAILABLE" if any(fetched[kind].values()) else "EMPTY",
                        }
                    except ObservationError as exc:
                        data_sources[kind] = {"status": "UNAVAILABLE", "reason": str(exc)}
                        if not overnight or kind == "snapshots":
                            report.update(status="DATA_UNAVAILABLE", reason=str(exc))
                        if "rate_limited" in str(exc):
                            break
                snapshots, bars, reference = (
                    fetched.get(k, {}) for k in ("snapshots", "bars", "reference")
                )
                report["snapshot_symbols"] = len(snapshots)
                if overnight and report["status"] != "DATA_UNAVAILABLE":
                    if data_sources.get("snapshots", {}).get("status") != "AVAILABLE":
                        reason = data_sources.get("snapshots", {}).get("reason")
                        report.update(status="DATA_UNAVAILABLE",
                                      reason=reason or "overnight_snapshots_unavailable")
                    elif snapshot_only or not any(bars.values()) or not reference:
                        report.update(status="SNAPSHOT_ONLY",
                                      reason="overnight_indicative_snapshots")
            except ObservationError as exc:
                report.update(status="DATA_UNAVAILABLE", reason=str(exc))
            observed_at = clock()
            report["at"] = observed_at.isoformat()
            observed_phase = phase_at(observed_at)
            if observed_phase != phase:
                report.update(
                    phase=observed_phase.name,
                    trade_date=observed_phase.day,
                    status="DATA_UNAVAILABLE",
                    reason="intraday_phase_changed_during_fetch",
                    snapshot_symbols=0,
                )
                snapshots, bars, reference = {}, {}, {}
                phase = observed_phase
            catalysts = {
                r["symbol"]: r
                for r in rows(
                    """
                SELECT symbol,form,accepted_at,observed_at FROM filings
                WHERE observed_at<=? AND accepted_at<=? AND accepted_at>=?
                ORDER BY accepted_at,observed_at
                """,
                    (
                        observed_at.isoformat(),
                        observed_at.isoformat(),
                        (observed_at - timedelta(hours=36)).isoformat(),
                    ),
                )
            }
            for symbol in symbols:
                row = observe(
                    symbol,
                    snapshots.get(symbol),
                    bars.get(symbol, []),
                    reference.get(symbol),
                    phase,
                    feed,
                    observed_at,
                )
                if report.get("reason") and not row["valid"]:
                    if report["status"] == "DATA_UNAVAILABLE":
                        row["reason"] = report["reason"]
                    elif snapshot_only and row.get("quote_ready"):
                        row["reason"] = "optional_overnight_history"
                row.update(catalyst=catalysts.get(symbol), enabled=symbol in enabled)
                report["rows"].append(row)
            report["valid"] = sum(r["valid"] for r in report["rows"])
            report["market_risk"], candidates = decide(report["rows"])
            report["short_candidates"] = len(shorts.rank(report["rows"]))
            if report["status"] not in {"DATA_UNAVAILABLE", "SNAPSHOT_ONLY"}:
                report["status"] = "OBSERVING"
                if paper.broker_mode() and phase.name in TRADABLE_PHASES and feed == "sip":
                    try:
                        with broker_factory() as client:
                            report["execution"] = execute(
                                client, self.data, report, candidates, bars, phase, sectors
                            )
                    except paper.PaperError as exc:
                        report["execution"] = str(exc)
                    except ObservationError as exc:
                        report["execution"] = str(exc)
                    report["transport_recovered"] = bool(
                        self.previous_error
                        and not any(
                            t in report["execution"] for t in ("http_", "transport", "unavailable")
                        )
                    )
                    self.previous_error = (
                        report["execution"]
                        if any(
                            t in report["execution"] for t in ("http_", "transport", "unavailable")
                        )
                        else None
                    )
                else:
                    report["execution"] = (
                        "overnight_monitor_only"
                        if phase.name == "OVERNIGHT"
                        else "intraday_realtime_sip_or_paper_account_required"
                    )
        report["finished_at"] = clock().isoformat()
        journal.save(report)
        return report
