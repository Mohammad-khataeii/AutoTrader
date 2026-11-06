"""Alpaca paper broker adapter. Financial truth comes ONLY from Alpaca.

Local sw_alpaca_* tables hold audit/intents, never account balances/fills.
Paper order submission is OFF until specifically enabled on the server.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from datetime import datetime, timezone

import httpx

from .storage import connect, rows, one, utc
from .sessions import completed_day, instant, next_day, session
from .ledger import (
    MAX_DRAWDOWN, MAX_GROSS_EXPOSURE, MAX_POSITIONS, MAX_SECTOR_WEIGHT,
    MAX_SYMBOL_WEIGHT, MAX_VOLATILITY, SCORE_MIN, eligible_signals,
)

PAPER_ORIGIN = "https://paper-api.alpaca.markets"
PREFIX = "swp2-"
TERMINAL = {"filled", "canceled", "expired", "rejected", "replaced"}
log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sw_alpaca_intents (
    client_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    signal_day TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL,
    broker_order_id TEXT,
    broker_status TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sw_alpaca_intents_day ON sw_alpaca_intents(signal_day, side);
CREATE TABLE IF NOT EXISTS sw_alpaca_state (
    id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL DEFAULT 1,
    linked_account TEXT, linked_at TEXT
);
INSERT OR IGNORE INTO sw_alpaca_state(id,paused) VALUES (1,1);
"""


def broker_mode():
    return os.getenv("STOCKSWATCH_EXECUTION_BACKEND", "local").strip().lower() == "alpaca_paper"


def orders_enabled():
    return os.getenv("STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS", "0") == "1"


def broker_init():
    with connect() as c:
        c.executescript(SCHEMA)


def safe_number(value, fallback=0.0):
    try:
        num = float(value)
        return num if math.isfinite(num) else fallback
    except (TypeError, ValueError, OverflowError):
        return fallback


def expected_account():
    return os.getenv("STOCKSWATCH_ALPACA_PAPER_ACCOUNT_ID", "").strip()


def _credentials():
    key = os.getenv("STOCKSWATCH_ALPACA_PAPER_KEY", "").strip()
    secret = os.getenv("STOCKSWATCH_ALPACA_PAPER_SECRET", "").strip()
    if not (key and secret):
        raise RuntimeError("alpaca_paper_credentials_missing")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


