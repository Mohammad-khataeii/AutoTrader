"""All transactions run against temporary, explicitly isolated SQLite ledgers."""

import asyncio
import importlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from stockswatch import audit, ledger, market, storage
from stockswatch.app import authenticated, lifespan
from stockswatch.observer import Observer, export_jsonl, init_journal
from stockswatch.sessions import (
    completed_day,
    history_days,
    instant,
    next_day,
    published_after,
    session,
)

svc = importlib.import_module("stockswatch.service")

SIGNAL = "2026-11-03"
FILL = "2026-11-04"
EXIT = "2026-11-05"
EXIT_FILL = "2026-11-06"


def observed(day):
    return published_after(day) + timedelta(minutes=5)


def cycle_time(day):
    return observed(day) + timedelta(minutes=1)


def row(symbol, day, close, source=ledger.SOURCE, stamp=None):
    return (
        symbol,
        day,
        close,
        close * 1.006,
        close * 0.994,
        close,
        1_000_000,
        source,
        "RAW",
        (stamp or observed(day)).isoformat(),
    )


def prices(symbol, signal=SIGNAL):
    drift = 1.0024 if symbol != "SPY" else 1.0003
    return [row(symbol, day, 80 * drift**i) for i, day in enumerate(history_days(signal))]


def certify(symbol, day, close, *, status="OK", actions=(), stamp=None, source=ledger.SOURCE):
    with storage.connect() as c:
        c.execute(
            """INSERT INTO sw_eod_observations VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,day) DO NOTHING""",
            row(symbol, day, close, source, stamp),
        )
        c.execute(
            """INSERT INTO sw_price_checks VALUES(?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET day=excluded.day,checked_at=excluded.checked_at,
            status=excluded.status,actions_since=excluded.actions_since,actions_json=excluded.actions_json""",
            (
                symbol,
                day,
                (observed(day) + timedelta(seconds=1)).isoformat(),
                status,
                "2026-08-01",
                json.dumps(actions),
            ),
        )


def last(symbol, day=SIGNAL):
    return storage.one("SELECT c FROM bars WHERE symbol=? AND day=?", (symbol, day))["c"]


def order():
    return storage.one("SELECT * FROM pending_orders ORDER BY created_at,id LIMIT 1")


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    path = tmp_path / "stockswatch.sqlite3"
    monkeypatch.setattr(storage, "DB_PATH", str(path))
    monkeypatch.setenv("STOCKSWATCH_PRICE_PROVIDER", "alpaca")
    monkeypatch.setenv("STOCKSWATCH_ALPACA_KEY", "fixture-id")
    monkeypatch.setenv("STOCKSWATCH_ALPACA_SECRET", "fixture-secret")
    monkeypatch.setenv("STOCKSWATCH_INITIAL_USD", "10000")
    monkeypatch.delenv("STOCKSWATCH_ALLOW_INIT", raising=False)
    monkeypatch.delenv("STOCKSWATCH_SEC_USER_AGENT", raising=False)
    monkeypatch.setenv("STOCKSWATCH_GEMINI_ENABLED", "false")
    return path


@pytest.fixture
def ledger_db():
    storage.init()
    storage.init_execution()
    init_journal()
    with storage.connect() as c:
        c.execute("UPDATE assets SET enabled=(symbol IN ('AAPL','SPY'))")
        c.executemany(
            "INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)", prices("SPY") + prices("AAPL")
        )
    for sym in ("AAPL", "SPY"):
        certify(sym, SIGNAL, last(sym))


@pytest.fixture
def queued(ledger_db):
    result = ledger.decide_and_queue(now=cycle_time(SIGNAL))
    assert result["funnel"]["order_created"] == 1
    assert result["status"] == "TRADE_READY"
    return order()["id"]


def trade_observations():
    certify("SPY", FILL, last("SPY") * 1.001)
    certify("AAPL", FILL, last("AAPL") * 1.01)


