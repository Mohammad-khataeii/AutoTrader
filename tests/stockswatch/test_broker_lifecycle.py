"""Use isolated SQLite and HTTP mock transport for the whole broker order path."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest
from stockswatch.sessions import next_day, session

from stockswatch import alpaca_paper as paper
from stockswatch import storage

DAY = "2026-11-05"
TARGET = next_day(DAY)
OPEN, CLOSE = session(TARGET)
NOW = OPEN + timedelta(minutes=15)
ACCOUNT = {
    "id": "offline-paper",
    "account_number": "test1234",
    "currency": "USD",
    "status": "ACTIVE",
    "equity": "100000",
    "last_equity": "100000",
    "cash": "100000",
    "buying_power": "400000",
    "non_marginable_buying_power": "100000",
    "trading_blocked": False,
    "account_blocked": False,
}
SIGNAL = {
    "symbol": "AAPL",
    "name": "Apple",
    "sector": "Technology",
    "day": DAY,
    "score": 3,
    "features": {"close": 100, "sma50": 95, "volatility_annual": 0.2},
    "regime": "RISK_ON",
    "ranking_complete": True,
    "iex_dollar_volume_20d": 2_000_000,
    "signals": {},
    "reasons": [],
}


@pytest.fixture
def setup_broker(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "offline.sqlite3"))
    for k, v in {
        "STOCKSWATCH_EXECUTION_BACKEND": "alpaca_paper",
        "STOCKSWATCH_PRICE_PROVIDER": "alpaca",
        "STOCKSWATCH_ALPACA_KEY": "mock-data-key",
        "STOCKSWATCH_ALPACA_SECRET": "mock-data-secret",
        "STOCKSWATCH_ALPACA_PAPER_KEY": "mock-paper-key",
        "STOCKSWATCH_ALPACA_PAPER_SECRET": "mock-paper-secret",
        "STOCKSWATCH_ALPACA_PAPER_ACCOUNT_ID": ACCOUNT["id"],
        "STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS": "1",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(paper, "_last_view", None)
    monkeypatch.setattr(paper, "_sync_error", None)
    monkeypatch.setattr(paper, "_last_sync", 0.0)
    storage.init()
    storage.init_execution()
    paper.broker_init()
    paper.set_broker_paused(False)
    with storage.connect() as c:
        c.execute(
            "INSERT INTO sw_price_checks VALUES (?,?,?,?,?,?)",
            ("AAPL", DAY, NOW.isoformat(), "OK", DAY, "[]"),
        )
        c.execute(
            "INSERT INTO pending_orders VALUES (?,?,?,?,?,?,?,?)",
            ("legacy", "AAPL", "BUY", DAY, "{}", NOW.isoformat(), "PENDING", None),
        )

    class Broker:
        def __init__(self):
            self.account = dict(ACCOUNT)
            self.positions = []
            self.open_orders = []
            self.fills = []
            self.history = {"equity": [100000]}
            self.orders = {}
            self.posts = []
            self.mode = "accepted"
            self.lookup_hidden = False
            self.clock_open = True
            self.signals = [dict(SIGNAL)]

        def handle(self, request):
            assert request.url.host == "paper-api.alpaca.markets"
            path = request.url.path
            if request.method == "POST":
                payload = json.loads(request.content)
                self.posts.append(payload)
                assert (
                    storage.one(
                        "SELECT state FROM sw_alpaca_intents WHERE client_id=?",
                        (payload["client_order_id"],),
                    )["state"]
                    == "PREPARED"
                )
                if self.mode == "reject":
                    return httpx.Response(
                        403, json={"code": 40310000, "message": "PRIVATE_RESPONSE"}
                    )
                order = {
                    **payload,
                    "id": "order-" + str(len(self.posts)),
                    "status": "accepted",
                    "filled_qty": "0",
                }
                self.orders[payload["client_order_id"]] = order
                if self.mode == "timeout":
                    raise httpx.ReadTimeout("mock response lost after acceptance", request=request)
                self.open_orders.append(order)
                return httpx.Response(200, json=order)
            if path.endswith("by_client_order_id"):
                order = self.orders.get(request.url.params["client_order_id"])
                return (
                    httpx.Response(200, json=order)
                    if order and not self.lookup_hidden
                    else httpx.Response(404)
                )
            if path == "/v2/clock":
                return httpx.Response(
                    200,
                    json={
                        "timestamp": NOW.isoformat(),
                        "is_open": self.clock_open,
                        "next_close": CLOSE.isoformat(),
                    },
                )
            if path == "/v2/orders":
                if request.url.params["status"] == "open":
                    return httpx.Response(200, json=self.open_orders)
                # A full display page cannot block safe decisions on a complete open book.
                return httpx.Response(
                    200, json=[{"id": f"closed-{i}", "status": "filled"} for i in range(100)]
                )
            if path == "/v2/assets/AAPL":
                return httpx.Response(
                    200,
                    json={
                        "id": "aapl",
                        "symbol": "AAPL",
                        "class": "us_equity",
                        "status": "active",
                        "tradable": True,
                    },
                )
            values = {
                "/v2/account": self.account,
                "/v2/positions": self.positions,
                "/v2/account/activities/FILL": self.fills,
                "/v2/account/portfolio/history": self.history,
            }
            if values[path] is None:
                return httpx.Response(503)
            return httpx.Response(200, json=values[path])

        def cycle(self, now=NOW):
            real_client = paper.PaperClient
            transport = httpx.MockTransport(self.handle)
            with (
                patch.object(
                    paper, "PaperClient", side_effect=lambda: real_client(transport=transport)
                ),
                patch.object(paper, "eligible_signals", return_value=(self.signals, DAY)),
                patch.object(paper, "datetime", wraps=datetime) as clock,
            ):
                clock.now.return_value = now
                return paper.paper_cycle(now)

    return Broker()


def test_read_only_and_pause_preserve_legacy(setup_broker, monkeypatch):
    broker = setup_broker
    paper.set_broker_paused(True)
    assert broker.cycle()["status"] == "BROKER_PAUSED"
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS", "0")
    assert broker.cycle()["status"] == "BROKER_READ_ONLY"
    assert broker.posts == []
    assert paper.enrich_dashboard({})["legacy_local_pending_orders"][0]["id"] == "legacy"
    with pytest.raises(paper.PaperError, match="orders_disabled"):
        paper.set_broker_paused(False)


def test_timeout_restart_and_partial_to_cancel(setup_broker):
    broker = setup_broker
    broker.mode = "timeout"
    assert broker.cycle()["status"] == "BROKER_ORDER_UNCERTAIN"
    cid = broker.posts[0]["client_order_id"]
    broker.lookup_hidden = True
    paper.broker_init()  # Restart with existing durable intent.
    assert broker.cycle()["status"] == "UNCERTAIN_BROKER_INTENT"
    broker.lookup_hidden = False
    order = broker.orders[cid]
    order.update(status="partially_filled", filled_qty="2", filled_avg_price="99")
    broker.open_orders = [order]
    broker.fills = [
        {
            "id": "partial",
            "symbol": "AAPL",
            "side": "buy",
            "qty": "2",
            "price": "99",
            "transaction_time": NOW.isoformat(),
            "order_id": order["id"],
        }
    ]
    assert broker.cycle()["status"] == "NO_APPROVED_BROKER_SIGNAL"
    view = paper.enrich_dashboard({})
    assert view["pending_orders"][0]["filled_qty"] == "2"
    assert view["fills"][0]["price"] == 99
    order["status"] = "canceled"
    broker.open_orders = []
    broker.cycle()
    assert storage.one("SELECT state,broker_status FROM sw_alpaca_intents") == {
        "state": "TERMINAL",
        "broker_status": "canceled",
    }
    assert len(broker.posts) == 1


def test_explicit_rejection_is_audited_and_not_retried(setup_broker):
    broker = setup_broker
    broker.mode = "reject"
    assert broker.cycle()["status"] == "BROKER_REJECTED"
    assert broker.cycle()["status"] == "NO_APPROVED_BROKER_SIGNAL"
    intent = paper.enrich_dashboard({})["broker_intents"][0]
    assert intent["state"] == "REJECTED"
    assert intent["diagnostic"] == "alpaca_paper_insufficient_buying_power"
    assert len(broker.posts) == 1


def test_cash_and_history_are_independent_of_margin_buying_power(setup_broker):
    broker = setup_broker
    broker.account["cash"] = "40000"
    assert broker.cycle()["why_no_trade"][0]["reason"] == "alpaca_paper_cash_or_exposure_cap"
    broker.account["cash"] = "100000"
    broker.history = None
    assert (
        broker.cycle()["why_no_trade"][0]["reason"] == "alpaca_paper_drawdown_history_unavailable"
    )
    broker.history = {"equity": [100000]}
    broker.account["non_marginable_buying_power"] = "102"
    assert broker.cycle()["status"] == "BROKER_ACKNOWLEDGED"
    (payload,) = broker.posts
    assert payload["qty"] == "1" and payload["limit_price"] == "100.50"
    assert payload["extended_hours"] is False


def test_partial_buy_reserve_uses_its_own_limit_and_remaining_quantity():
    existing = [
        {
            "symbol": "MSFT",
            "owned_intent": True,
            "side": "buy",
            "qty": "50",
            "filled_qty": "10",
            "limit_price": "500",
        }
    ]
    account = {**ACCOUNT, "cash": "65000"}
    budget = paper._entry_budget(
        {"account": account, "history": {"equity": [100000]}},
        {"AAPL": "Technology", "MSFT": "Technology"},
        "Technology",
        existing,
        {},
    )
    assert budget == Decimal("5000")


def test_manual_position_never_sold_and_is_shown(setup_broker):
    broker = setup_broker
    broker.positions = [
        {
            "symbol": "AAPL",
            "side": "long",
            "asset_class": "us_equity",
            "asset_id": "aapl",
            "qty": "4",
            "qty_available": "4",
            "avg_entry_price": "150",
            "market_value": "400",
            "unrealized_pl": "-200",
            "unrealized_plpc": "-0.333",
        }
    ]
    assert (
        broker.cycle()["why_no_trade"][0]["reason"]
        == "alpaca_paper_external_or_unverified_position"
    )
    assert broker.posts == []
    assert paper.enrich_dashboard({})["positions"][0]["unrealized"] == -200


def test_owned_position_exit_and_manual_round_trip_protection(setup_broker):
    broker = setup_broker
    prior = NOW - timedelta(days=2)
    cid = paper.cid_for(ACCOUNT["id"], "AAPL", "2026-11-03", "BUY")
    with patch.object(paper, "utc", return_value=prior.isoformat()), storage.connect() as c:
        assert paper._intent(c, cid, ACCOUNT["id"], "2026-11-03", "AAPL", "BUY", "4", "test")
    paper._state(cid, "TERMINAL", {"id": "bot-entry", "status": "filled"})
    with storage.connect() as c:
        c.execute("UPDATE sw_price_checks SET actions_since='2026-11-03'")
    broker.positions = [
        {
            "symbol": "AAPL",
            "side": "long",
            "asset_class": "us_equity",
            "asset_id": "aapl",
            "qty": "4",
            "qty_available": "4",
            "avg_entry_price": "150",
            "market_value": "400",
        }
    ]
    f = {
        "id": "entry",
        "symbol": "AAPL",
        "side": "buy",
        "qty": "4",
        "price": "150",
        "transaction_time": (prior + timedelta(seconds=5)).isoformat(),
        "order_id": "bot-entry",
    }
    broker.fills = [
        {**f, "id": "manual-buy", "order_id": "manual2", "qty": "1"},
        {**f, "id": "manual-sell", "order_id": "manual1", "qty": "1", "side": "sell"},
        f,
    ]
    assert (
        broker.cycle()["why_no_trade"][0]["reason"]
        == "alpaca_paper_external_or_unverified_position"
    )
    broker.fills = [f]
    assert broker.cycle()["status"] == "BROKER_ACKNOWLEDGED"
    assert broker.posts[0]["side"] == "sell"
    assert broker.posts[0]["type"] == "market"
    assert broker.posts[0]["qty"] == "4"


@pytest.mark.parametrize(
    "now",
    [OPEN - timedelta(minutes=1), OPEN + timedelta(hours=1), datetime(2026, 11, 7, 15, tzinfo=UTC)],
)
def test_no_orders_outside_broker_window(setup_broker, now):
    broker = setup_broker
    broker.cycle(now)
    assert broker.posts == []


def test_clock_and_corporate_actions_block_orders(setup_broker):
    broker = setup_broker
    broker.clock_open = False
    assert broker.cycle()["status"] == "WAITING_FOR_NEXT_CORE_OPEN_WINDOW"
    broker.clock_open = True
    with storage.connect() as c:
        c.execute("UPDATE sw_price_checks SET actions_json=?", (json.dumps([{"day": TARGET}]),))
    assert broker.cycle()["why_no_trade"][0]["reason"].endswith(
        "corporate_action_check_missing_or_blocked"
    )
    assert broker.posts == []


def test_account_identity_mismatch_clears_cached_financials(setup_broker, monkeypatch):
    broker = setup_broker
    paper.set_broker_paused(True)
    broker.cycle()
    assert paper.enrich_dashboard({})["account"]["cash"] == 100000
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_ACCOUNT_ID", "other-test")
    assert broker.cycle()["reason"] == "alpaca_paper_account_mismatch"
    view = paper.enrich_dashboard({})
    assert "account" not in view
    assert view["broker_account"]["status"] == "DISCONNECTED"
    assert view["broker_account"].get("masked") is None


def test_uncertain_intent_requires_read_only_pause_and_out_of_band_resolution(
    setup_broker, monkeypatch
):
    broker = setup_broker
    broker.mode = "timeout"
    broker.cycle()
    cid = broker.posts[0]["client_order_id"]
    ended = CLOSE + timedelta(minutes=1)
    with pytest.raises(paper.PaperError, match="read_only_required"):
        paper.record_confirmed_absence(cid, "CASE-123", ended)
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS", "0")
    paper.set_broker_paused(True)
    original = paper.PaperClient
    with patch.object(
        paper,
        "PaperClient",
        side_effect=lambda: original(transport=httpx.MockTransport(broker.handle)),
    ):
        with pytest.raises(paper.PaperError, match="session_ends"):
            paper.record_confirmed_absence(cid, "CASE-123", NOW)
        with pytest.raises(paper.PaperError, match="broker_order_exists"):
            paper.record_confirmed_absence(cid, "CASE-123", ended)
        del broker.orders[cid]
        paper.record_confirmed_absence(cid, "CASE-123", ended)
    assert storage.one("SELECT state FROM sw_alpaca_intents")["state"] == "CONFIRMED_ABSENT"
    assert len(broker.posts) == 1
