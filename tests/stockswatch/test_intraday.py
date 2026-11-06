"""End-to-end Alpaca paper behavior using only HTTP mocks and temporary SQLite."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest
from stockswatch.intraday_market import IntradayData, ObservationError, observe, parse_bars
from stockswatch.intraday_policy import GATES, STRATEGY, order_gate, phase_at

from stockswatch import alpaca_paper as paper
from stockswatch import intraday, intraday_store, storage

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 6, 12, 0, 30, tzinfo=UTC)
SYMBOLS = [r[0] for r in storage.ASSETS]


@pytest.mark.parametrize(
    ("local", "expected"),
    [
        ("2026-03-06T04:00", "PREMARKET"),
        ("2026-03-09T04:00", "PREMARKET"),
        ("2026-10-30T09:30", "CORE"),
        ("2026-11-02T09:30", "CORE"),
        ("2026-11-06T16:00", "AFTERHOURS"),
        ("2026-11-06T20:00", "CLOSED"),
        ("2026-11-07T10:00", "CLOSED"),
        ("2026-11-08T20:00", "OVERNIGHT"),
        ("2026-11-25T21:00", "CLOSED"),
        ("2026-11-26T10:00", "CLOSED"),
        ("2026-11-26T20:00", "OVERNIGHT"),
        ("2026-11-27T13:00", "AFTERHOURS"),
        ("2026-11-27T17:00", "MAINTENANCE"),
        ("2026-11-27T20:00", "CLOSED"),
    ],
)
def test_nyse_phase_boundaries(local, expected):
    now = datetime.fromisoformat(local).replace(tzinfo=NY)
    phase = phase_at(now)
    assert phase.name == expected
    if phase.start:
        assert phase.contains(now)


def test_dst_actual_utc_hours():
    def opened(value):
        return phase_at(datetime.fromisoformat(value).replace(tzinfo=NY)).start

    assert opened("2026-03-06T05:00").hour == 9
    assert opened("2026-03-09T05:00").hour == 8
    assert opened("2026-10-30T10:00").hour == 13
    assert opened("2026-11-02T10:00").hour == 14


def bars(end, bullish=False):
    values = [100 + index * 0.06 if bullish else 100 for index in range(8)]
    return [
        {
            "t": (end - timedelta(minutes=8 - i)).isoformat(),
            "o": v,
            "h": v,
            "l": v,
            "c": v,
            "v": 3000,
        }
        for i, v in enumerate(values)
    ]


def snap(at, bullish=False, price=None):
    px = price or (100.45 if bullish else 100)
    return {
        "latestQuote": {
            "t": (at - timedelta(seconds=1)).isoformat(),
            "bp": str(px - 0.02),
            "ap": str(px + 0.02),
            "bs": 1000,
            "as": 1000,
            "bx": "Q",
            "ax": "Q",
            "c": ["R"],
        },
        "latestTrade": {
            "t": (at - timedelta(seconds=2)).isoformat(),
            "p": str(px),
            "s": 100,
            "c": ["@", "T"],
        },
    }


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda r: r.pop("latestQuote"), "intraday_quote_or_trade_missing"),
        (lambda r: r["latestQuote"].update({"bs": 0}), "missing_or_invalid_positive_value"),
        (lambda r: r["latestQuote"].update({"bp": "101"}), "intraday_locked_or_crossed_quote"),
        (lambda r: r["latestQuote"].update({"as": 1}), "intraday_insufficient_displayed_liquidity"),
        (
            lambda r: r["latestTrade"].update({"t": (NOW - timedelta(minutes=15)).isoformat()}),
            "intraday_stale_future_or_cross_session_tick",
        ),
        (
            lambda r: r["latestQuote"].update({"t": (NOW + timedelta(seconds=1)).isoformat()}),
            "intraday_stale_future_or_cross_session_tick",
        ),
        (lambda r: r.update(halted=True), "intraday_halted"),
        (lambda r: r["latestQuote"].update({"c": ["H"]}), "intraday_quote_not_regular_executable"),
        (lambda r: r["latestTrade"].update({"c": ["P"]}), "intraday_trade_condition_unverified"),
        (
            lambda r: r["latestTrade"].update({"t": "2026-11-05T20:55:00Z"}),
            "intraday_stale_future_or_cross_session_tick",
        ),
    ],
)
def test_invalid_observations(mutate, reason):
    raw = snap(NOW)
    mutate(raw)
    r = observe(
        "AAPL", raw, bars(NOW.replace(second=0)), {"price": "99"}, phase_at(NOW), "sip", NOW
    )
    assert (r["valid"], r["reason"]) == (False, reason)


def test_causal_completed_bar_parser():
    end = NOW.replace(second=0)
    sample = bars(end)
    forming = {**sample[-1], "t": end.isoformat()}
    assert len(parse_bars([*sample, forming], end - timedelta(minutes=10), end)) == 8
    for invalid in (
        [*sample, sample[-1]],
        list(reversed(sample)),
        [*sample, {**forming, "t": (end + timedelta(minutes=1)).isoformat()}],
    ):
        with pytest.raises(ObservationError):
            parse_bars(invalid, end - timedelta(minutes=10), end)


@pytest.fixture
def offline(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "stocks.sqlite"))
    for key, value in {
        "STOCKSWATCH_EXECUTION_BACKEND": "alpaca_paper",
        "STOCKSWATCH_ALPACA_KEY": "test-data",
        "STOCKSWATCH_ALPACA_SECRET": "test-data-secret",
        "STOCKSWATCH_ALPACA_PAPER_KEY": "test-broker",
        "STOCKSWATCH_ALPACA_PAPER_SECRET": "test-broker-secret",
        "STOCKSWATCH_ALPACA_PAPER_ACCOUNT_ID": "offline",
        "STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS": "1",
        "STOCKSWATCH_INTRADAY_ALLOW_ORDERS": "1",
        "STOCKSWATCH_INTRADAY_FEED": "sip",
        "STOCKSWATCH_BUILD_COMMIT": "a" * 40,
    }.items():
        monkeypatch.setenv(key, value)
    proof = tmp_path / "proof.json"
    proof.write_text(
        json.dumps(
            {
                "commit": "a" * 40,
                "strategy": STRATEGY,
                "paper_only": True,
                "checks": {k: "PASS" for k in GATES},
            }
        )
    )
    monkeypatch.setenv("STOCKSWATCH_INTRADAY_PREFLIGHT", str(proof))
    monkeypatch.setenv(
        "STOCKSWATCH_INTRADAY_PREFLIGHT_SHA256", hashlib.sha256(proof.read_bytes()).hexdigest()
    )
    storage.init()
    storage.init_execution()
    paper.broker_init()
    intraday_store.initialize()
    paper.set_broker_paused(False)

    class Fixture:
        def __init__(self):
            self.now = NOW
            self.equity = "100000"
            self.positions = []
            self.open = []
            self.fills = []
            self.orders = {}
            self.posts = []
            self.requests = []
            self.mode = "accept"
            self.data_status = None
            self.missing = None
            self.low_depth = False
            self.split = False
            self.wrong_asset = False
            self.bad_clock = False
            self.account_faults = []
            self.bad_account = False
            self.trade_price = None
            self.lookup_hidden = False
            self.bar_page = False

        def data(self, request):
            assert request.url.host == "data.alpaca.markets" and request.method == "GET"
            assert request.headers["APCA-API-KEY-ID"] == "test-data"
            params = request.url.params
            self.requests.append((request.url.path, dict(params)))
            path = request.url.path
            if self.data_status:
                return httpx.Response(self.data_status)
            if path.endswith("corporate-actions"):
                action = (
                    {"forward_splits": [{"ex_date": phase_at(self.now).day}]} if self.split else {}
                )
                return httpx.Response(200, json={"corporate_actions": action})
            syms = params["symbols"].split(",")
            assert len(syms) <= 32
            assert params["feed"] in {"sip", "iex", "delayed_sip", "overnight", "boats"}
            if path.endswith("snapshots"):
                values = {
                    s: snap(self.now, s == "AAPL", self.trade_price if s == "AAPL" else None)
                    for s in syms
                    if s != self.missing
                }
                if self.low_depth and "AAPL" in values:
                    values["AAPL"]["latestQuote"]["as"] = 1
                return httpx.Response(200, json=values)
            end = datetime.fromisoformat(params["end"])
            if end.date() != self.now.date() or end.hour == 21:
                values = [
                    {
                        "t": (end - timedelta(minutes=1)).isoformat(),
                        "o": 99,
                        "h": 99,
                        "l": 99,
                        "c": 99,
                        "v": 3000,
                    }
                ]
                return httpx.Response(200, json={"bars": {s: values for s in syms}})
            if self.bar_page and not params.get("page_token"):
                return httpx.Response(
                    200,
                    json={
                        "bars": {s: bars(end, s == "AAPL") for s in syms[:16]},
                        "next_page_token": "p2",
                    },
                )
            if params.get("page_token"):
                syms = syms[16:]
            return httpx.Response(200, json={"bars": {s: bars(end, s == "AAPL") for s in syms}})

        def broker(self, request):
            assert request.url.host == "paper-api.alpaca.markets"
            assert request.headers["APCA-API-KEY-ID"] == "test-broker"
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
                assert path == "/v2/orders"
                if self.mode == "reject":
                    return httpx.Response(403, json={"code": 40310000})
                if isinstance(self.mode, int):
                    return httpx.Response(self.mode)
                order = {
                    **payload,
                    "id": f"paper-{len(self.posts)}",
                    "status": "accepted",
                    "filled_qty": "0",
                }
                self.orders[payload["client_order_id"]] = order
                self.open.append(order)
                if self.mode == "timeout":
                    raise httpx.ReadTimeout("mock lost acknowledgement", request=request)
                if self.mode == "bad_identity":
                    return httpx.Response(200, json={**order, "side": "sell"})
                return httpx.Response(200, json=order)
            if path == "/v2/account":
                if self.account_faults:
                    fault = self.account_faults.pop(0)
                    if fault == "transport":
                        raise httpx.ReadTimeout("offline transport", request=request)
                    return httpx.Response(fault)
                return httpx.Response(
                    200,
                    json={
                        "id": "wrong" if self.bad_account else "offline",
                        "currency": "USD",
                        "status": "ACTIVE",
                        "trading_blocked": False,
                        "account_blocked": False,
                        "cash": "100000",
                        "equity": self.equity,
                        "last_equity": "100000",
                        "non_marginable_buying_power": "100000",
                    },
                )
            if path == "/v2/clock":
                return httpx.Response(
                    200,
                    json={
                        "timestamp": (
                            self.now - (timedelta(minutes=2) if self.bad_clock else timedelta(0))
                        ).isoformat(),
                        "is_open": phase_at(self.now).name == "CORE",
                    },
                )
            if path == "/v2/orders:by_client_order_id":
                order = self.orders.get(request.url.params["client_order_id"])
                return (
                    httpx.Response(200, json=order)
                    if order and not self.lookup_hidden
                    else httpx.Response(404)
                )
            if path == "/v2/orders":
                return httpx.Response(
                    200,
                    json=self.open
                    if request.url.params["status"] == "open"
                    else list(self.orders.values()),
                )
            if path.startswith("/v2/assets/"):
                return httpx.Response(
                    200,
                    json={
                        "symbol": "TSLA" if self.wrong_asset else path.split("/")[-1],
                        "class": "us_equity",
                        "status": "active",
                        "tradable": True,
                        "id": "asset-a",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "/v2/positions": self.positions,
                    "/v2/account/activities/FILL": self.fills,
                    "/v2/account/portfolio/history": {"equity": [100000]},
                }[path],
            )

        def cycle(self):
            return self.engine.cycle(
                clock=lambda: self.now,
                broker_factory=lambda: paper.PaperClient(
                    httpx.MockTransport(self.broker), retry_reads=True, clock=lambda: self.now
                ),
            )

    fx = Fixture()
    monkeypatch.setattr(paper, "utc", lambda: fx.now.isoformat())
    fx.engine = intraday.IntradayEngine()
    fx.engine.data = IntradayData(httpx.MockTransport(fx.data), sleeper=lambda _: None)
    yield fx
    fx.engine.close()


def test_bounded_32_symbol_cycle_and_idempotent_restart(offline):
    offline.bar_page = True
    report = offline.cycle()
    assert report["execution"] == "BROKER_ACCEPTED"
    assert report["tracked"] == report["snapshot_symbols"] == report["valid"] == 32
    assert storage.one("SELECT count(*) AS n FROM sw_intraday_observations")["n"] == 32
    (order,) = offline.posts
    assert order["side"] == "buy" and order["extended_hours"] is True
    assert order["type"] == "limit" and order["time_in_force"] == "day"
    assert order["client_order_id"].startswith("swx1-")
    assert Decimal(order["qty"]) * Decimal(order["limit_price"]) <= 5000
    assert len(offline.requests) <= 7
    offline.now += timedelta(seconds=15)
    offline.cycle()
    assert len(offline.posts) == 1
    assert intraday_store.status(offline.now + timedelta(minutes=3))["valid"] == 0
    assert intraday_store.order_history()[0]["broker_status"] == "accepted"


@pytest.mark.parametrize(
    ("at", "extended"),
    [
        (datetime(2026, 11, 6, 15, 50, 30, tzinfo=UTC), False),
        (datetime(2026, 11, 6, 22, 0, 30, tzinfo=UTC), True),
    ],
)
def test_core_and_afterhours_offline_route(offline, at, extended):
    offline.now = at
    assert offline.cycle()["execution"] == "BROKER_ACCEPTED"
    assert offline.posts[0]["extended_hours"] is extended


def test_unknown_response_quarantine_and_reconcile(offline):
    offline.mode = "timeout"
    report = offline.cycle()
    assert report["execution"] == "BROKER_ORDER_UNCERTAIN"
    order = offline.open.pop()
    offline.lookup_hidden = True
    offline.now += timedelta(seconds=10)
    assert offline.cycle()["execution"] == "intraday_uncertain_broker_intent"
    offline.open.append(order)
    offline.lookup_hidden = False
    offline.now += timedelta(seconds=10)
    offline.cycle()
    assert len(offline.posts) == 1
    assert intraday_store.order_history()[0]["state"] == "ACKNOWLEDGED"


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("reject", "BROKER_REJECTED"),
        (401, "BROKER_ORDER_UNCERTAIN"),
        (429, "BROKER_ORDER_UNCERTAIN"),
        (503, "BROKER_ORDER_UNCERTAIN"),
        ("bad_identity", "BROKER_ORDER_UNCERTAIN"),
    ],
)
def test_post_definitive_vs_unknown_never_retries(offline, mode, expected):
    offline.mode = mode
    assert offline.cycle()["execution"] == expected
    assert len(offline.posts) == 1


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        ("bad_account", "alpaca_paper_account_mismatch"),
        ("bad_clock", "intraday_broker_clock_stale_or_phase_mismatch"),
        ("split", "WAIT"),
        ("wrong_asset", "WAIT"),
        ("low_depth", "WAIT"),
    ],
)
def test_rejections_without_orders(offline, fault, expected):
    setattr(offline, fault, True)
    assert offline.cycle()["execution"] == expected
    assert offline.posts == []


def test_pause_and_daily_loss_leave_observations_active(offline):
    paper.set_broker_paused(True)
    paused = offline.cycle()
    assert paused["valid"] == 32 and paused["execution"] == "intraday_paper_kill_switch"
    paper.set_broker_paused(False)
    offline.equity = "98000"
    offline.now += timedelta(seconds=5)
    loss = offline.cycle()
    assert (
        next(r for r in loss["rows"] if r["symbol"] == "AAPL")["risk_decision"]
        == "intraday_daily_loss_pause"
    )
    assert offline.posts == []
    offline.equity = "100000"
    offline.now += timedelta(seconds=5)
    assert offline.cycle()["daily_loss_paused"] is True
    assert offline.posts == []


def test_universe_and_feed_fail_closed(offline, monkeypatch):
    offline.missing = "GE"
    assert offline.cycle()["execution"] == "intraday_universe_confidence_insufficient"
    offline.now += timedelta(seconds=5)
    offline.missing = None
    monkeypatch.setenv("STOCKSWATCH_INTRADAY_FEED", "iex")
    report = offline.cycle()
    assert report["feed_scope"] == "IEX_SINGLE_VENUE"
    assert offline.posts == []
    assert not any(r.get("candidate") for r in report["rows"])


def test_read_retries_and_recovery(offline):
    offline.account_faults = ["transport", 503]
    assert offline.cycle()["execution"] == "alpaca_paper_http_503"
    assert offline.posts == []
    offline.now += timedelta(seconds=5)
    offline.account_faults = ["transport"]
    report = offline.cycle()
    assert report["execution"] == "BROKER_ACCEPTED" and report["transport_recovered"]
    assert len(offline.posts) == 1


@pytest.mark.parametrize(
    "status,reason",
    [(429, "intraday_data_rate_limited"), (403, "intraday_feed_or_entitlement_denied")],
)
def test_data_outage_persists_and_recovers(offline, status, reason):
    offline.data_status = status
    failed = offline.cycle()
    assert failed["reason"] == reason and len(failed["rows"]) == 32
    assert not offline.posts
    offline.data_status = None
    offline.now += timedelta(minutes=1)
    assert offline.cycle()["execution"] == "BROKER_ACCEPTED"


def test_overnight_never_posts(offline):
    offline.now = datetime(2026, 11, 9, 3, 0, 30, tzinfo=UTC)
    assert offline.cycle()["execution"] == "overnight_monitor_only"
    assert not offline.posts


def test_partial_cancel_owned_sell_and_external_collision(offline):
    assert offline.cycle()["execution"] == "BROKER_ACCEPTED"
    buy = offline.open.pop()
    buy.update(status="canceled", filled_qty="5")
    offline.now += timedelta(minutes=1)
    offline.fills = [
        {
            "id": "fill1",
            "order_id": buy["id"],
            "side": "buy",
            "symbol": "AAPL",
            "qty": "5",
            "price": "100.50",
            "transaction_time": offline.now.isoformat(),
        }
    ]
    offline.positions = [
        {
            "symbol": "AAPL",
            "asset_id": "asset-a",
            "asset_class": "us_equity",
            "side": "long",
            "qty": "5",
            "qty_available": "5",
            "avg_entry_price": "100.50",
            "market_value": "490",
        }
    ]
    offline.trade_price = 98
    offline.open = [{"id": "manual", "client_order_id": "manual", "symbol": "AAPL", "side": "sell"}]
    report = offline.cycle()
    assert report["execution"] == "WAIT" and len(offline.posts) == 1
    offline.open = []
    offline.now += timedelta(seconds=10)
    assert offline.cycle()["execution"] == "BROKER_ACCEPTED"
    sell = offline.open.pop()
    assert sell["side"] == "sell" and sell["qty"] == "5" and sell["extended_hours"] is True
    sell.update(status="filled", filled_qty="5")
    offline.now += timedelta(seconds=10)
    offline.fills.insert(
        0,
        {
            "id": "fill2",
            "order_id": sell["id"],
            "side": "sell",
            "symbol": "AAPL",
            "qty": "5",
            "price": "98.00",
            "transaction_time": offline.now.isoformat(),
        },
    )
    offline.positions = []
    assert offline.cycle()["pnl"]["realized_usd"] == "-12.50"
    assert not paper._position_owned(
        {"symbol": "AAPL", "qty": "5", "qty_available": "5"}, offline.fills, "offline"
    )


def test_pinned_configuration_and_live_route_rejected(offline, monkeypatch):
    assert order_gate() is None
    monkeypatch.setenv("STOCKSWATCH_INTRADAY_PREFLIGHT_SHA256", "c" * 64)
    assert order_gate() == "intraday_pinned_preflight_required"
    assert offline.cycle()["execution"] == "intraday_pinned_preflight_required"
    with (
        paper.PaperClient(httpx.MockTransport(offline.broker)) as client,
        pytest.raises(paper.PaperError, match="unapproved_paper_route"),
    ):
        client.get("https://api.alpaca.markets/v2/account")
    assert not offline.posts


def test_rank_replay_of_persisted_evidence(offline, tmp_path):
    from stockswatch.intraday_replay import replay
    from stockswatch.observer import export_jsonl

    offline.cycle()
    path = tmp_path / "saved.jsonl"
    path.write_bytes(b"".join(export_jsonl("intraday_observations")))
    result = replay(path)
    assert result["observations"] == 32 and result["rank_mismatches"] == 0
    assert result["entry_candidates"] == 1 and result["broker_calls"] == 0


def test_open_intraday_order_carries_across_phase_without_duplicate(offline):
    offline.now = datetime(2026, 11, 6, 14, 25, 30, tzinfo=UTC)
    assert offline.cycle()["execution"] == "BROKER_ACCEPTED"
    offline.now = datetime(2026, 11, 6, 14, 40, 30, tzinfo=UTC)
    assert offline.cycle()["execution"] == "WAIT"
    assert len(offline.posts) == 1


def test_unresolved_eod_intent_blocks_intraday(offline):
    with storage.connect() as c:
        paper._intent(
            c,
            paper.cid_for("offline", "TSLA", "2026-11-05", "BUY"),
            "offline",
            "2026-11-05",
            "TSLA",
            "BUY",
            "1",
            "certified_eod_signal",
        )
    report = offline.cycle()
    assert report["execution"] == "intraday_uncertain_broker_intent"
    assert not offline.posts


def test_full_or_invalid_broker_snapshot_cannot_submit(offline):
    offline.open = [
        {"id": "same", "client_order_id": "manual", "symbol": "TSLA", "side": "sell"}
    ] * 500
    assert offline.cycle()["execution"] == "intraday_broker_snapshot_incomplete"
    assert not offline.posts
