import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from stockswatch import alpaca_paper, intraday, service, storage
from stockswatch.crypto_challenger_replay import _relative_strength
from stockswatch.crypto_strategy_replay import _trade
from stockswatch.intraday_market import IntradayData, ObservationError
from stockswatch.readiness import snapshot
from stockswatch.sessions import completed_day


@pytest.fixture
def database(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "stockswatch.sqlite3"))
    storage.init()
    storage.init_execution()
    alpaca_paper.broker_init()
    service.backfill.initialize()


def test_latest_session_catchup_repairs_missing_observations_for_all_102(database, monkeypatch):
    now = datetime.now(UTC)
    day = completed_day(now)
    monkeypatch.setenv("STOCKSWATCH_PRICE_PROVIDER", "alpaca")
    monkeypatch.setenv("STOCKSWATCH_EXECUTION_BACKEND", "alpaca_paper")
    calls = []

    async def fetch(client, symbol, start, through):
        calls.append(symbol)
        return ([{"day": day, "o": 100, "h": 102, "l": 99, "c": 101, "v": 1000}],
                "alpaca_iex_daily", "RAW")

    async def actions(*args, **kwargs):
        return []

    async def no_wait(seconds):
        pass

    monkeypatch.setattr(service, "fetch_bars", fetch)
    monkeypatch.setattr(service, "alpaca_execution_checks", actions)
    monkeypatch.setattr(service.asyncio, "sleep", no_wait)
    monkeypatch.setattr(service, "broker_symbols", lambda: [])
    with storage.connect() as db:
        db.execute("INSERT INTO sw_price_checks VALUES(?,?,?,?,?,?)",
                   ("AAPL", day, now.isoformat(), "OK", day, "[]"))

    async def catch_up():
        worker = service.Service()
        observer = SimpleNamespace(asset_count=102, event=lambda *args, **kwargs: None)
        for _ in range(9):
            await worker.price_cycle(None, observer, {"new_bars": 0, "price_updates": 0},
                                     datetime.now(UTC))
        return worker

    worker = asyncio.run(catch_up())
    now = datetime.now(UTC)
    assert calls[0] == "SPY"
    assert len(set(calls)) == len(calls) == 102
    assert service.daily_refresh_due(now) == 0
    assert snapshot(worker, now)["daily_data"] == {
        "completed_session": day, "certified_assets": 102,
        "enabled_assets": 102, "unconfirmed_assets": {},
    }


@pytest.mark.parametrize("response, expected", [
    ({"AAPL": {"latestQuote": {}}}, "SNAPSHOT_ONLY"),
    ({}, "DATA_UNAVAILABLE"),
    ("intraday_feed_or_entitlement_denied", "DATA_UNAVAILABLE"),
])
def test_overnight_snapshot_only_records_capability_and_actual_failure(database, monkeypatch,
                                                                         response, expected):
    def snapshots(symbols, feed):
        if isinstance(response, str):
            raise ObservationError(response)
        return response

    engine = intraday.IntradayEngine()
    engine.data = SimpleNamespace(
        snapshots=snapshots, regular_closes=lambda *args: {},
        bars=lambda *args: pytest.fail("indicative feed must not request optional history"),
    )
    monkeypatch.setattr(intraday.journal, "save", lambda report: None)
    report = engine.cycle(clock=lambda: datetime(2026, 11, 12, 6, tzinfo=UTC),
                          broker_factory=lambda: pytest.fail("overnight order path"))
    assert report["status"] == expected
    assert report["execution"] == "overnight_monitor_only"
    assert report["data_sources"]["bars"]["status"] == "NOT_REQUESTED"
    if isinstance(response, str):
        assert report["reason"] == response


@pytest.mark.parametrize("status,reason", [
    (401, "intraday_data_authentication_failed"),
    (403, "intraday_feed_or_entitlement_denied"),
    (422, "intraday_data_http_422"),
])
def test_distinguishes_data_errors(monkeypatch, status, reason):
    monkeypatch.setenv("STOCKSWATCH_ALPACA_KEY", "fixture")
    monkeypatch.setenv("STOCKSWATCH_ALPACA_SECRET", "fixture")
    client = IntradayData(transport=httpx.MockTransport(lambda _: httpx.Response(status)))
    try:
        with pytest.raises(ObservationError, match=reason):
            client.snapshots(["SPY"], "overnight")
    finally:
        client.close()


def test_off_hours_reports_separate_technical_gates_without_broker_budget(monkeypatch):
    monkeypatch.setattr(alpaca_paper, "_open_window", lambda *args: False)
    now = datetime(2026, 11, 12, 6, tzinfo=UTC)
    signal = dict(symbol="AAPL", name="Apple", sector="Technology", score=0,
                  regime="RISK_OFF", signals=[], reasons=[],
                  features={"volatility_annual": 0.9}, iex_dollar_volume_20d=100)
    result = alpaca_paper._preview_and_submit(
        None, {"positions": []}, [signal], completed_day(now), now,
    )
    [decision] = result["why_no_trade"]
    assert set(decision["blockers"]) == {"score", "regime", "volatility", "liquidity", "timing"}
    assert decision["not_evaluated"] == ["capital", "protection"]


def test_readonly_audit_uses_wal_memory_temp_and_does_not_create_files(database):
    with storage.connect_readonly() as db:
        assert db.execute("PRAGMA temp_store").fetchone()[0] == 2
        assert db.execute("PRAGMA query_only").fetchone()[0] == 1
        assert db.execute("SELECT sector,COUNT(*) FROM assets GROUP BY sector ORDER BY 2").fetchall()
        with pytest.raises(Exception, match="readonly"):
            db.execute("DELETE FROM assets")
    missing = Path(storage.DB_PATH).with_name("missing.sqlite3")
    with pytest.raises(Exception, match="unable to open"):
        with storage.connect_readonly(missing):
            pass
    assert not missing.exists()


def test_relative_strength_requires_aligned_positive_trade_evidence():
    now = datetime(2026, 11, 12, 6, tzinfo=UTC)
    hourly = [{"ts": (now + timedelta(hours=i)).isoformat(), "c": 100 + i * 0.15, "v": 1}
              for i in range(25)]
    btc = [{**b, "c": 100} for b in hourly]
    assert _relative_strength("AVAX/USD", hourly, btc, healthy=True, btc_stable=True)
    assert not _relative_strength("AVAX/USD", hourly, btc, healthy=True, btc_stable=False)
    btc[0]["v"] = 0
    assert not _relative_strength("AVAX/USD", hourly, btc, healthy=True, btc_stable=True)


def test_replay_stop_accounts_for_gap_through_stop():
    signal = dict(bar_at="2026-11-12T06:00:00+00:00", price=100, stop=95, target=110,
                  gates={"entry_strategy": "breakout"})
    future = [{"ts": "2026-11-12T07:00:00+00:00", "o": 100, "h": 104, "l": 96},
              {"ts": "2026-11-12T08:00:00+00:00", "o": 92, "h": 96, "l": 91}]
    result, held = _trade("BTC/USD", signal, future, fee=0, slip=0)
    assert held == 2
    assert result["r"] == pytest.approx(-1.6)
