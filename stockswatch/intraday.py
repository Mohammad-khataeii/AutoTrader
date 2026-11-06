"""Independent deterministic intraday decisions, sharing only Alpaca paper authority."""

import hashlib
import os
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from . import alpaca_paper as paper
from . import intraday_store as journal
from .intraday_market import FEEDS, MINUTE, IntradayData, ObservationError, observe, positive
from .intraday_policy import (
    ORDER_PREFIX,
    STRATEGY,
    TRADABLE_PHASES,
    order_gate,
    phase_at,
    previous_regular_day,
)
from .sessions import instant
from .storage import connect, one, rows

D = Decimal
BENCHMARKS = {"SPY", "QQQ"}
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
        elif (gap + move) * 10000 < cost + D(20):
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
        side,created_at,detail_json FROM sw_alpaca_intents WHERE account_id=? AND client_id LIKE ?
        AND broker_order_id IS NOT NULL""",
            (account_id, ORDER_PREFIX + "%"),
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


def _submit(client, data, snapshot, row, raw_bars, phase, side, reason, sectors):
    symbol = row["symbol"]
    account_id = snapshot["account"]["id"]
    now = client.now()
    if phase_at(now) != phase or not phase.start + timedelta(
        seconds=15
    ) <= now < phase.end - timedelta(seconds=45):
        raise paper.PaperError("intraday_session_transition")
    start = previous_regular_day(phase)
    if side == "sell":
        start = min(start, _owned_entry(symbol, account_id)["signal_day"])
    events = data.corporate_actions(symbol, start, phase.day)
    if events:
        row["corporate_actions"] = events
        raise paper.PaperError("intraday_corporate_action_review_required")
    asset = _asset(client, symbol)
    # Fresh broker state, quote and clock immediately before persisting the intent.
    fresh = _snapshot(client)
    if fresh["account"]["id"] != account_id:
        raise paper.PaperError("intraday_account_changed")
    raw = data.snapshots([symbol], "sip").get(symbol)
    now = client.now()
    refreshed = observe(symbol, raw, raw_bars, row["previous_regular_close"], phase, "sip", now)
    if not refreshed["valid"] or refreshed["latest_completed_at"] != row["latest_completed_at"]:
        raise paper.PaperError("intraday_dispatch_quote_or_context_stale")
    key = "ap" if side == "buy" else "bp"
    if abs(positive(refreshed["quote"][key]) / positive(row["quote"][key]) - 1) > D(".0015"):
        raise paper.PaperError("intraday_price_moved_recheck")
    refreshed["market_risk"] = row["market_risk"]
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
                {**payload, "session": phase.name},
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
                {**payload, "session": phase.name},
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
            action=side.upper(), reason=reason, client_id=cid, risk_decision=f"broker_{status}"
        )
        return f"BROKER_{status.upper()}"


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
    for row in report["rows"]:
        row["position_owner"] = ownership.get(row["symbol"])
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
    attempts = []
    for pos in snapshot["positions"]:
        row = by_symbol.get(pos["symbol"])
        entry = _owned_entry(pos["symbol"], account_id)
        if row and entry and row["valid"] and pos["symbol"] in owned:
            reason = _exit_trigger(row, pos, entry, client.now())
            if reason:
                attempts.append((row, "sell", reason))
    if not attempts:
        if not candidates:
            return "WAIT"
        if (
            report["valid"] < report["required_confidence"]
            or report["snapshot_symbols"] != report["tracked"]
        ):
            return "intraday_universe_confidence_insufficient"
        attempts = [(row, "buy", "intraday_cost_adjusted_momentum") for row in candidates]
    for row, side, reason in attempts[:2]:
        try:
            return _submit(
                client, data, snapshot, row, all_bars[row["symbol"]], phase, side, reason, sectors
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
            len(symbols) if os.getenv("STOCKSWATCH_INTRADAY_REQUIRE_ALL_VALID") == "1" else 26
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
            "paper_only": True,
            "feed_scope": {
                "iex": "IEX_SINGLE_VENUE",
                "sip": "REALTIME_SIP_ENTITLEMENT_CHECKED_PER_REQUEST",
                "overnight": "DERIVED_OVERNIGHT_INDICATIVE",
                "boats": "BOATS_MONITOR_ONLY",
                "delayed_sip": "SIP_15_MINUTE_DELAY",
            }.get(feed, "UNSUPPORTED"),
        }
        snapshots, bars, reference = {}, {}, {}
        if phase.start:
            try:
                if feed not in FEEDS or len(symbols) != 32 or not BENCHMARKS.issubset(symbols):
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
                if end > phase.start:
                    fetches.insert(
                        0,
                        (
                            "bars",
                            lambda: self.data.bars(
                                symbols, feed, max(phase.start, end - 20 * MINUTE), end
                            ),
                        ),
                    )
                fetched = {}
                for kind, fetch in fetches:
                    try:
                        fetched[kind] = fetch()
                    except ObservationError as exc:
                        report.update(status="DATA_UNAVAILABLE", reason=str(exc))
                        if "rate_limited" in str(exc):
                            break
                snapshots, bars, reference = (
                    fetched.get(k, {}) for k in ("snapshots", "bars", "reference")
                )
                report["snapshot_symbols"] = len(snapshots)
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
                    row["reason"] = report["reason"]
                row.update(catalyst=catalysts.get(symbol), enabled=symbol in enabled)
                report["rows"].append(row)
            report["valid"] = sum(r["valid"] for r in report["rows"])
            report["market_risk"], candidates = decide(report["rows"])
            if report["status"] != "DATA_UNAVAILABLE":
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