@pytest.mark.asyncio
async def test_startup_autonomous_buy_and_sell_then_restart(sandbox, tmp_path, monkeypatch):
    other = tmp_path / "crypto.sqlite3"
    with sqlite3.connect(other) as c:
        c.execute("CREATE TABLE crypto_account (value INTEGER)")
        c.execute("INSERT INTO crypto_account VALUES (4910)")
    crypto_bytes = other.read_bytes()
    tick = observed(SIGNAL)
    current_day = SIGNAL
    published = {sym: {r[1]: r for r in prices(sym)} for sym in ("AAPL", "SPY")}
    initial = {sym: published[sym][SIGNAL][5] for sym in published}
    provider_calls = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return tick.astimezone(tz) if tz else tick.replace(tzinfo=None)

    def response(req):
        assert req.method == "GET" and req.url.host == "data.alpaca.markets"
        assert req.headers["APCA-API-KEY-ID"] == "fixture-id"
        provider_calls.append(req.url.path)
        if req.url.path == "/v1/corporate-actions":
            return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})
        symbol = req.url.path.split("/")[-2]
        if req.url.params["timeframe"] == "1Min":
            _, close = session(current_day)
            bars = [
                {"t": (close - timedelta(minutes=i)).isoformat(), "c": 100, "v": 200}
                for i in range(1, 6)
            ]
        else:
            bars = [
                {
                    "t": f"{d}T00:00:00-05:00",
                    **dict(zip(("o", "h", "l", "c", "v"), r[2:7], strict=True)),
                }
                for d, r in published[symbol].items()
            ]
        return httpx.Response(200, json={"bars": bars, "symbol": symbol, "next_page_token": None})

    real_client = httpx.AsyncClient

    def client(**kwargs):
        return real_client(transport=httpx.MockTransport(response), **kwargs)

    monkeypatch.setattr(svc, "datetime", Clock)
    monkeypatch.setattr(svc.httpx, "AsyncClient", client)
    monkeypatch.setattr(storage, "mounted_directory", lambda path: path == tmp_path)
    monkeypatch.setenv("STOCKSWATCH_ALLOW_INIT", "1")
    # Call the same scheduled cycle directly so fixture time controls observations.
    monkeypatch.setattr(importlib.import_module("stockswatch.app").service, "start", lambda: None)
    async with lifespan(None):
        with storage.connect() as c:
            c.execute("UPDATE assets SET enabled=(symbol IN ('AAPL','SPY'))")
        storage.set_setting("macro_checked_at", storage.utc())
        first = await svc.Service().cycle()
        assert first["price_updates"] == 2
        assert first["new_bars"] == 402
        assert first["paper"]["orders_queued"] == 1
        assert not storage.rows("SELECT * FROM fills")
        assert order()["symbol"] == "AAPL"
    monkeypatch.delenv("STOCKSWATCH_ALLOW_INIT")

    async with lifespan(None):
        assert storage.one("SELECT cash FROM portfolio")["cash"] == 10000
        for day, factor in ((FILL, 1.01), (EXIT, 0.90), (EXIT_FILL, 0.91)):
            current_day, tick = day, observed(day)
            for symbol in published:
                close = initial[symbol] * (factor if symbol == "AAPL" else 1.002)
                published[symbol][day] = row(symbol, day, close)
            if day == EXIT:
                with storage.connect() as c:
                    c.execute("UPDATE portfolio SET paused=1")
            result = await svc.Service().cycle()
            if day == FILL:
                assert result["paper"]["funnel"]["order_filled"] == 1
                assert storage.one("SELECT qty FROM positions")["qty"] > 0
            if day == EXIT:
                assert (
                    storage.one("SELECT side FROM pending_orders WHERE state='PENDING'")["side"]
                    == "SELL"
                )
                assert result["paper"]["funnel"]["order_created"] == 1
        fills = storage.rows("SELECT * FROM fills ORDER BY fill_day")
        assert [f["side"] for f in fills] == ["BUY", "SELL"]
        buy, sell = fills
        assert buy["price"] == pytest.approx(initial["AAPL"] * 1.01 * 1.0012)
        assert sell["price"] == pytest.approx(initial["AAPL"] * 0.91 * 0.9988)
        assert buy["slippage"] > 0 and buy["fee"] == sell["fee"] == 0
        assert buy["qty"] == sell["qty"]
        pnl = sell["qty"] * (sell["price"] - buy["price"])
        assert sell["realized"] == pytest.approx(pnl)
        assert storage.one("SELECT cash FROM portfolio")["cash"] == pytest.approx(10000 + pnl)
        assert storage.one("SELECT equity FROM equity_curve WHERE day=?", (EXIT_FILL,))[
            "equity"
        ] == pytest.approx(10000 + pnl)
        assert not storage.rows("SELECT * FROM positions")
        assert len(storage.rows("SELECT * FROM sw_order_outcomes WHERE reason='filled'")) == 2
        assert "/v1/corporate-actions" in provider_calls
        assert b"observed_daily_close" in b"".join(export_jsonl("order_outcomes"))
    assert other.read_bytes() == crypto_bytes


