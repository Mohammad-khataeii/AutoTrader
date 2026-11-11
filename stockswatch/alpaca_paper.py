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
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation

import httpx

from .direction import SHORT_PREFIX, Action, intent_action, position as normalized_position
from .intraday_policy import ORDER_PREFIX as INTRADAY_PREFIX, TRADABLE_PHASES, order_gate, phase_at, short_gate
from .ledger import (
    MAX_DRAWDOWN,
    MAX_GROSS_EXPOSURE,
    MAX_ONE_DAY_LOSS,
    MAX_POSITIONS,
    MAX_SECTOR_WEIGHT,
    MAX_SYMBOL_WEIGHT,
    MAX_VOLATILITY,
    SCORE_MIN,
    eligible_signals,
    execution_configuration_gate,
)
from .sessions import NY, completed_day, instant, next_day, session
from .storage import connect, one, rows, utc

PAPER_ORIGIN = "https://paper-api.alpaca.markets"
PREFIX = "swp2-"
CASH_BUFFER = Decimal("0.40")
MIN_IEX_DOLLAR_VOLUME = 1_000_000
OPEN_WINDOW = timedelta(hours=1)
FILL_PAGE_SIZE = 100
SYNC_MAX_AGE = 120
_admission = threading.Lock()
broker_cycle_lock = threading.Lock()
_view_lock = threading.Lock()
_last_view = None
_sync_error = None
_last_sync = 0.0
_market_clock = {"verified": False, "reason": "alpaca_market_clock_not_observed"}
TERMINAL = {"filled", "canceled", "expired", "rejected", "replaced"}
ORDER_STATES = TERMINAL | {
    "new",
    "accepted",
    "pending_new",
    "partially_filled",
    "accepted_for_bidding",
    "pending_cancel",
    "pending_replace",
    "done_for_day",
    "calculated",
    "stopped",
    "suspended",
}
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
-- Highest broker-verified equity mark, scoped to one linked paper account.
-- Only updated after a valid Alpaca portfolio-history observation.
CREATE TABLE IF NOT EXISTS sw_paper_risk_peaks (
 account_id TEXT PRIMARY KEY,
 high_water TEXT NOT NULL,
 verified_at TEXT NOT NULL);