class PaperClient:
    """Only accepts constant paper host and narrowly defined endpoint paths."""
    def __init__(self, transport=None):
        self._client = httpx.Client(
            base_url=PAPER_ORIGIN,
            headers=_credentials(),
            timeout=httpx.Timeout(12.0, connect=5.0),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._client.close()

    def _request(self, method, path, **kwargs):
        if not path.startswith("/v2/") or "?" in path or "//" in path or ".." in path:
            raise RuntimeError("unapproved_paper_route")
        try:
            response = self._client.request(method, path, **kwargs)
            if response.status_code >= 400:
                if response.status_code == 404:
                    return None
                # Do not log response bodies/headers; some contain account details.
                raise RuntimeError(f"alpaca_paper_http_{response.status_code}")
            return response.json()
        except httpx.HTTPError as e:
            raise RuntimeError("alpaca_paper_transport_unavailable") from e
        except ValueError as e:
            raise RuntimeError("alpaca_paper_invalid_json") from e

    def get(self, path, params=None):
        return self._request("GET", path, params=params)

    def account(self):
        account = self.get("/v2/account")
        if not isinstance(account, dict):
            raise RuntimeError("alpaca_paper_account_unavailable")
        account_id = str(account.get("id") or "")
        number = str(account.get("account_number") or "")
        expected = expected_account()
        if not expected:
            raise RuntimeError("alpaca_paper_expected_account_not_configured")
        if expected not in (account_id, number):
            raise RuntimeError("alpaca_paper_account_mismatch")
        if account.get("currency") != "USD" or account.get("status") != "ACTIVE":
            raise RuntimeError("alpaca_paper_account_not_active_usd")
        if account.get("trading_blocked") or account.get("account_blocked"):
            raise RuntimeError("alpaca_paper_account_blocked")
        return account

    def snapshot(self):
        account = self.account()
        positions = self.get("/v2/positions")
        orders = self.get("/v2/orders", {"status": "all", "limit": 500, "direction": "desc", "nested": "false"})
        if not isinstance(positions, list) or not isinstance(orders, list):
            raise RuntimeError("alpaca_paper_snapshot_incomplete")
        try:
            history = self.get("/v2/account/portfolio/history", {"period": "1M", "timeframe": "1D"})
        except RuntimeError:
            history = None
        try:
            fills = self.get("/v2/account/activities/FILL", {"direction": "desc", "page_size": 100})
        except RuntimeError:
            fills = None
        if not isinstance(fills, list):
            fills = []
        if not isinstance(history, dict):
            history = {}
        return {"account": account, "positions": positions, "orders": orders, "fills": fills, "history": history}

    def by_client_id(self, cid):
        if not re.fullmatch(r"swp2-[a-f0-9]{40}", cid):
            raise RuntimeError("invalid_client_order_id")
        return self.get("/v2/orders:by_client_order_id", {"client_order_id": cid})

    def submit(self, payload):
        if not orders_enabled():
            raise RuntimeError("alpaca_paper_orders_disabled")
        if payload.get("client_order_id", "")[:len(PREFIX)] != PREFIX:
            raise RuntimeError("invalid_client_order_id")
        if payload.get("side") not in ("buy", "sell") or payload.get("time_in_force") != "day":
            raise RuntimeError("unsafe_order_request")
        return self._request("POST", "/v2/orders", json=payload)


def masked_account(account):
    number = str(account.get("account_number") or "")
    return ("…" + number[-4:]) if number else "verified"


def account_ui(snapshot):
    a = snapshot["account"]
    positions = snapshot["positions"]
    equity = safe_number(a.get("equity"))
    cash = safe_number(a.get("cash"))
    last_equity = safe_number(a.get("last_equity"))
    exposure = sum(max(0.0, safe_number(p.get("market_value"))) for p in positions)
    history = snapshot["history"]
    times, equities = history.get("timestamp", []), history.get("equity", [])
    curve = []
    if isinstance(times, list) and isinstance(equities, list):
        for t, val in zip(times, equities):
            if val is None or not isinstance(t, (int, float)):
                continue
            curve.append({"day": datetime.fromtimestamp(t, timezone.utc).isoformat(), "equity": safe_number(val), "spy_close": None})
    base = safe_number(history.get("base_value")) or (curve[0]["equity"] if curve else equity)
    delta = equity - last_equity if last_equity else 0.0
    pnl_pct = delta / last_equity * 100 if last_equity else 0.0
    high = max((x["equity"] for x in curve), default=equity)
    drawdown = max(0, (high - equity) / high * 100) if high else 0.0
    ui_positions = [
        {
            "symbol": p.get("symbol"),
            "qty": safe_number(p.get("qty")),
            "avg_cost": safe_number(p.get("avg_entry_price")),
            "mark": safe_number(p.get("current_price")),
            "market_value": safe_number(p.get("market_value")),
            "unrealized": safe_number(p.get("unrealized_pl")),
            "unrealized_pct": safe_number(p.get("unrealized_plpc")) * 100,
            "sector": "Broker position",
            "stop": None,
            "broker_position": True,
        }
        for p in positions
    ]
    active = {"new", "accepted", "pending_new", "partially_filled", "accepted_for_bidding", "pending_cancel", "pending_replace", "done_for_day", "calculated", "stopped", "suspended"}
    orders = [
        {
            "id": o.get("id"), "client_order_id": o.get("client_order_id"),
            "symbol": o.get("symbol"), "side": str(o.get("side", "")).upper(),
            "state": str(o.get("status", "")).upper(), "qty": o.get("qty"),
            "filled_qty": o.get("filled_qty"), "filled_avg_price": o.get("filled_avg_price"),
            "created_at": o.get("created_at"), "submitted_at": o.get("submitted_at"),
            "filled_at": o.get("filled_at"), "signal_day": None,
            "broker_order": True,
            "managed": str(o.get("client_order_id") or "").startswith(PREFIX),
        }
        for o in snapshot["orders"]
    ]
    fills = [{
        "id": f.get("id"), "symbol": f.get("symbol"),
        "side": str(f.get("side", "")).upper(),
        "qty": safe_number(f.get("qty")),
        "price": safe_number(f.get("price")),
        "created_at": f.get("transaction_time") or f.get("date"),
        "order_id": f.get("order_id"),
        "source": "ALPACA_PAPER_FILLS", "broker_fill": True,
    } for f in snapshot["fills"]]
    return {
        "account": {
            "currency": "USD", "initial_cash": base, "cash": cash,
            "equity": equity, "exposure": exposure, "unrealized": sum(p["unrealized"] for p in ui_positions),
            "realized": None, "drawdown_pct": round(drawdown, 3),
            "pnl": round(delta, 2), "pnl_pct": round(pnl_pct, 3),
            "buying_power": safe_number(a.get("buying_power")),
            "daytrading_buying_power": safe_number(a.get("daytrading_buying_power")),
            "paused": bool((one("SELECT paused FROM sw_alpaca_state WHERE id=1") or {}).get("paused", 1)),
            "account_masked": masked_account(a), "broker": "Alpaca Paper", "pnl_period": "day",
        },
        "positions": ui_positions, "equity_curve": curve,
        "pending_orders": [o for o in orders if o["state"].lower() in active],
        "order_history": [o for o in orders if o["state"].lower() not in active],
        "fills": fills,
        "last_fill": {"last_buy": next((f["created_at"] for f in fills if f["side"] == "BUY"), None),
                      "last_sell": next((f["created_at"] for f in fills if f["side"] == "SELL"), None)},
        "broker_account": {"masked": masked_account(a), "status": "CONNECTED", "as_of": utc(),
                           "source": "Alpaca Paper Trading API", "order_submission_enabled": orders_enabled()},
    }


def enrich_dashboard(local):
    """Return broker-authoritative financial fields; never silently fall back to local cash."""
    with PaperClient() as client:
        snapshot = client.snapshot()
    view = account_ui(snapshot)
    local.update(view)
    local["paper_only"] = True
    local["execution_mode"] = "ALPACA_PAPER"
    local["can_issue_live_orders"] = False
    local["legacy_local_pending_orders"] = rows(
        "SELECT symbol,side,signal_day,state,created_at FROM pending_orders WHERE state='PENDING' ORDER BY created_at"
    )
    return local


def broker_status():
    if not broker_mode():
        return {"mode": "LOCAL_PAPER", "broker": "NOT_SELECTED"}
    try:
        with PaperClient() as client:
            account = client.account()
        return {"mode": "ALPACA_PAPER", "broker": "CONNECTED", "account_masked": masked_account(account),
                "orders_enabled": orders_enabled(), "updated_at": utc()}
    except Exception as exc:
        return {"mode": "ALPACA_PAPER", "broker": "DISCONNECTED", "reason": str(exc),
                "orders_enabled": False, "updated_at": utc()}


def set_broker_paused(paused):
    with connect() as c:
        c.execute("UPDATE sw_alpaca_state SET paused=? WHERE id=1", (int(paused),))
    return {"paused": paused, "mode": "alpaca_paper"}


def cid_for(account_id, symbol, day, side):
    return PREFIX + hashlib.sha256(f"paper2|{account_id}|{day}|{symbol}|{side}".encode()).hexdigest()[:40]


def _intent(c, cid, account_id, day, symbol, side, qty, reason):
    """Persist the intent BEFORE the network call; unknown outcomes never retry blindly."""
    t = utc()
    cur = c.execute("""INSERT OR IGNORE INTO sw_alpaca_intents
        (client_id,account_id,signal_day,symbol,side,qty,reason,state,created_at,updated_at,detail_json)
        VALUES(?,?,?,?,?,?,?,'PREPARED',?,?,?)""",
        (cid,account_id,day,symbol,side,str(qty),reason,t,t,"{}"))
    return cur.rowcount == 1


def _state(cid, status, order=None, reason=""):
    with connect() as c:
        c.execute("""UPDATE sw_alpaca_intents SET state=?,broker_order_id=?,broker_status=?,updated_at=?,detail_json=?
                   WHERE client_id=?""",
                  (status, str(order.get("id") or "") if isinstance(order, dict) else None,
                   str(order.get("status") or "") if isinstance(order, dict) else None,
                   utc(), json.dumps({"reason": reason}), cid))


def _guard_snapshot(snapshot):
    a = snapshot["account"]
    if safe_number(a.get("equity")) <= 0 or safe_number(a.get("cash")) < 0:
        raise RuntimeError("invalid_broker_account_balance")
    for p in snapshot["positions"]:
        if str(p.get("side")) != "long" or p.get("asset_class") != "us_equity":
            raise RuntimeError("unsupported_or_short_broker_position")
    if len(snapshot["orders"]) >= 500:
        raise RuntimeError("broker_order_history_truncated")
    if any(safe_number(p.get("qty")) <= 0 for p in snapshot["positions"]):
        raise RuntimeError("broker_position_quantity_invalid")


def _risk_inputs(snapshot):
    eq = safe_number(snapshot["account"].get("equity"))
    cash = safe_number(snapshot["account"].get("cash"))
    gross = sum(max(0, safe_number(p.get("market_value"))) for p in snapshot["positions"])
    active = [o for o in snapshot["orders"] if str(o.get("status")) not in TERMINAL]
    return eq, cash, gross, active


def _tracked_fills(snapshot):
    # Managed holdings: only shares attributable to this strategy's confirmed broker buys.
    # If there were intervening manual trades on a symbol, ownership is ambiguous => no sell.
    orders = {str(o.get("id")): o for o in snapshot["orders"]}
    managed = {}
    for f in snapshot["fills"]:
        o = orders.get(str(f.get("order_id")))
        if not o or not str(o.get("client_order_id") or "").startswith(PREFIX):
            continue
        sym = str(f.get("symbol"))
        side = str(f.get("side", "")).lower()
        qty = safe_number(f.get("qty"))
        if side in ("buy", "sell") and qty > 0:
            managed[sym] = managed.get(sym, 0.0) + qty * (1 if side == "buy" else -1)
    return managed


def _preview_and_submit(client, snapshot, signals, day):
    """EOD decisions; capped cash-backed paper LIMIT buys, managed long exits only.

    Does not trade while paused, without documented source provenance or broker state.
    It checks the broker by client ID before and after any uncertain POST.
    """
    result = {"status": "RESEARCH_ONLY", "processed": len(signals), "orders_queued": 0,
              "broker_orders_submitted": 0, "market_day": day, "why_no_trade": [],
              "mode": "ALPACA_PAPER", "at": utc()}
    _guard_snapshot(snapshot)
    if not orders_enabled():
        result["status"] = "BROKER_ORDERS_DISABLED"
        return result
    state = one("SELECT paused FROM sw_alpaca_state WHERE id=1")
    if state is None or state["paused"]:
        result["status"] = "BROKER_PAUSED"
        return result
    now = datetime.now(timezone.utc)
    if not signals or completed_day(now) != day:
        result["status"] = "NO_CERTIFIED_CURRENT_SIGNALS"
        return result
    if now >= session(next_day(day))[0]:
        # The next-session opening execution window was already missed.
        result["status"] = "STALE_SIGNAL_TARGET_SESSION_ALREADY_OPENED"
        return result
    eq, cash, gross, active = _risk_inputs(snapshot)
    if not eq:
        raise RuntimeError("invalid_paper_equity")
    # Only exchange-verified, certified, completed EOD signals can be executed.
    sources = {r["symbol"]: r for r in rows("""SELECT o.symbol,o.day,o.c,o.observed_at,q.status AS check_status
                FROM sw_eod_observations o JOIN sw_price_checks q ON q.symbol=o.symbol AND q.day=o.day
                WHERE o.day=? AND o.source='alpaca_iex_daily' AND o.adjustment='RAW'""", (day,))}
    known = {str(p.get("symbol")): p for p in snapshot["positions"]}
    sectors = {r["symbol"]: r["sector"] for r in rows("SELECT symbol,sector FROM assets")}
    reserved = {str(o.get("symbol")) for o in active}
    if any(not str(o.get("symbol") or "") for o in active):
        raise RuntimeError("broker_open_order_missing_symbol")
    managed_qty = _tracked_fills(snapshot)
    today_prefix = {str(r["symbol"]) for r in rows(
        "SELECT symbol FROM sw_alpaca_intents WHERE signal_day=?", (day,))}
    buys_today = (one("SELECT COUNT(*) AS n FROM sw_alpaca_intents WHERE signal_day=? AND side='BUY'", (day,)) or {})["n"]
    # All open broker orders and all manual positions count against allocation.
    if any(not str(o.get("client_order_id") or "").startswith(PREFIX) for o in active):
        result["status"] = "EXTERNAL_BROKER_ORDERS_OPEN"
        return result
    if len(active) >= 15:
        result["status"] = "BROKER_TOO_MANY_PENDING_ORDERS"
        return result
    if gross > eq * MAX_GROSS_EXPOSURE:
        result["status"] = "EXPOSURE_OVER_CAP"
        return result
    # Drawdown and daily-loss circuit breakers restrict new entries, not exits.
    history = snapshot.get("history") or {}
    valid_marks = [safe_number(x) for x in history.get("equity", []) if safe_number(x) > 0]
    peak = max(valid_marks + [eq])
    drawdown = (peak - eq) / peak if peak > 0 else 1
    last_equity = safe_number(snapshot["account"].get("last_equity"))
    day_loss = (last_equity - eq) / last_equity if last_equity > 0 else 0
    buy_paused = drawdown >= MAX_DRAWDOWN or day_loss >= 0.035
    # No unattended order if any existing broker position lies outside researched universe.
    if any(sym not in sectors for sym in known):
        result["status"] = "EXTERNAL_POSITION_OUTSIDE_UNIVERSE"
        return result
    # If history/fill window is insufficient to attribute owned shares, no SELL is authorized.
    # The strategy still reads/monitors such positions from broker dashboard.
    # Exits have priority over buys. The signal list still sorts deterministically.
    ordered = sorted(signals, key=lambda s: (str(s.get("symbol")) not in known,
                                                -safe_number(s.get("score")), str(s.get("symbol"))))
    for signal in ordered:
        sym = str(signal.get("symbol") or "")
        certified = sources.get(sym)
        item = {"symbol": sym, "action": "WATCH", "reason": "no_entry_signal"}
        result["why_no_trade"].append(item)
        if not certified or certified["check_status"] != "OK":
            item["reason"] = "uncertified_daily_observation"
            continue
        if signal.get("day") != day or signal.get("source") != "alpaca_iex_daily":
            item["reason"] = "stale_or_untrusted_signal"
            continue
        if not safe_number(certified["c"]) or sym in reserved or sym in today_prefix:
            item["reason"] = "pending_or_already_ordered"
            continue
        if sym in known:
            # No blind liquidation of user-managed or mixed holdings. Exit only when
            # strategy-owned filled quantity equals broker-held quantity and data verified.
            p = known[sym]
            match_qty = abs(managed_qty.get(sym, 0.0) - safe_number(p.get("qty"))) < 1e-6
            if not match_qty:
                item["reason"] = "external_position_not_strategy_owned"
                continue
            ev = signal.get("features") or {}
            px = safe_number(certified["c"])
            avg = safe_number(p.get("avg_entry_price"))
            sma50 = safe_number(ev.get("sma50"))
            if not avg or not sma50:
                item["reason"] = "exit_evidence_missing"
                continue
            if px >= avg * 0.92 and px >= sma50 * 0.96 and safe_number(signal.get("score")) >= 0.8:
                item["reason"] = "no_exit_trigger"
                continue
            action, qty, reason = "SELL", int(safe_number(p.get("qty"))), "eod_stop_or_trend_exit"
            if qty <= 0:
                continue
            payload = {"symbol": sym, "qty": str(qty), "side": "sell", "type": "market",
                       "time_in_force": "day", "extended_hours": False}
        else:
            if buy_paused:
                item["reason"] = "broker_drawdown_or_daily_loss_pause"
                continue
            if safe_number(signal.get("score")) < SCORE_MIN:
                item["reason"] = "score_below_threshold"
                continue
            if buys_today >= 2 or len(known) + buys_today >= MAX_POSITIONS:
                item["reason"] = "daily_or_position_cap"
                continue
            features = signal.get("features") or {}
            if safe_number(features.get("volatility_annual"), 999) >= MAX_VOLATILITY:
                item["reason"] = "volatility_cap"
                continue
            if signal.get("regime") != "RISK_ON":
                item["reason"] = "benchmark_regime_unapproved"
                continue
            sector = sectors.get(sym)
            if not sector or sector == "Benchmark":
                item["reason"] = "unknown_sector"
                continue
            # Account may include externally placed holdings. Unknown sector is a block.
            if any(sectors.get(h) is None for h in known):
                item["reason"] = "unknown_existing_sector"
                continue
            sector_used = sum(safe_number(p.get("market_value")) for h,p in known.items() if sectors.get(h)==sector)
            for order in active:
                if sectors.get(str(order.get("symbol"))) == sector and str(order.get("side")) == "buy":
                    sector_used += safe_number(order.get("qty"))*safe_number(certified["c"])
            px = safe_number(certified["c"])
            # Conservative limit buys: protect against opening gaps rather than using market buys.
            limit = math.floor(px * 1.005 * 100) / 100
            # Hard minimum tick and reserved financial buffer.
            if limit <= 0:
                item["reason"] = "invalid_limit"
                continue
            open_reserve = sum(safe_number(o.get("qty"))*safe_number(o.get("limit_price") or o.get("stop_price") or px)
                               for o in active if str(o.get("side")) == "buy")
            budget = min(eq*MAX_SYMBOL_WEIGHT, eq*MAX_SECTOR_WEIGHT-sector_used,
                         eq*MAX_GROSS_EXPOSURE-gross-open_reserve,
                         cash-eq*0.40-open_reserve)
            qty = int(max(0, math.floor(budget / limit / 1.01)))
            if qty < 1:
                item["reason"] = "cash_or_exposure_cap"
                continue
            action, reason = "BUY", "certified_eod_signal"
            payload = {"symbol": sym, "qty": str(qty), "side": "buy", "type": "limit",
                       "limit_price": f"{limit:.2f}", "time_in_force": "day", "extended_hours": False}
        cid = cid_for(str(snapshot["account"].get("id")), sym, day, action)
        payload["client_order_id"] = cid
        # Broker lookup first; never resubmit the same decision.
        present = client.by_client_id(cid)
        if present:
            item["reason"] = "broker_order_already_exists"
            continue
        with connect() as c:
            c.execute("BEGIN IMMEDIATE")
            fresh = _intent(c, cid, str(snapshot["account"].get("id")), day, sym, action, qty, reason)
            c.commit()
        if not fresh:
            item["reason"] = "existing_or_uncertain_intent"
            continue
        try:
            # A POST timeout is UNKNOWN, never interpreted as a safe retry.
            order = client.submit(payload)
            if not isinstance(order, dict) or order.get("client_order_id") != cid:
                raise RuntimeError("broker_order_response_mismatch")
            _state(cid, "ACKNOWLEDGED", order)
            item.update({"action": action, "reason": "broker_order_submitted"})
            result["broker_orders_submitted"] += 1
            if action == "BUY":
                buys_today += 1
                cash -= qty * safe_number(payload["limit_price"])
                gross += qty * safe_number(payload["limit_price"])
            reserved.add(sym)
            today_prefix.add(sym)
        except Exception as exc:
            _state(cid, "UNKNOWN", reason=type(exc).__name__)
            item["reason"] = "broker_order_outcome_uncertain_do_not_retry"
            log.warning("Alpaca paper order outcome uncertain for %s", sym)
            # Stop, reconcile externally before the next decision cycle.
            result["status"] = "BROKER_ORDER_UNCERTAIN"
            return result
    result["status"] = "BROKER_SUBMITTED" if result["broker_orders_submitted"] else "NO_APPROVED_BROKER_SIGNAL"
    result["orders_queued"] = result["broker_orders_submitted"]
    return result


def paper_cycle():
    broker_init()
    with PaperClient() as client:
        snapshot = client.snapshot()
        _guard_snapshot(snapshot)
        # Reconcile intents from authoritative broker state; never derive fills locally.
        local_intents = rows("SELECT client_id,state FROM sw_alpaca_intents ORDER BY created_at DESC LIMIT 50")
        for intent in local_intents:
            broker = client.by_client_id(intent["client_id"])
            if broker:
                current = str(broker.get("status") or "").lower()
                _state(intent["client_id"], "TERMINAL" if current in TERMINAL else "ACKNOWLEDGED", broker)
            elif intent["state"] in ("PREPARED", "UNKNOWN"):
                # Not found after an uncertain POST does not authorize resubmission.
                return {"status": "UNCERTAIN_BROKER_INTENT", "mode": "ALPACA_PAPER",
                        "market_day": completed_day(datetime.now(timezone.utc)),
                        "orders_queued": 0, "pending_count": 1, "at": utc()}
        if not orders_enabled():
            return {"status": "BROKER_READ_ONLY", "mode": "ALPACA_PAPER",
                    "market_day": completed_day(datetime.now(timezone.utc)),
                    "orders_queued": 0, "pending_count": 0, "at": utc()}
        signals, day = eligible_signals()
        if not day:
            return {"status": "NO_CERTIFIED_BENCHMARK", "mode": "ALPACA_PAPER", "orders_queued": 0,
                    "market_day": completed_day(datetime.now(timezone.utc)), "at": utc()}
        return _preview_and_submit(client, snapshot, signals, day)
