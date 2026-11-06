"""Offline history acquisition, provenance and independent replay verification."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest
from stockswatch.direction import Action, fifo, intent_action, position
from stockswatch.directional_research import replay
from stockswatch.intraday_market import IntradayData
from stockswatch.sessions import completed_day, history_days
from stockswatch.universe import ADDITIONS, BENCHMARKS, LEGACY, NEW, REGISTRY

from stockswatch import alpaca_paper as paper
from stockswatch import backfill, storage

NOW = datetime(2026, 11, 6, 17, tzinfo=UTC)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "research.sqlite"
    monkeypatch.setattr(storage, "DB_PATH", str(path))
    for name, value in {
        "STOCKSWATCH_ALPACA_KEY": "offline",
        "STOCKSWATCH_ALPACA_SECRET": "offline",
        "STOCKSWATCH_ALPACA_PAPER_KEY": "paper",
        "STOCKSWATCH_ALPACA_PAPER_SECRET": "paper",
        "STOCKSWATCH_ALPACA_PAPER_ACCOUNT_ID": "test-paper",
    }.items():
        monkeypatch.setenv(name, value)
    storage.init()
    storage.init_execution()
    backfill.initialize()
    return path


def test_registry_and_read_only_report(db):
    assert len(REGISTRY) == 52 and len(LEGACY) == 32 and len(ADDITIONS) == 20
    assert BENCHMARKS == {"SPY", "QQQ"}
    assert NEW == {
        "TSLA",
        "PLTR",
        "COIN",
        "MU",
        "AMAT",
        "PANW",
        "CRWD",
        "ADBE",
        "NOW",
        "BAC",
        "GS",
        "SCHW",
        "HD",
        "LOW",
        "DE",
        "PFE",
        "MRK",
        "ABT",
        "NEE",
        "MCD",
    }
    assert all(REGISTRY[s]["strategies"] == () for s in BENCHMARKS)
    assert all(
        REGISTRY[s]["instrument_type"] == "COMPANY_EQUITY" and REGISTRY[s]["name"] for s in NEW
    )
    result = backfill.report(NOW, db)
    assert result["instruments"] == 52
    assert all(
        len(r["missing_sessions"]) == 201 and r["asset"]["status"] == "UNVERIFIED"
        for r in result["symbols"]
    )


def test_mock_actual_asset_schema_marks_ineligible_without_replacement(db):
    def handler(request):
        assert request.url.host == "paper-api.alpaca.markets" and request.method == "GET"
        if request.url.path == "/v2/account":
            return httpx.Response(200, json={"id": "test-paper", "currency": "USD"})
        assert request.url.path == "/v2/assets"
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": s,
                    "class": "us_equity",
                    "id": s,
                    "exchange": "NASDAQ",
                    "status": "active",
                    "tradable": s != "TSLA",
                    "borrow_status": "easy_to_borrow",
                }
                for s in REGISTRY
            ],
        )

    with paper.PaperClient(httpx.MockTransport(handler)) as client:
        backfill.verify_assets(client, NOW)
    result = backfill.report(NOW, db)
    rows = {r["symbol"]: r for r in result["symbols"]}
    assert not rows["TSLA"]["asset"]["verified"]
    assert rows["AAPL"]["asset"]["verified"] and rows["AAPL"]["asset"]["verified_at"]
    assert len(rows) == 52


def test_historical_checkpoint_resume_throttling_and_separate_adjustments(db):
    from datetime import date

    start = backfill.midnight(date(2026, 11, 2))
    end = backfill.midnight(date(2026, 11, 5))
    calls = []

    def handler(request):
        params = request.url.params
        assert request.method == "GET" and request.url.host == "data.alpaca.markets"
        if request.url.path.endswith("corporate-actions"):
            return httpx.Response(
                200, json={"corporate_actions": {"forward_splits": [{"ex_date": "2026-11-03"}]}}
            )
        calls.append(params.get("page_token"))
        if len(calls) == 2:
            return httpx.Response(429, headers={"Retry-After": "0"})
        second = params.get("page_token")
        d = date(2026, 11, 3) if second else date(2026, 11, 2)
        bar = {
            "t": backfill.midnight(d).isoformat(),
            "o": 101,
            "h": 102,
            "l": 100,
            "c": 101,
            "v": 1000,
        }
        return httpx.Response(
            200, json={"bars": {"TSLA": [bar]}, "next_page_token": None if second else "continue"}
        )

    with storage.connect() as c:
        c.execute(
            """INSERT INTO sw_history_jobs
          (symbol,timeframe,feed,adjustment,first_at,end_at,state) VALUES(?,?,?,?,?,?,'PENDING')""",
            ("TSLA", "1Day", "iex", "raw", start.isoformat(), end.isoformat()),
        )
    data = IntradayData(httpx.MockTransport(handler), background=True, sleeper=lambda _: None)
    try:
        assert backfill.step(data, NOW)
        assert storage.one("SELECT token,state FROM sw_history_jobs") == {
            "token": "continue",
            "state": "RUNNING",
        }
        assert backfill.step(data, NOW + timedelta(seconds=1))
        assert storage.one("SELECT state FROM sw_history_jobs")["state"] == "COMPLETE"
        assert calls == [None, "continue", "continue"]
        assert storage.one("SELECT COUNT(*) n FROM sw_historical_bars")["n"] == 2
        assert storage.one("SELECT kind FROM sw_history_actions")["kind"] == "forward_splits"
        with storage.connect() as c:
            c.execute(
                """INSERT INTO sw_history_jobs
              (symbol,timeframe,feed,adjustment,first_at,end_at,state) VALUES(?,?,?,?,?,?,'PENDING')""",
                ("TSLA", "1Day", "iex", "split", start.isoformat(), end.isoformat()),
            )
        assert backfill.step(data, NOW)
        assert {
            r["adjustment"]
            for r in storage.rows("SELECT DISTINCT adjustment FROM sw_historical_bars")
        } == {"raw", "split"}
        assert storage.one("SELECT COUNT(*) n FROM bars")["n"] == 0
    finally:
        data.close()


def test_eod_report_distinguishes_missing_session_and_archive_sources(db):
    day = completed_day(NOW)
    days = history_days(day)
    with storage.connect() as c:
        c.executemany(
            "INSERT INTO sw_eod_observations VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                ("TSLA", d, 101, 101, 101, 101, 100, "alpaca_iex_daily", "RAW", NOW.isoformat())
                for d in days[1:]
            ],
        )
        c.execute(
            "INSERT INTO sw_historical_bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "TSLA",
                "1Day",
                "iex",
                "split",
                days[0] + "T00:00:00Z",
                days[0],
                "DAILY",
                NOW.isoformat(),
                "101",
                "101",
                "101",
                "101",
                "100",
            ),
        )
    row = next(r for r in backfill.report(NOW, db)["symbols"] if r["symbol"] == "TSLA")
    assert row["missing_sessions"] == [days[0]] and not row["eod_certified_window_complete"]
    with storage.connect() as c:
        c.execute(
            "INSERT INTO sw_eod_observations VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("TSLA", days[0], 101, 101, 101, 101, 100, "alpaca_iex_daily", "RAW", NOW.isoformat()),
        )
    row = next(r for r in backfill.report(NOW, db)["symbols"] if r["symbol"] == "TSLA")
    assert row["eod_certified_window_complete"] and not row["missing_sessions"]


def test_explicit_direction_fifo_and_short_proceeds_removed_from_cash(db):
    short = {
        "side": "short",
        "asset_class": "us_equity",
        "qty": "-100",
        "qty_available": "-100",
        "market_value": "-9000",
        "avg_entry_price": "100",
    }
    assert position(short).signed_qty == D(-100)
    assert intent_action("swx1-x", "SELL") == Action.SELL_TO_CLOSE_LONG
    assert intent_action("sws1-x", "SELL") == Action.SELL_TO_OPEN_SHORT
    realized, inventory = fifo(
        [
            (Action.SELL_TO_OPEN_SHORT, "AAPL", D(100), D(100)),
            (Action.BUY_TO_COVER_SHORT, "AAPL", D(10), D(110)),
            (Action.BUY_TO_COVER_SHORT, "AAPL", D(20), D(90)),
        ]
    )
    assert realized == D(100) and inventory["AAPL"][0][1] == 70
    with pytest.raises(ValueError):
        fifo([(Action.BUY_TO_COVER_SHORT, "AAPL", D(1), D(90))])
    snapshot = {
        "account": {
            "equity": "100000",
            "cash": "55000",
            "last_equity": "100000",
            "non_marginable_buying_power": "100000",
        },
        "history": {"equity": [100000]},
    }
    assert paper._entry_budget(
        snapshot, {"AAPL": "Technology"}, "Technology", [], {"AAPL": short}
    ) == D(5000)


def test_walk_forward_has_disjoint_testing_and_cost_stress():
    series = {}
    for day_index in range(8):
        day = (NOW + timedelta(days=day_index)).date().isoformat()
        for s in ("AAPL", "SPY", "QQQ"):
            values = []
            for i in range(80):
                px = 100 - i * (0.05 if s == "AAPL" else 0.002)
                values.append((NOW + timedelta(days=day_index, minutes=i), px, px, px))
            series[(s, day)] = values
    result = replay(series)
    assert result["windows"]
    for window in result["windows"]:
        assert max(window["development"]) < min(window["test"])
        short = window["variants"]["short_only"]
        assert short["trades"] > 0 and short["stressed"]["mean_net"] < short["mean_net"]


def test_explicit_borrow_charge_and_recall_override_etb():
    from stockswatch.shorts import borrow

    etb = {"shortable": True, "marginable": True, "borrow_status": "easy_to_borrow"}
    assert borrow(etb) == "ETB"
    assert borrow({**etb, "borrow_fee_rate": "0.04"}) == "CHARGEABLE_OR_UNVERIFIED"
    assert borrow({**etb, "borrow_recalled": True}) == "UNAVAILABLE"
    assert borrow({**etb, "short_sale_restricted": True}) == "RESTRICTED"