-- Decision evidence is advisory and cannot authorize or execute orders.
CREATE TABLE IF NOT EXISTS sw_broker_decision_cycles (
 at TEXT PRIMARY KEY, session_day TEXT NOT NULL,
 status TEXT NOT NULL, reason TEXT, result_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sw_broker_cycle_day ON sw_broker_decision_cycles(session_day,at);
"""


class PaperError(RuntimeError):
    """Stable diagnostic code. Never includes request data or credentials."""


class PaperLocalRefusal(PaperError):
    """Local validation refused a POST before any broker request."""


class PaperRejection(PaperError):
    """An explicit broker rejection of this order."""


def broker_mode():
    mode = os.getenv("STOCKSWATCH_EXECUTION_BACKEND", "local").strip().lower()
    if mode not in ("local", "alpaca_paper"):
        raise PaperError("stockswatch_execution_backend_invalid")
    return mode == "alpaca_paper"


def orders_enabled():
    return os.getenv("STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS", "0") == "1"


def broker_init():
    with connect() as c:
        c.executescript(SCHEMA)
    from .profit_oco import initialize as init_protection
    init_protection()


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
        raise PaperError("alpaca_paper_credentials_missing")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


class PaperClient:
    """Only accepts constant paper host and narrowly defined endpoint paths."""

    def __init__(self, transport=None, *, retry_reads=False, clock=None):
        self.retry_reads = retry_reads
        self.now = clock or (lambda: datetime.now(UTC))
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
            raise PaperError("unapproved_paper_route")
        attempts = 2 if method == "GET" and self.retry_reads else 1
        for attempt in range(attempts):
            try:
                response = self._client.request(method, path, **kwargs)
            except httpx.TransportError:
                if attempt+1 == attempts:
                    raise PaperError("alpaca_paper_transport_unavailable") from None
            else:
                if response.status_code not in (429, 500, 502, 503, 504) or attempt+1 == attempts:
                    break
                if response.status_code == 429:
                    try:
                        delay = float(response.headers.get("Retry-After", "1"))
                    except ValueError:
                        break
                    if not 0 <= delay <= 1:
                        break
                    time.sleep(delay)
                    continue
            time.sleep(0.25)
        if (
            response.status_code == 404
            and path == "/v2/orders:by_client_order_id"
            and method == "GET"
        ):
            return None
        if not response.is_success:
            # A documented insufficient-buying-power rejection is definitive.
            # Duplicate-ID errors, throttling, 5xx and unclassified errors are uncertain.
            if method == "POST" and response.status_code == 403:
                try:
                    body = response.json()
                except ValueError:
                    body = None
                if isinstance(body, dict) and str(body.get("code")) == "40310000":
                    raise PaperRejection("alpaca_paper_insufficient_buying_power")
            raise PaperError(f"alpaca_paper_http_{response.status_code}")
        if method=="DELETE" and response.status_code==204:
            return None
        try:
            return response.json()
        except ValueError:
            raise PaperError("alpaca_paper_invalid_json") from None

    def get(self, path, params=None):
        return self._request("GET", path, params=params)

    def account(self):
        account = self.get("/v2/account")
        if not isinstance(account, dict) or not account.get("id"):
            raise PaperError("alpaca_paper_account_unavailable")
        expected = expected_account()
        if not expected:
            raise PaperError("alpaca_paper_expected_account_not_configured")
        if expected not in (account["id"], account.get("account_number")):
            raise PaperError("alpaca_paper_account_mismatch")
        if account.get("currency") != "USD":
            raise PaperError("alpaca_paper_account_not_usd")
        return account

    def _optional(self, path, params, expected_type):
        try:
            value = self.get(path, params)
            if isinstance(value, expected_type):
                return value, None
            return None, "alpaca_paper_invalid_snapshot_component"
        except PaperError as exc:
            return None, str(exc)

    def snapshot(self):
        account = self.account()
        # The history limit is solely a display limit. Risk uses an independent open-order book.
        open_orders = self.get("/v2/orders", {"status": "open", "limit": 500, "nested": "false"})
        positions = self.get("/v2/positions")
        if not all(
            isinstance(items, list) and all(isinstance(x, dict) for x in items)
            for items in (positions, open_orders)
        ):
            raise PaperError("alpaca_paper_snapshot_incomplete")
        recent, order_error = self._optional(
            "/v2/orders",
            {
                "status": "closed",
                "limit": 100,
                "direction": "desc",
                "nested": "false",
            },
            list,
        )
        history, history_error = self._optional(
            "/v2/account/portfolio/history",
            {
                "period": "1M",
                "timeframe": "1D",
            },
            dict,
        )
        fills, fill_error = self._optional(
            "/v2/account/activities/FILL",
            {
                "direction": "desc",
                "page_size": FILL_PAGE_SIZE,
            },
            list,
        )
        if fills is not None and not all(isinstance(f, dict) for f in fills):
            fills, fill_error = None, "alpaca_paper_invalid_fill_activity"
        orders = {
            o["id"]: o for o in (recent or []) + open_orders if isinstance(o, dict) and o.get("id")
        }
        # Alpaca delivers stock and crypto holdings/orders from the SAME
        # paper account. Keep StocksWatch's stock ledger distinct from crypto
        # intents, while the shared cash/equity stays broker-authoritative.
        from .alpaca_crypto import PAIRS
        from .universe import ASSETS
        crypto_symbols = set(PAIRS) | {s.replace("/", "") for s in PAIRS}
        stock_symbols = {a[0] for a in ASSETS}
        def is_crypto(item):
            kind = item.get("asset_class")
            if kind == "crypto":
                return True
            if kind == "us_equity":
                return False
            symbol = item.get("symbol")
            if symbol in crypto_symbols:
                return True
            if symbol in stock_symbols:
                return False
            # Unknown asset classes/asset IDs are never silently excluded
            # from the risk-relevant open order/position book.
            raise PaperError("alpaca_shared_account_asset_class_unknown")
        other_positions = [p for p in positions if is_crypto(p)]
        positions = [p for p in positions if not is_crypto(p)]
        other_open_orders = [o for o in open_orders if is_crypto(o)]
        open_orders = [o for o in open_orders if not is_crypto(o)]
        orders = {oid:o for oid,o in orders.items() if not is_crypto(o)}
        if fills is not None:
            # FILL activities may omit asset_class; use only verified known
            # crypto symbols to prevent their fills appearing in stock history.
            fills = [f for f in fills if f.get("symbol") not in crypto_symbols]
        open_error = "alpaca_paper_open_order_page_full" if len(open_orders) + len(other_open_orders) >= 500 else None
        return {
            "account": account,
            "positions": positions,
            "other_positions": other_positions,
            "orders": list(orders.values()),
            "open_orders": open_orders,
            "other_open_orders": other_open_orders,
            "fills": fills,
            "history": history,
            "warnings": {
                name: error
                for name, error in (
                    ("order_history", order_error),
                    ("open_orders", open_error),
                    ("portfolio_history", history_error),
                    ("fills", fill_error),
                )
                if error
            },
        }

    def clock(self):
        return self.get("/v2/clock")

    def asset(self, symbol):
        return self.get(f"/v2/assets/{symbol}")

    def by_client_id(self, cid):
        if not re.fullmatch(r"(?:swp2|swx1|sws1)-[a-f0-9]{40}", cid):
            raise PaperError("invalid_client_order_id")
        return self.get("/v2/orders:by_client_order_id", {"client_order_id": cid})

    def cancel_short_entry(self, order, intent):
        if not orders_enabled() or short_gate(cover=True):
            raise PaperLocalRefusal("short_cancellation_disabled")
        if (not intent["client_id"].startswith(SHORT_PREFIX)
                or intent_action(intent["client_id"],intent["side"])!=Action.SELL_TO_OPEN_SHORT):
            raise PaperLocalRefusal("short_cancellation_owner_mismatch")
        validated=_validated_order(order,intent)
        identifier=validated["id"]
        if validated["status"] in TERMINAL or not re.fullmatch(r"[A-Za-z0-9-]{1,80}",identifier):
            raise PaperLocalRefusal("short_cancellation_identity_invalid")
        self._request("DELETE",f"/v2/orders/{identifier}")

    def submit(self, payload, *, phase=None):
        if not orders_enabled():
            raise PaperLocalRefusal("alpaca_paper_orders_disabled")
        cid = payload.get("client_order_id", "")
        if not re.fullmatch(r"(?:swp2|swx1|sws1)-[a-f0-9]{40}", cid):
            raise PaperError("invalid_client_order_id")
        side = payload.get("side")
        if side not in ("buy", "sell") or payload.get("time_in_force") != "day" or money(payload.get("qty")) <= 0:
            raise PaperError("unsafe_order_request")
        if cid.startswith((INTRADAY_PREFIX,SHORT_PREFIX)):
            short = cid.startswith(SHORT_PREFIX)
            gate = short_gate(cover=side=="buy") if short else order_gate()
            if gate:
                raise PaperLocalRefusal(gate)
            now = self.now()
            live_phase = phase_at(now)
            if (phase is None or phase != live_phase or phase.name not in TRADABLE_PHASES
                    or not phase.start+timedelta(seconds=15) <= now < phase.end-timedelta(seconds=45)
                    or (short and phase.name!="CORE")
                    or payload.get("type") != "limit"
                    or payload.get("extended_hours") is not (phase.name != "CORE")
                    or set(payload) != {"side","symbol","type","qty","limit_price","time_in_force",
                                        "extended_hours","client_order_id"}
                    or not isinstance(payload["symbol"], str)
                    or not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", payload["symbol"])
                    or not isinstance(payload["qty"], str)
                    or not re.fullmatch(r"[0-9]+", payload["qty"])
                    or money(payload.get("limit_price")) < 1
                    or money(payload["limit_price"]) % Decimal(".01")):
                raise PaperLocalRefusal("unsafe_intraday_order_request")
        elif (payload.get("extended_hours") is not False
              or payload.get("type") != ("limit" if side == "buy" else "market")
              or (side == "buy" and money(payload.get("limit_price")) <= 0)):
            raise PaperError("unsafe_order_request")
        return self._request("POST", "/v2/orders", json=payload)


def masked_account(account):
    number = str(account.get("account_number") or "")
    return ("…" + number[-4:]) if number else "verified"


def account_ui(snapshot):
    a = snapshot["account"]
    positions = snapshot["positions"]
    equity = safe_number(a.get("equity"), None)
    cash = safe_number(a.get("cash"), None)
    last_equity = safe_number(a.get("last_equity"))
    long_exposure = sum(abs(safe_number(p.get("market_value"))) for p in positions if p.get("side")=="long")
    short_exposure = sum(abs(safe_number(p.get("market_value"))) for p in positions if p.get("side")=="short")
    exposure = sum(abs(safe_number(p.get("market_value"))) for p in positions)
    history = snapshot["history"] or {}
    times, equities = history.get("timestamp", []), history.get("equity", [])
    curve = []
    if isinstance(times, list) and isinstance(equities, list):
        for t, val in zip(times, equities):
            if safe_number(val) <= 0 or not isinstance(t, (int, float)):
                continue
            try:
                stamp = datetime.fromtimestamp(t, UTC).isoformat()
            except (ValueError, OverflowError, OSError):
                continue
            curve.append({"day": stamp, "equity": safe_number(val), "spy_close": None})
    base = safe_number(history.get("base_value")) or (curve[0]["equity"] if curve else equity)
    delta = equity - last_equity if last_equity and equity is not None else None
    pnl_pct = delta / last_equity * 100 if delta is not None else None
    high = max((x["equity"] for x in curve), default=0)
    drawdown = max(0, (high - equity) / high * 100) if high and equity is not None else None
    ui_positions = [
        {
            "symbol": p.get("symbol"),
            "qty": safe_number(p.get("qty")),
            "direction": str(p.get("side","unknown")).upper(),
            "absolute_exposure": abs(safe_number(p.get("market_value"))),
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
    open_ids = {o.get("id") for o in snapshot.get("open_orders", [])}
    orders = [
        {
            "id": o.get("id"),
            "client_order_id": o.get("client_order_id"),
            "symbol": o.get("symbol"),
            "side": str(o.get("side", "")).upper(),
            "state": str(o.get("status", "")).upper(),
            "qty": o.get("qty"),
            "filled_qty": o.get("filled_qty"),
            "filled_avg_price": o.get("filled_avg_price"),
            # Prices and lifecycle details are broker-reported, never inferred
            # from research candidates or local unacknowledged intents.
            "type": o.get("type"),
            "order_class": o.get("order_class"),
            "limit_price": o.get("limit_price"),
            "stop_price": o.get("stop_price"),
            "take_profit_price": o.get("limit_price") if o.get("order_class") == "oco" and o.get("side") == "sell" else None,
            "created_at": o.get("created_at"),
            "submitted_at": o.get("submitted_at"),
            "filled_at": o.get("filled_at"),
            "signal_day": None,
            "broker_order": True,
            "managed": str(o.get("client_order_id") or "").startswith((PREFIX,INTRADAY_PREFIX,SHORT_PREFIX)),
        }
        for o in snapshot["orders"]
    ]
    fills = [
        {
            "id": f.get("id"),
            "symbol": f.get("symbol"),
            "side": str(f.get("side", "")).upper(),
            "qty": safe_number(f.get("qty")),
            "price": safe_number(f.get("price")),
            "created_at": f.get("transaction_time") or f.get("date"),
            "order_id": f.get("order_id"),
            "source": "ALPACA_PAPER_FILLS",
            "broker_fill": True,
        }
        for f in (snapshot["fills"] or [])
    ]
    return {
        "account": {
            "currency": "USD",
            "initial_cash": base,
            "cash": cash,
            "equity": equity,
            "exposure": exposure,
            "long_exposure":long_exposure,"short_exposure":short_exposure,
            "net_exposure":long_exposure-short_exposure,
            "realized_scope":"BROKER_ACCOUNT_REALIZED_NOT_PROVIDED",
            "unrealized": sum(p["unrealized"] for p in ui_positions),
            "realized": None,
            "drawdown_pct": round(drawdown, 3) if drawdown is not None else None,
            "pnl": round(delta, 2) if delta is not None else None,
            "pnl_pct": round(pnl_pct, 3) if pnl_pct is not None else None,
            "buying_power": safe_number(a.get("buying_power"), None),
            "daytrading_buying_power": safe_number(a.get("daytrading_buying_power")),
            "paused": bool(
                (one("SELECT paused FROM sw_alpaca_state WHERE id=1") or {}).get("paused", 1)
            ),
            "account_masked": masked_account(a),
            "broker": "Alpaca Paper",
            "pnl_period": "day",
        },
        "positions": ui_positions,
        "equity_curve": curve,
        "pending_orders": [o for o in orders if o["id"] in open_ids],
        "order_history": [o for o in orders if o["id"] not in open_ids],
        "fills": fills,
        "last_fill": {
            "last_buy": next((f["created_at"] for f in fills if f["side"] == "BUY"), None),
            "last_sell": next((f["created_at"] for f in fills if f["side"] == "SELL"), None),
        },
        "broker_account": {
            "masked": masked_account(a),
            "status": "CONNECTED",
            "as_of": utc(),
            "source": "Alpaca Paper Trading API",
            "order_submission_enabled": orders_enabled(),
            "account_status": a.get("status"),
            "warnings": snapshot.get("warnings", {}),
        },
    }


def _publish_snapshot(snapshot=None, error=None):
    global _last_view, _last_sync, _sync_error
    view = account_ui(snapshot) if snapshot is not None else None
    with _view_lock:
        if view is not None:
            _last_view, _last_sync = view, time.monotonic()
        if error in {
            "alpaca_paper_account_mismatch",
            "alpaca_paper_linked_account_mismatch",
            "alpaca_paper_http_401",
            "alpaca_paper_http_403",
        }:
            _last_view = None
        _sync_error = error


def _refresh_market_clock(client, now):
    """Read Alpaca Paper's authoritative US equity session clock.

    This is read-only and independent of trading permissions. A failure never
    prevents broker reconciliation, position protection, or the status API.
    """
    global _market_clock
    observed_at = utc()
    try:
        clock = client.clock()
        if not isinstance(clock, dict) or type(clock.get("is_open")) is not bool:
            raise PaperError("alpaca_market_clock_invalid")
        source_time = instant(clock["timestamp"])
        next_open = instant(clock["next_open"])
        next_close = instant(clock["next_close"])
        if abs((source_time - now).total_seconds()) > 180:
            raise PaperError("alpaca_market_clock_stale")
        if clock["is_open"] and next_close <= source_time:
            raise PaperError("alpaca_market_clock_next_close_invalid")
        if not clock["is_open"] and next_open <= source_time:
            raise PaperError("alpaca_market_clock_next_open_invalid")
        reading = {
            "verified": True,
            "is_open": clock["is_open"],
            "checked_at": observed_at,
            "broker_time": source_time.isoformat(),
            "next_open": next_open.isoformat(),
            "next_close": next_close.isoformat(),
        }
    except (PaperError, KeyError, ValueError, TypeError, OverflowError) as exc:
        # Do not assume CLOSED when the clock cannot be verified.
        code = str(exc) if isinstance(exc, PaperError) else "alpaca_market_clock_invalid"
        reading = {"verified": False, "checked_at": observed_at, "reason": code}
    with _view_lock:
        _market_clock = reading


def broker_market_clock():
    with _view_lock:
        return dict(_market_clock)


def broker_symbols():
    with _view_lock:
        return [p["symbol"] for p in (_last_view or {}).get("positions", [])]


def broker_status():
    with _view_lock:
        account = dict((_last_view or {}).get("broker_account", {}))
        state = (
            "CONNECTED"
            if account and not _sync_error and time.monotonic() - _last_sync <= SYNC_MAX_AGE
            else ("STALE" if account else "DISCONNECTED" if _sync_error else "CONNECTING")
        )
        reason = _sync_error or ("alpaca_paper_sync_stale" if state == "STALE" else None)
    paused = bool((one("SELECT paused FROM sw_alpaca_state WHERE id=1") or {}).get("paused", 1))
    return {
        **account,
        "mode": "ALPACA_PAPER",
        "broker": state,
        "status": state,
        "reason": reason,
        "orders_enabled": orders_enabled(),
        "paused": paused,
    }


def enrich_dashboard(local):
    status = broker_status()
    with _view_lock:
        view = _last_view
    if (
        status["status"] == "CONNECTED"
        and view
        and view["broker_account"]["as_of"] == status.get("as_of")
    ):
        local.update(view)
        local["account"] = {**local["account"], "paused": status["paused"]}
    local.update(
        {
            "paper_only": True,
            "execution_mode": "ALPACA_PAPER",
            "can_issue_live_orders": False,
            "broker_account": status,
            "benchmark_change_pct": None,
        }
    )
    local["legacy_local_pending_orders"] = rows(
        "SELECT id,symbol,side,signal_day,state,created_at FROM pending_orders WHERE state='PENDING' ORDER BY created_at"
    )
    local["broker_intents"] = (
        rows("""SELECT client_id,signal_day,symbol,side,qty,reason,state,broker_status,
        updated_at,detail_json FROM sw_alpaca_intents ORDER BY created_at DESC LIMIT 50""")
    )
    for intent in local["broker_intents"]:
        detail = json.loads(intent.pop("detail_json"))
        intent["diagnostic"] = detail.get("reason")
        intent["limit_price"] = detail.get("limit_price")
        intent["type"] = detail.get("type")
        intent["time_in_force"] = detail.get("time_in_force")
    return local


def set_broker_paused(paused):
    with _admission, connect() as c:
        if not paused and not orders_enabled():
            raise PaperError("alpaca_paper_orders_disabled")
        c.execute("UPDATE sw_alpaca_state SET paused=? WHERE id=1", (int(paused),))
    return {"paused": paused, "mode": "alpaca_paper"}


def cid_for(account_id, symbol, day, side):
    return (
        PREFIX
        + hashlib.sha256(f"paper2|{account_id}|{day}|{symbol}|{side}".encode()).hexdigest()[:40]
    )


def _intent(c, cid, account_id, day, symbol, side, qty, reason, payload=None):
    """Persist the intent BEFORE the network call; unknown outcomes never retry blindly."""
    t = utc()
    detail = {
        k: payload[k] for k in ("type", "limit_price", "time_in_force", "extended_hours", "session", "action", "risk") if payload and k in payload
    }
    if cid.startswith((PREFIX,INTRADAY_PREFIX,SHORT_PREFIX)):
        detail.setdefault("action",intent_action(cid,side).value)
    cur = c.execute(
        """INSERT OR IGNORE INTO sw_alpaca_intents
        (client_id,account_id,signal_day,symbol,side,qty,reason,state,created_at,updated_at,detail_json)
        VALUES(?,?,?,?,?,?,?,'PREPARED',?,?,?)""",
        (cid, account_id, day, symbol, side, str(qty), reason, t, t, json.dumps(detail)),
    )
    return cur.rowcount == 1


def _state(cid, status, order=None, reason=""):
    with connect() as c:
        c.execute(
            """UPDATE sw_alpaca_intents SET state=?,broker_order_id=?,broker_status=?,updated_at=?,
                       detail_json=json_patch(detail_json, ?) WHERE client_id=?""",
            (
                status,
                str(order.get("id") or "") if isinstance(order, dict) else None,
                str(order.get("status") or "") if isinstance(order, dict) else None,
                utc(),
                json.dumps({"reason":reason, **({"filled_qty":str(order["filled_qty"])}
                    if cid.startswith((INTRADAY_PREFIX,SHORT_PREFIX)) and order and "filled_qty" in order else {})}),
                cid,
            ),
        )


def money(value, fallback=None):
    try:
        parsed = Decimal(str(value))
        if parsed.is_finite():
            return parsed
    except InvalidOperation:
        pass
    if fallback is not None:
        return fallback
    raise PaperError("alpaca_paper_invalid_numeric_evidence")


def _linked_account(account_id):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute(
            "SELECT 1 FROM sw_alpaca_intents WHERE account_id!=? LIMIT 1", (account_id,)
        ).fetchone():
            raise PaperError("alpaca_paper_linked_account_mismatch")
        c.execute(
            "UPDATE sw_alpaca_state SET linked_account=?,linked_at=? WHERE id=1 AND linked_account IS NULL",
            (account_id, utc()),
        )
        linked = c.execute("SELECT linked_account FROM sw_alpaca_state WHERE id=1").fetchone()
        if linked is None or linked["linked_account"] != account_id:
            raise PaperError("alpaca_paper_linked_account_mismatch")
        c.commit()


def _validated_order(order, intent):
    if (
        not isinstance(order, dict)
        or not order.get("id")
        or order.get("status") not in ORDER_STATES
        or order.get("client_order_id") != intent["client_id"]
        or order.get("symbol") != intent["symbol"]
        or order.get("side") != intent["side"].lower()
        or money(order.get("qty")) != money(intent["qty"])
    ):
        raise PaperError("alpaca_paper_order_identity_mismatch")
    if intent["client_id"].startswith((INTRADAY_PREFIX,SHORT_PREFIX)):
        detail = json.loads(intent["detail_json"])
        if intent["client_id"].startswith(SHORT_PREFIX) and detail.get("action")!=intent_action(intent["client_id"],intent["side"]).value:
            raise PaperError("alpaca_short_intent_action_mismatch")
        filled = money(order.get("filled_qty"))
        if (not 0 <= filled <= money(intent["qty"])
                or (order["status"] == "filled" and filled != money(intent["qty"]))
                or (intent.get("broker_order_id") and intent["broker_order_id"] != order["id"])
                or order["status"] == "replaced"
                or order.get("extended_hours") is not detail.get("extended_hours")
                or order.get("type") != detail.get("type")
                or order.get("time_in_force") != detail.get("time_in_force")
                or money(order.get("limit_price")) != money(detail.get("limit_price"))):
            raise PaperError("alpaca_intraday_order_identity_mismatch")
    return order


def _reconcile(client, account_id, open_orders):
    local = rows(
        """SELECT * FROM sw_alpaca_intents WHERE account_id=?
        AND state IN ('PREPARED','UNKNOWN','ACKNOWLEDGED') ORDER BY created_at,client_id""",
        (account_id,),
    )
    by_client = {order.get("client_order_id"): order for order in open_orders}
    unresolved = 0
    for intent in local:
        cid = intent["client_id"]
        if intent["reason"] == "broker_order_without_local_intent":
            unresolved += 1
            continue
        try:
            order = by_client.get(cid) or client.by_client_id(cid)
            if order is None:
                unresolved += 1
                continue
            order = _validated_order(order, intent)
        except PaperError:
            # Continue reconciling the other intents. Never unlock a missing or mismatched intent.
            unresolved += 1
            continue
        terminal = order["status"] in TERMINAL
        if cid.startswith((INTRADAY_PREFIX,SHORT_PREFIX)) and not terminal and cid not in by_client:
            unresolved += 1
            continue
        _state(cid, "TERMINAL" if terminal else "ACKNOWLEDGED", order)
    return unresolved


def _position_owned(position, fills, account_id, actions_since=None, *, prefix=PREFIX):
    """Require a known strategy entry and an uninterrupted broker fill trail."""
    if fills is None:
        return False
    intents = rows(
        """SELECT side,broker_order_id,created_at,signal_day FROM sw_alpaca_intents
        WHERE account_id=? AND symbol=? AND broker_order_id IS NOT NULL AND client_id LIKE ?
        ORDER BY created_at DESC,client_id DESC""",
        (account_id, position["symbol"], prefix+"%"),
    )
    entry = next((intent for intent in intents if intent["side"] == "BUY"), None)
    if not entry or (actions_since and actions_since > entry["signal_day"]):
        return False
    start = instant(entry["created_at"])
    try:
        stamped = [(instant(f["transaction_time"]), f) for f in fills]
        if len(fills) >= FILL_PAGE_SIZE and min(t for t, _ in stamped) >= start:
            return False
        after = [f for t, f in stamped if t >= start and f.get("symbol") == position["symbol"]]
        allowed = {
            i["broker_order_id"]: i["side"].lower()
            for i in intents
            if i["created_at"] >= entry["created_at"]
        }
        allowed = {
            oid: side
            for oid, side in allowed.items()
            if side == "sell" or oid == entry["broker_order_id"]
        }
        if (
            not any(f.get("order_id") == entry["broker_order_id"] for f in after)
            or len({f["id"] for f in after}) != len(after)
            or any(allowed.get(f["order_id"]) != f["side"] or money(f["qty"]) <= 0 for f in after)
        ):
            return False
        qty = sum((money(f["qty"]) * (1 if f["side"] == "buy" else -1) for f in after), Decimal(0))
        return qty == money(position["qty"]) == money(position.get("qty_available")) > 0
    except (KeyError, ValueError, TypeError, PaperError):
        return False


def _open_window(client, day, now):
    bounds = session(next_day(day))
    if not bounds[0] <= now < min(bounds[0] + OPEN_WINDOW, bounds[1]):
        return False
    clock = client.clock()
    try:
        stamp = instant(clock["timestamp"])
        return (
            clock["is_open"] is True
            and abs(stamp - now) <= timedelta(seconds=30)
            and bounds[0] <= stamp < bounds[0] + OPEN_WINDOW
            and instant(clock["next_close"]) == bounds[1]
        )
    except (KeyError, ValueError, TypeError):
        return False


def _record_verified_account_peak(snapshot):
    """Remember a genuine Alpaca portfolio-history peak on routine broker GETs.

    Without this, the fail-closed fallback would have no evidence unless a
    stock BUY happened to reach the allocation stage before the outage.
    No invented values, no orders, and no change to drawdown thresholds.
    """
    account=snapshot.get("account") or {}
    identifier=account.get("id")
    history=snapshot.get("history") or {}
    values=history.get("equity",[])
    if not identifier or not isinstance(values,list):
        return False
    marks=[money(x,Decimal(0)) for x in values if x is not None]
    verified=[x for x in marks if x>0]
    eq=money(account.get("equity"),Decimal(0))
    if not verified or eq<=0:
        return False
    saved=one("SELECT high_water FROM sw_paper_risk_peaks WHERE account_id=?",
              (identifier,))
    high=max(verified+[eq,money(saved["high_water"]) if saved else Decimal(0)])
    with connect() as c:
        c.execute("""INSERT INTO sw_paper_risk_peaks(account_id,high_water,verified_at)
          VALUES(?,?,?) ON CONFLICT(account_id) DO UPDATE SET
          high_water=excluded.high_water,verified_at=excluded.verified_at""",
          (identifier,str(high),utc()))
    return True


def _entry_budget(snapshot, sectors, sector, active, known):
    account = snapshot["account"]
    eq, cash, last, cash_buying_power = (
        money(account.get(k))
        for k in (
            "equity",
            "cash",
            "last_equity",
            "non_marginable_buying_power",
        )
    )
    if short_gate(cover=True) is None:
        from .intraday_store import daily_loss_paused
        now=datetime.now(UTC)
        if last<=0 or daily_loss_paused(account["id"],now.astimezone(NY).date().isoformat(),
                                       eq<=last*Decimal(".98"),now):
            raise PaperError("alpaca_shared_daily_loss_pause")
    if min(eq, last) <= 0 or cash < 0:
        raise PaperError("alpaca_paper_invalid_account_balance")
    history = snapshot.get("history") or {}
    values = history.get("equity", [])
    if not isinstance(values, list):
        values = []
    marks = [money(x, Decimal(0)) for x in values if x is not None]
    verified = [x for x in marks if x > 0]
    recorded = one("SELECT * FROM sw_paper_risk_peaks WHERE account_id=?",
                   (account["id"],))
    prior_peak = money(recorded["high_water"]) if recorded else Decimal(0)
    if verified:
        # Do not erase a previously observed peak when Alpaca returns a
        # rolling one-month window. Persist only independently verified truth.
        peak = max([eq,prior_peak]+verified)
        with connect() as c:
            c.execute("""INSERT INTO sw_paper_risk_peaks(account_id,high_water,verified_at)
                VALUES(?,?,?) ON CONFLICT(account_id) DO UPDATE SET
                high_water=excluded.high_water,verified_at=excluded.verified_at""",
                (account["id"],str(peak),utc()))
    elif recorded:
        # A recent, previously broker-verified high-water can bridge a brief
        # history API outage, but never invent one from current account equity.
        age=datetime.now(UTC)-instant(recorded["verified_at"])
        if not timedelta(0)<=age<=timedelta(days=3) or prior_peak<=0:
            raise PaperError("alpaca_paper_risk_history_missing_or_stale")
        peak=max(eq,prior_peak)
    else:
        raise PaperError("alpaca_paper_risk_history_never_verified")
    if 1 - eq / peak >= money(MAX_DRAWDOWN) or 1 - eq / last >= money(MAX_ONE_DAY_LOSS):
        raise PaperError("alpaca_paper_drawdown_or_daily_loss_pause")
    gross = sector_used = reserved = cash_reserved = short_proceeds = Decimal(0)
    for sym, raw in known.items():
        if not sectors.get(sym):
            raise PaperError("alpaca_paper_external_position_unclassified")
        try:
            holding=normalized_position(raw)
        except ValueError:
            # Older long fixtures/legacy responses may lack cost basis, which
            # is required only to prevent spending short proceeds.
            if raw.get("side")!="long" or raw.get("asset_class")!="us_equity" or money(raw.get("qty"))<=0:
                raise PaperError("alpaca_paper_invalid_position_value") from None
            value=money(raw.get("market_value"))
            if value<=0:
                raise PaperError("alpaca_paper_invalid_position_value")
        else:
            value=holding.gross
            short_proceeds+=holding.proceeds
        gross+=value
        if sectors[sym]==sector:
            sector_used+=value

    # Shared Alpaca Paper cash and equity also fund crypto inventory. Count
    # crypto holdings toward the gross-exposure ceiling; never budget the
    # same account equity independently for both strategies.
    for crypto_position in snapshot.get("other_positions", []):
        if crypto_position.get("side") != "long":
            raise PaperError("alpaca_shared_account_crypto_inventory_invalid")
        gross += abs(money(crypto_position.get("market_value")))

    reserved_symbols = set()
    from .profit_oco import recognized_order_ids
    protection_orders=recognized_order_ids(account.get("id"))
    for order in active:
        sym = order.get("symbol")
        if (
            not order.get("owned_intent")
            or not sectors.get(sym)
            or order.get("side") not in ("buy", "sell")
        ):
            raise PaperError("alpaca_paper_external_or_unclassified_open_order")
        try:
            action=(Action.SELL_TO_CLOSE_LONG if order.get("id") in protection_orders
                    and order["side"]=="sell" else
                    intent_action(order.get("client_order_id",""),order["side"]))
        except ValueError:
            if order.get("client_order_id"):
                raise PaperError("alpaca_paper_unknown_order_direction") from None
            action=Action.BUY_TO_OPEN_LONG if order["side"]=="buy" else Action.SELL_TO_CLOSE_LONG
        if action.opening or action==Action.BUY_TO_COVER_SHORT:
            price=money(order.get("limit_price"))
            qty=money(order.get("qty"))-money(order.get("filled_qty"))
            if price<=0 or qty<0:
                raise PaperError("alpaca_paper_open_buy_reserve_unverifiable")
            if action.opening:
                reserved+=price*qty
                reserved_symbols.add(sym)
                if sectors[sym]==sector:
                    sector_used+=price*qty
            cash_reserved+=price*qty
    if len(set(known) | reserved_symbols) >= MAX_POSITIONS:
        raise PaperError("alpaca_paper_position_cap")
    return min(
        eq * money(MAX_SYMBOL_WEIGHT),
        eq * money(MAX_SECTOR_WEIGHT) - sector_used,
        eq * money(MAX_GROSS_EXPOSURE) - gross - reserved,
        cash - short_proceeds - eq * CASH_BUFFER - cash_reserved,
        cash_buying_power - short_proceeds - cash_reserved,
    )


def _payload_for(client, snapshot, signal, target, active, known, sectors, account_id, *, entry_limit=None):
    symbol = signal["symbol"]
    if any(o.get("symbol") == symbol for o in active):
        raise PaperError("alpaca_paper_symbol_has_open_order")
    if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", symbol):
        raise PaperError("alpaca_paper_symbol_invalid")
    if symbol not in known:
        if signal["score"] < SCORE_MIN or signal["regime"] != "RISK_ON":
            raise PaperError("alpaca_paper_score_or_regime_gate")
        if signal["features"]["volatility_annual"] >= MAX_VOLATILITY:
            raise PaperError("alpaca_paper_volatility_cap")
        if signal["iex_dollar_volume_20d"] < MIN_IEX_DOLLAR_VOLUME:
            raise PaperError("alpaca_paper_liquidity_gate")
    asset = client.asset(symbol)
    if (
        not isinstance(asset, dict)
        or asset.get("symbol") != symbol
        or asset.get("class") != "us_equity"
        or asset.get("status") != "active"
        or asset.get("tradable") is not True
    ):
        raise PaperError("alpaca_paper_asset_not_tradable")
    check = one("SELECT * FROM sw_price_checks WHERE symbol=? AND day=?", (symbol, signal["day"]))
    if (
        not check
        or instant(check["checked_at"]).astimezone(NY).date().isoformat() != target
        or any(e["day"] == target for e in json.loads(check["actions_json"]))
    ):
        raise PaperError("alpaca_paper_execution_day_corporate_action_check_missing_or_blocked")
    px = money(signal["features"]["close"])
    if symbol in known:
        # Retain the conservative recent share-change gate for broker-owned inventory.
        if any(e["kind"] != "cash_dividends" for e in json.loads(check["actions_json"])):
            raise PaperError("alpaca_paper_corporate_action_requires_reconciliation")
        position = known[symbol]
        if (
            position.get("side") != "long"
            or position.get("asset_class") != "us_equity"
            or position.get("asset_id") != asset.get("id")
            or not asset.get("id")
            or not check["actions_since"]
            or not _position_owned(position, snapshot["fills"], account_id, check["actions_since"])
        ):
            raise PaperError("alpaca_paper_external_or_unverified_position")
        avg = money(position.get("avg_entry_price"))
        if avg <= 0:
            raise PaperError("alpaca_paper_position_cost_unavailable")
        if px <= avg * Decimal("0.92"):
            reason = "eod_stop"
        elif px < money(signal["features"]["sma50"]) * Decimal("0.96") or signal["score"] < 0.8:
            reason = "eod_trend_exit"
        else:
            raise PaperError("alpaca_paper_no_exit_trigger")
        return {
            "side": "sell",
            "qty": format(money(position["qty"]), "f"),
            "type": "market",
        }, reason

    sector = sectors.get(symbol)
    if not sector or sector == "Benchmark":
        raise PaperError("alpaca_paper_unknown_sector")
    budget = _entry_budget(snapshot, sectors, sector, active, known)
    ceiling = (px * Decimal("1.005")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    limit = money(entry_limit) if entry_limit is not None else ceiling
    if limit < Decimal("0.01") or limit > ceiling or limit != limit.quantize(Decimal("0.01")):
        raise PaperError("adaptive_limit_outside_certified_price_cap")
    qty = int(max(Decimal(0), budget) / limit / Decimal("1.01")) if limit >= 1 else 0
    if qty < 1:
        raise PaperError("alpaca_paper_cash_or_exposure_cap")
    return {
        "side": "buy",
        "qty": str(qty),
        "type": "limit",
        "limit_price": str(limit),
    }, "certified_eod_signal"


def _preview_and_submit(client, snapshot, signals, day, now, *, protection=None):
    result = {
        "status": "NO_APPROVED_BROKER_SIGNAL",
        "processed": len(signals),
        "orders_queued": 0,
        "next_core_open": session(next_day(day))[0].isoformat(),
        "broker_orders_submitted": 0,
        "market_day": day,
        "why_no_trade": [],
        "mode": "ALPACA_PAPER",
        "at": utc(),
        "signals": [
            {k: s[k] for k in ("symbol", "name", "sector", "score", "regime", "signals", "reasons")}
            for s in signals
        ],
    }
    if not signals or day != completed_day(now):
        return {**result, "status": "NO_CERTIFIED_CURRENT_SIGNALS"}
    if not _open_window(client, day, now):
        # The regular session or limited opening admission window is closed.
        # Preserve ticker-level technical reasons without pretending the
        # broker's remaining order gates ran (no order calls happen here).
        def closing_reason(signal):
            if signal["score"] < SCORE_MIN or signal["regime"] != "RISK_ON":
                return "technical_score_or_regime_below_gate"
            if signal["features"]["volatility_annual"] >= MAX_VOLATILITY:
                return "technical_volatility_cap"
            if signal["iex_dollar_volume_20d"] < MIN_IEX_DOLLAR_VOLUME:
                return "technical_iex_liquidity_cap"
            return "entry_window_closed_remaining_broker_gates_not_evaluated"
        result["why_no_trade"] = [
            {"symbol": signal["symbol"], "action": "WATCH",
             "reason": closing_reason(signal)} for signal in signals
        ]
        return {**result, "status": "WAITING_FOR_NEXT_CORE_OPEN_WINDOW"}
    account = snapshot["account"]
    if (
        account.get("status") != "ACTIVE"
        or account.get("trading_blocked") is not False
        or account.get("account_blocked") is not False
    ):
        return {**result, "status": "ALPACA_ACCOUNT_TRADING_UNAVAILABLE"}
    active = snapshot["open_orders"]
    # Pending crypto orders reserve shared buying power but cannot preempt
    # an independently owned stock exit. Block only new stock BUY admissions.
    # Final account/positions/order checks still include BOTH asset classes.
    if len(active) >= 500 or any(
        not o.get("symbol") or not o.get("id") or not o.get("status") or o.get("legs")
        for o in active
    ):
        return {**result, "status": "BROKER_OPEN_ORDERS_INCOMPLETE"}
    known = {p.get("symbol"): p for p in snapshot["positions"]}
    if None in known or len(known) != len(snapshot["positions"]):
        return {**result, "status": "BROKER_POSITIONS_INVALID"}
    if any(p.get("side") != "long" or money(p.get("qty")) <= 0 for p in known.values()):
        return {**result, "status": "BROKER_SHORT_OR_INVALID_POSITION"}
    account_id = account["id"]
    intents = rows(
        "SELECT * FROM sw_alpaca_intents WHERE account_id=? AND signal_day=?", (account_id, day)
    )
    all_active = snapshot["open_orders"] + snapshot.get("other_open_orders", [])
    active_ids = {o.get("id") for o in all_active}
    if (len(active_ids)!=len(all_active) or None in active_ids):
        return {**result, "status": "SHARED_BROKER_ORDER_BOOK_UNVERIFIABLE"}
    own_ids = {
        r["broker_order_id"]
        for r in rows(
            "SELECT broker_order_id FROM sw_alpaca_intents WHERE account_id=? AND state='ACKNOWLEDGED'",
            (account_id,),
        )
    }
    from .profit_oco import recognized_order_ids
    own_ids.update(recognized_order_ids(account_id))
    active = [{**o, "owned_intent": o.get("id") in own_ids} for o in active]
    today = {r["symbol"] for r in intents}
    buys_today = sum(r["side"] == "BUY" for r in intents)
    sectors = {r["symbol"]: r["sector"] for r in rows("SELECT symbol,sector FROM assets")}
    # Live-account protection must be verified before any additional BUY.
    # Existing stock/crypto exits are never blocked by this entry-only rule.
    uncovered = []
    protection_missing = False
    if protection is not None:
        from .profit_oco import armed as protection_armed
        proof = {p["symbol"]: p for p in protection.get("positions", [])}
        owned = {r["symbol"] for r in rows("""SELECT DISTINCT symbol FROM sw_alpaca_intents
          WHERE account_id=? AND side='BUY' AND broker_order_id IS NOT NULL
            AND client_id LIKE 'swp2-%'""", (account_id,))}
        uncovered = sorted(
            symbol for symbol in owned & known.keys()
            if proof.get(symbol, {}).get("broker_state") != "ACTIVE"
            or not proof.get(symbol, {}).get("verified_broker_stop")
        )
        protection_missing = (
            not protection_armed() or not protection.get("paper_orders_enabled")
            or protection.get("status") != "PAPER_OCO_MONITORING"
        )
    target = next_day(day)
    for signal in sorted(
        signals, key=lambda s: (s["symbol"] not in known, -s["score"], s["symbol"])
    ):
        symbol = signal["symbol"]
        item = {"symbol": symbol, "action": "WATCH"}
        result["why_no_trade"].append(item)
        if one(
            "SELECT 1 FROM sw_alpaca_intents WHERE account_id=? AND symbol=? AND signal_day=? AND (client_id LIKE ? OR client_id LIKE ?)",
            (account_id, symbol, target, INTRADAY_PREFIX+"%",SHORT_PREFIX+"%"),
        ):
            item["reason"] = "intraday_same_symbol_same_session_interlock"
            continue
        if symbol in today or (symbol not in known and buys_today >= 2):
            item["reason"] = "already_ordered_or_daily_buy_cap"
            continue
        if symbol not in known and not signal.get("ranking_complete", False):
            item["reason"] = "awaiting_completed_universe_scan"
            continue
        if symbol not in known and (one("SELECT paused FROM sw_alpaca_state WHERE id=1") or {}).get("paused",1):
            item["reason"]="new_stock_entry_paused_exit_protection_continues"
            continue
        if symbol not in known and snapshot.get("other_open_orders"):
            item["reason"] = "new_stock_buy_blocked_by_shared_crypto_orders"
            continue
        if symbol not in known and protection is not None and (protection_missing or uncovered):
            item["reason"] = ("stock_protection_not_armed_blocks_new_entry"
                              if protection_missing else "existing_eod_long_unprotected_blocks_new_entry")
            item["unprotected_owned_symbols"] = uncovered
            continue
        # A long with an active, verified broker-native OCO must not receive
        # a second SELL. Request a one-shot reduction of its existing OCO TP
        # limit; its stop remains at the broker throughout the handoff.
        if symbol in known and any(o.get("symbol")==symbol for o in active):
            from .profit_oco import request_strategy_exit
            try:
                handoff=request_strategy_exit(client,snapshot,signal,account_id,now)
            except Exception as exc:
                log.warning("StocksWatch OCO exit handoff failed for %s: %s",
                            symbol,type(exc).__name__)
                handoff="oco_exit_handoff_unavailable_do_not_double_sell"
            item["reason"]=handoff
            if handoff=="oco_exit_replace_requested_keep_existing_stop":
                return {**result, "status": "OCO_EXIT_REPLACE_REQUESTED",
                        "broker_orders_submitted": 0}
            continue
        # A missing OCO in the open book is not proof that it was cancelled
        # or filled. Until independently reconciled, no duplicate stock SELL.
        if symbol in known and one("""SELECT 1 FROM sw_protection WHERE
              account_id=? AND symbol=? AND state IN
              ('ACTIVE','REPLACE_PENDING','REPLACE_UNCERTAIN','UNVERIFIED')""",
              (account_id,symbol)):
            item["reason"]="oco_exit_open_order_missing_requires_reconciliation"
            continue
        entry_limit = None
        if symbol not in known and signal["score"] >= SCORE_MIN and signal["regime"] == "RISK_ON":
            from .entry_execution import mode as entry_mode, observe as observe_entry
            try:
                if entry_mode() == "adaptive":
                    timing = observe_entry(signal, now)
                    item["entry_timing"] = timing
                    if timing["status"] != "READY":
                        item["reason"] = timing["reason"]
                        continue
                    entry_limit = timing["limit_price"]
            except ValueError:
                item["reason"] = "adaptive_entry_configuration_invalid"
                continue
        try:
            payload, reason = _payload_for(
                client, snapshot, signal, target, active, known, sectors, account_id,
                entry_limit=entry_limit,
            )
        except PaperError as exc:
            item["reason"] = str(exc)
            continue
        action = payload["side"].upper()
        cid = cid_for(account_id, symbol, day, action)
        payload.update(
            {
                "symbol": symbol,
                "client_order_id": cid,
                "time_in_force": "day",
                "extended_hours": False,
            }
        )
        with _admission:
            if action == "BUY" and (one("SELECT paused FROM sw_alpaca_state WHERE id=1") or {}).get("paused", 1):
                return {**result, "status": "BROKER_NEW_ENTRIES_PAUSED"}
            if client.by_client_id(cid):
                item["reason"] = "broker_order_already_exists"
                # A broker order without a durable local intent needs operator review.
                return {**result, "status": "BROKER_ORDER_WITHOUT_LOCAL_INTENT"}
            # Recheck the independently mutable broker state just before reserving.
            fresh_account = client.account()
            fresh_positions = client.get("/v2/positions")
            fresh_orders = client.get(
                "/v2/orders", {"status": "open", "limit": 500, "nested": "false"}
            )

            from .broker_shared_state import shared_state_matches
            if (
                any(
                    fresh_account.get(k) != account.get(k)
                    for k in (
                        "id",
                        "cash",
                        "last_equity",
                        "status",
                        "account_blocked",
                        "trading_blocked",
                    )
                )
                or not shared_state_matches(snapshot,fresh_positions,fresh_orders)
            ):
                return {**result, "status": "BROKER_STATE_CHANGED_RECHECK_NEXT_CYCLE"}
            if action == "BUY":
                fresh_budget = _entry_budget(
                    {**snapshot, "account": fresh_account},
                    sectors,
                    sectors[symbol],
                    active,
                    {p["symbol"]: p for p in fresh_positions},
                )
                if (
                    money(payload["qty"]) * money(payload["limit_price"]) * Decimal("1.01")
                    > fresh_budget
                ):
                    return {**result, "status": "BROKER_BUDGET_CHANGED_RECHECK_NEXT_CYCLE"}
            if action == "SELL":
                fills = client.get(
                    "/v2/account/activities/FILL",
                    {
                        "direction": "desc",
                        "page_size": FILL_PAGE_SIZE,
                    },
                )
                if not isinstance(fills, list) or not _position_owned(
                    known[symbol], fills, account_id
                ):
                    return {**result, "status": "BROKER_OWNERSHIP_CHANGED_RECHECK_NEXT_CYCLE"}
            if not _open_window(client, day, datetime.now(UTC)):
                return {**result, "status": "EXECUTION_WINDOW_CLOSED"}
            with connect() as c:
                c.execute("PRAGMA synchronous=FULL")
                fresh = _intent(
                    c, cid, account_id, day, symbol, action, payload["qty"], reason, payload
                )
            if not fresh:
                return {**result, "status": "EXISTING_INTENT"}
            try:
                order = _validated_order(
                    client.submit(payload),
                    {
                        "client_id": cid,
                        "symbol": symbol,
                        "side": action,
                        "qty": payload["qty"],
                    },
                )
            except PaperRejection as exc:
                _state(cid, "REJECTED", reason=str(exc))
                item["reason"] = str(exc)
                return {**result, "status": "BROKER_REJECTED"}
            except PaperError as exc:
                _state(cid, "UNKNOWN", reason=str(exc))
                item["reason"] = "broker_order_outcome_uncertain_do_not_retry"
                log.warning("Alpaca paper order outcome uncertain for %s (%s)", symbol, exc)
                return {**result, "status": "BROKER_ORDER_UNCERTAIN"}
            status = order["status"]
            _state(cid, "TERMINAL" if status in TERMINAL else "ACKNOWLEDGED", order)
            item.update({"action": action, "reason": f"broker_{status}"})
            return {
                **result,
                "status": "BROKER_REJECTED" if status == "rejected" else "BROKER_ACKNOWLEDGED",
                "broker_orders_submitted": 1,
            }
    # A wall-clock WAITING display hid thousands of substantive safety
    # rejections. Preserve the exact per-symbol reasons and report the
    # protection interlock explicitly whenever new BUYs are suppressed.
    blocking={"stock_protection_not_armed_blocks_new_entry",
              "existing_eod_long_unprotected_blocks_new_entry"}
    if any(item.get("reason") in blocking for item in result["why_no_trade"]):
        result["status"]="BLOCKED_BY_PROTECTION"
        result["reason"]="existing_oco_protection_needs_broker_verification"
    return result


def _record_broker_cycle(result, now):
    # Broker GET failures and rejected decisions are valuable audit evidence.
    # This write never changes brokerage intent, quantities or account P&L.
    try:
        observed = now or datetime.now(UTC)
        record = json.dumps(result, default=str, separators=(",", ":"))
        with connect() as c:
            c.execute("""INSERT OR REPLACE INTO sw_broker_decision_cycles
              (at,session_day,status,reason,result_json) VALUES(?,?,?,?,?)""",
              (observed.isoformat(),observed.astimezone(NY).date().isoformat(),
               result.get("status","UNKNOWN"),result.get("reason"),record))
    except Exception as exc:
        log.warning("StocksWatch decision audit write unavailable: %s",type(exc).__name__)


def paper_cycle(now=None):
    with broker_cycle_lock:
        result = _paper_cycle(now)
        _record_broker_cycle(result,now)
        return result


def _paper_cycle(now=None):
    real_clock = now is None
    now = now or datetime.now(UTC)
    result = {
        "mode": "ALPACA_PAPER",
        "market_day": completed_day(now),
        "orders_queued": 0,
        "at": utc(),
    }
    try:
        with PaperClient() as client:
            # Safe GET retries only. Keep constructor ABI for injected broker fakes.
            if hasattr(client, 'retry_reads'):
                client.retry_reads = True
            snapshot = client.snapshot()
            account_id = snapshot["account"]["id"]
            _linked_account(account_id)
            # Populate verified risk evidence every broker cycle, not only
            # when a rare new stock BUY reaches its budget calculation.
            try:
                _record_verified_account_peak(snapshot)
            except Exception as exc:
                log.warning("StocksWatch broker high-water observation unavailable: %s",
                            type(exc).__name__)
            _publish_snapshot(snapshot)
            _refresh_market_clock(client, now)
            unresolved = _reconcile(client, account_id, snapshot["open_orders"])
            if unresolved:
                return {**result, "status": "UNCERTAIN_BROKER_INTENT", "pending_count": unresolved}
            # Broker-native OCO manager executes before new EOD entries under
            # the same broker-cycle lock; no competing duplicate sell orders.
            from . import profit_oco
            try:
                protected = profit_oco.cycle(client, snapshot, now)
            except Exception as exc:
                log.warning("StocksWatch protection monitor unavailable: %s",type(exc).__name__)
                return {**result, "status": "PROTECTION_MONITOR_UNAVAILABLE"}
            if protected.get("changed"):
                # A newly accepted OCO changes broker open-order inventory.
                # Never dispatch EOD orders against the stale snapshot.
                snapshot=client.snapshot()
                _publish_snapshot(snapshot)
            if real_clock:
                now = datetime.now(UTC)
            configuration = execution_configuration_gate()
            signals, day = (
                eligible_signals(now=now, broker=True) if not configuration else ([], None)
            )
            preview = {
                "signals": [
                    {
                        k: s[k]
                        for k in (
                            "symbol",
                            "name",
                            "sector",
                            "score",
                            "regime",
                            "signals",
                            "reasons",
                        )
                    }
                    for s in signals
                ]
            }
            if not orders_enabled():
                return {**result, **preview, "status": "BROKER_READ_ONLY"}
            # The stock pause controls NEW entries, not independently verified
            # exits for owned shares or existing broker-native OCO protection.
            if configuration or day is None:
                return {**result, "status": "NO_CERTIFIED_BENCHMARK", "reason": configuration}
            return _preview_and_submit(client, snapshot, signals, day, now, protection=protected)
    except PaperError as exc:
        if str(exc).startswith("alpaca_paper_http_") or str(exc) in {
            "alpaca_paper_credentials_missing",
            "alpaca_paper_expected_account_not_configured",
            "alpaca_paper_account_mismatch",
            "alpaca_paper_linked_account_mismatch",
            "alpaca_paper_snapshot_incomplete",
            "alpaca_paper_account_unavailable",
            "alpaca_paper_account_not_usd",
            "alpaca_paper_transport_unavailable",
            "alpaca_paper_invalid_json",
        }:
            _publish_snapshot(error=str(exc))
        return {**result, "status": "BROKER_CHECK_FAILED", "reason": str(exc)}


def record_confirmed_absence(client_id, support_case, now=None):
    """Operator recovery for an uncertain submission after external Alpaca confirmation."""
    now = now or datetime.now(UTC)
    if not broker_mode() or orders_enabled():
        raise PaperError("alpaca_paper_read_only_required_for_resolution")
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", support_case):
        raise PaperError("alpaca_paper_support_case_required")
    with _admission:
        state = one("SELECT paused,linked_account FROM sw_alpaca_state WHERE id=1")
        if not state or not state["paused"]:
            raise PaperError("alpaca_paper_pause_required_for_resolution")
        intent = one("SELECT * FROM sw_alpaca_intents WHERE client_id=?", (client_id,))
        if (
            not intent
            or intent["account_id"] != state["linked_account"]
            or intent["state"] not in ("PREPARED", "UNKNOWN")
        ):
            raise PaperError("alpaca_paper_no_matching_uncertain_intent")
        if client_id.startswith((INTRADAY_PREFIX,SHORT_PREFIX)):
            original_session_ended = now.astimezone(NY).date().isoformat() > intent["signal_day"]
        else:
            original_session_ended = now >= session(next_day(intent["signal_day"]))[1]
        if not original_session_ended:
            raise PaperError("alpaca_paper_wait_until_original_session_ends")
        with PaperClient() as client:
            if (
                client.account()["id"] != intent["account_id"]
                or client.by_client_id(client_id) is not None
            ):
                raise PaperError("alpaca_paper_broker_order_exists_or_account_mismatch")
        with connect() as c:
            cur = c.execute(
                """UPDATE sw_alpaca_intents SET state='CONFIRMED_ABSENT',updated_at=?,
                detail_json=json_set(detail_json,'$.reason','operator_confirmed_absence','$.support_case',?)
                WHERE client_id=? AND state IN ('PREPARED','UNKNOWN')""",
                (utc(), support_case, client_id),
            )
            if cur.rowcount != 1:
                raise PaperError("alpaca_paper_intent_changed_during_resolution")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Record broker-confirmed absence of an uncertain paper order"
    )
    parser.add_argument("client_id")
    parser.add_argument("--support-case", required=True)
    parser.add_argument("--alpaca-confirmed-absence", action="store_true", required=True)
    args = parser.parse_args()
    try:
        record_confirmed_absence(args.client_id, args.support_case)
    except PaperError as exc:
        parser.exit(1, f"{exc}\n")
    print("Recorded broker-confirmed absence. The original client order ID remains reserved.")