def test_preknown_future_bar_rejected(queued):
    with storage.connect() as c:
        c.execute(
            "INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)",
            row("AAPL", FILL, last("AAPL"), stamp=cycle_time(SIGNAL) - timedelta(seconds=1)),
        )
    trade_observations()
    r = ledger.decide_and_queue(now=cycle_time(FILL))
    assert r["order_checks"][queued] == "observation_not_forward_of_order"
    assert (
        storage.one("SELECT state FROM pending_orders WHERE id=?", (queued,))["state"]
        == "CANCELLED"
    )
    assert not storage.rows("SELECT * FROM fills")


def test_concurrent_retries_settle_once(queued):
    trade_observations()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: ledger.decide_and_queue(now=cycle_time(FILL)), range(4)))
    assert sum(r["funnel"]["order_filled"] for r in results) == 1
    assert len(storage.rows("SELECT * FROM fills")) == 1


def test_crash_rolls_back_cash_positions_and_fill(queued):
    trade_observations()
    with storage.connect() as c:
        c.execute("""CREATE TRIGGER fail_fill BEFORE INSERT ON fills BEGIN
            SELECT RAISE(ABORT,'fixture failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        ledger.decide_and_queue(now=cycle_time(FILL))
    assert storage.one("SELECT cash FROM portfolio")["cash"] == 10000
    assert not storage.rows("SELECT * FROM positions")
    assert order()["state"] == "PENDING"
    with storage.connect() as c:
        c.execute("DROP TRIGGER fail_fill")
    assert ledger.decide_and_queue(now=cycle_time(FILL))["funnel"]["order_filled"] == 1


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("halt", "no_recent_core_session_activity"),
        ("split", "corporate_action_requires_reconciliation"),
        ("dividend", "corporate_action_requires_reconciliation"),
        ("unknown", "corporate_action_date_unknown"),
        ("source", "unapproved_execution_source"),
        ("invalid", "invalid_price"),
        ("partial", "invalid_observation_time"),
        ("stale_spy", "benchmark_missing_or_stale"),
        ("large_gap", "ambiguous_gap_or_split"),
    ],
)
def test_invalid_execution_observation(queued, kind, reason):
    if kind != "stale_spy":
        certify("SPY", FILL, last("SPY") * 1.002)
    certify(
        "AAPL",
        FILL,
        -1 if kind == "invalid" else last("AAPL") * (0.7 if kind == "large_gap" else 1.01),
        source="stooq" if kind == "source" else ledger.SOURCE,
        status={"halt": reason, "unknown": reason}.get(kind, "OK"),
        actions=[{"day": FILL, "kind": kind}] if kind in {"split", "dividend"} else [],
        stamp=published_after(FILL) - timedelta(seconds=1) if kind == "partial" else None,
    )
    result = ledger.decide_and_queue(now=cycle_time(FILL))
    assert result["order_checks"][queued] == reason
    assert not storage.rows("SELECT * FROM fills")


def test_pending_expires_when_next_core_session_begins(queued):
    result = ledger.decide_and_queue(now=session(next_day(FILL))[0])
    assert result["order_checks"][queued] == "next_observation_window_missed"
    assert order()["state"] == "EXPIRED"


def test_legacy_order_preserved_as_cancelled(ledger_db):
    with storage.connect() as c:
        c.execute(
            "INSERT INTO pending_orders VALUES('legacy','AAPL','BUY',?,'old',?,'PENDING',NULL)",
            (SIGNAL, cycle_time(SIGNAL).isoformat()),
        )
    r = ledger.decide_and_queue(now=cycle_time(SIGNAL))
    assert r["order_checks"]["legacy"] == "legacy_order_evidence_unavailable"
    assert order()["state"] == "CANCELLED"
    assert not storage.rows("SELECT * FROM fills")


def test_sector_cap_rechecked_after_prices_move(queued):
    trade_observations()
    with storage.connect() as c:
        for sym in ("MSFT", "AMD"):
            oid = "fixture-" + sym
            c.execute(
                "INSERT INTO pending_orders VALUES(?,?,'BUY',?,'old',?,'FILLED',?)",
                (oid, sym, SIGNAL, cycle_time(SIGNAL).isoformat(), SIGNAL),
            )
            c.execute(
                "INSERT INTO fills VALUES(?,?,?,'BUY',?,?,12,100,0,0,0,?,?)",
                (
                    "fill-" + sym,
                    oid,
                    sym,
                    SIGNAL,
                    SIGNAL,
                    ledger.SOURCE,
                    cycle_time(SIGNAL).isoformat(),
                ),
            )
            c.execute("INSERT INTO positions VALUES(?,12,100,92,?,'Technology')", (sym, SIGNAL))
        c.execute("UPDATE portfolio SET cash=cash-2400")
    for sym in ("MSFT", "AMD"):
        certify(sym, FILL, 110)
    r = ledger.decide_and_queue(now=cycle_time(FILL))
    assert r["order_checks"][queued] == "sector_exposure_cap"
    assert len(storage.rows("SELECT * FROM fills")) == 2


def test_ledger_reconciliation_error_is_durable(ledger_db):
    with storage.connect() as c:
        c.execute("UPDATE portfolio SET cash=9900")
    r = ledger.decide_and_queue(now=cycle_time(SIGNAL))
    assert r["reason"] == "ledger_reconciliation_failed"
    assert (
        "ledger_reconciliation_failed"
        in storage.one("SELECT report_json FROM sw_trade_cycles")["report_json"]
    )
    assert not storage.rows("SELECT * FROM pending_orders")


def test_watchlist_source_switch_fails_closed(ledger_db, monkeypatch):
    monkeypatch.setenv("STOCKSWATCH_PRICE_PROVIDER", "stooq")
    result = ledger.decide_and_queue(now=cycle_time(SIGNAL))
    assert result["status"] == "WAITING_FOR_DATA"
    assert result["why_no_trade"][0]["reason"] == "source_not_configured_for_execution"


def test_holiday_dst_and_early_close():
    assert session("2026-11-26") is None
    assert next_day("2026-11-25") == "2026-11-27"
    assert session("2026-11-27")[1] == instant("2026-11-27T18:00:00Z")
    assert session("2026-03-06")[0] == instant("2026-03-06T14:30:00Z")
    assert session("2026-03-09")[0] == instant("2026-03-09T13:30:00Z")
    assert completed_day(instant("2026-11-28T05:14:59Z")) == "2026-11-25"
    assert completed_day(instant("2026-11-28T05:15:00Z")) == "2026-11-27"


@pytest.mark.parametrize(
    ("code", "message"), [(401, "alpaca_credentials_or_feed_denied"), (429, "alpaca_rate_limited")]
)
def test_provider_denial(code, message):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(code))
        ) as client:
            with pytest.raises(RuntimeError, match=message):
                await market.alpaca(client, "SPY", through=SIGNAL)

    asyncio.run(run())


def test_mount_and_ownership(sandbox, monkeypatch):
    monkeypatch.setattr(storage, "mounted_directory", lambda _: False)
    with pytest.raises(RuntimeError, match="db_parent_not_mounted"), storage.worker_ownership():
        pytest.fail()
    monkeypatch.setattr(storage, "mounted_directory", lambda _: True)
    with pytest.raises(RuntimeError, match="existing_db_missing"), storage.worker_ownership():
        pytest.fail()
    assert not sandbox.exists()
    storage.init()
    with storage.worker_ownership():
        with pytest.raises(RuntimeError, match="already_running"), storage.worker_ownership():
            pytest.fail()


def test_audit_read_only_and_observer_restart(sandbox, ledger_db):
    first = Observer()
    first.start()
    first.event("PRICE_FETCH", "RUNNING", "fixture", symbol="SPY")
    init_journal()
    assert storage.one("SELECT state FROM sw_scan_runs")["state"] == "INTERRUPTED"
    before = sandbox.read_bytes()
    evidence = audit.snapshot(Path(sandbox), history_days(SIGNAL)[-30:])
    assert evidence["cash_reconciles"] and evidence["shares_reconcile"]
    assert evidence["fills_last_30_market_sessions"] == {"BUY": 0, "SELL": 0}
    assert sandbox.read_bytes() == before


@pytest.mark.asyncio
async def test_existing_session_and_csrf_authority(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request

    token = "a" * 64
    calls = []

    def response(req):
        calls.append(req)
        return httpx.Response(200, json={"csrf_token": "fixture-proof"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(response), **kwargs),
    )
    headers = [(b"cookie", f"extraneous=private; personal_plan_session={token}".encode())]
    assert await authenticated(Request({"type": "http", "method": "GET", "headers": headers}))
    assert calls[0].headers["cookie"] == "personal_plan_session=" + token
    assert str(calls[0].url) == "http://backend:8000/api/session"
    with pytest.raises(HTTPException) as exc:
        await authenticated(Request({"type": "http", "method": "POST", "headers": headers}))
    assert exc.value.status_code == 403
    headers.append((b"x-csrf-token", b"fixture-proof"))
    assert await authenticated(Request({"type": "http", "method": "POST", "headers": headers}))


@pytest.mark.asyncio
async def test_gemini_quota_and_provider_error(ledger_db, monkeypatch):
    import sys
    from types import SimpleNamespace

    async def reject(_):
        return False

    async def allow(_):
        return True

    module = "autotrader.api.gemini_advisory"
    monkeypatch.setitem(sys.modules, module, SimpleNamespace(reserve=reject))
    monkeypatch.setenv("STOCKSWATCH_GEMINI_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-key-" * 3)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
    monkeypatch.setenv("REDIS_URL", "redis://fixture-only")
    with storage.connect() as c:
        c.execute(
            "INSERT INTO filings VALUES('fixture','AAPL','8-K',?,'1','filing',?,?)",
            (storage.utc(), "https://www.sec.gov/fixture", storage.utc()),
        )
    calls = []

    def respond(req):
        calls.append(req)
        assert req.url.host == "generativelanguage.googleapis.com"
        assert "fixture-key" not in req.content.decode()
        assert "responseSchema" in req.content.decode()
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert (await svc.Service().maybe_gemini(client))["status"] == "SHARED_GEMINI_QUOTA_LIMIT"
        assert not calls
        monkeypatch.setitem(sys.modules, module, SimpleNamespace(reserve=allow))
        assert (await svc.Service().maybe_gemini(client))["status"] == "GOOGLE_RATE_LIMIT"
        assert (await svc.Service().maybe_gemini(client))["status"] == "DAILY_CAP"
    assert len(calls) == 1
    assert not storage.rows("SELECT * FROM ai_insights")
    assert not storage.rows("SELECT * FROM fills")


def test_sell_fills_while_buys_paused_and_spy_stale(queued):
    trade_observations()
    assert ledger.decide_and_queue(now=cycle_time(FILL))["funnel"]["order_filled"] == 1
    with storage.connect() as c:
        c.execute("UPDATE portfolio SET paused=1")
    certify("AAPL", EXIT, last("AAPL") * 0.90)
    assert ledger.decide_and_queue(now=cycle_time(EXIT))["funnel"]["order_created"] == 1
    certify("AAPL", EXIT_FILL, last("AAPL") * 0.91)
    result = ledger.decide_and_queue(now=cycle_time(EXIT_FILL))
    assert result["funnel"]["order_filled"] == 1
    assert result["benchmark_gate"] == "price_check_pending"
    assert storage.one("SELECT side FROM fills ORDER BY fill_day DESC LIMIT 1")["side"] == "SELL"
    latest = storage.one("SELECT cash,equity,spy_close FROM equity_curve WHERE day=?", (EXIT_FILL,))
    assert latest["cash"] == latest["equity"]
    assert latest["spy_close"] is None
