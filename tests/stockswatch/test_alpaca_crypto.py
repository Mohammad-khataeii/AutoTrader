"""AlpacaCrypto has no legacy engine dependency and no crypto short path."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from stockswatch import alpaca_crypto as ac, alpaca_crypto_paper as ap, storage

UTC = timezone.utc


def _database(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "crypto-test.sqlite3"))
    storage.init()
    ac.initialize()


def test_new_crypto_archive_never_changes_stockswatch_financial_tables(monkeypatch, tmp_path):
    _database(monkeypatch, tmp_path)
    before = storage.one("SELECT * FROM portfolio WHERE id=1")
    ac.queue(datetime(2026, 11, 7, 16, tzinfo=UTC))
    assert storage.one("SELECT COUNT(*) AS n FROM ac_jobs")["n"] > 100
    assert storage.one("SELECT COUNT(*) AS n FROM ac_assets")["n"] == 10
    assert storage.one("SELECT * FROM portfolio WHERE id=1") == before
    dashboard = ac.dashboard()
    assert dashboard["mode"] == "ALPACA_CRYPTO_SPOT_PAPER"
    assert dashboard["short_supported"] is False
    assert dashboard["margin_supported"] is False
    assert dashboard["paper_orders_enabled"] is False


def test_no_signal_without_complete_history(monkeypatch, tmp_path):
    _database(monkeypatch, tmp_path)
    sig = ac.signal("BTC/USD", datetime(2026, 11, 7, 16, tzinfo=UTC))
    assert sig["action"] == "WAIT"
    assert sig["reason"] == "insufficient_completed_history"
    with pytest.raises(ac.CryptoDataError):
        ac.signal("INVALID/PAIR")


def test_crypto_bar_provider_pagination_and_incomplete_bars(monkeypatch):
    monkeypatch.setenv("STOCKSWATCH_ALPACA_KEY", "public-test-key")
    monkeypatch.setenv("STOCKSWATCH_ALPACA_SECRET", "test-secret")
    now = datetime.now(UTC)
    prior = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    current = now.replace(minute=0, second=0, microsecond=0)
    def reply(req):
        assert req.url.path == "/v1beta3/crypto/us/bars"
        assert req.url.params["timeframe"] == "1Hour"
        return httpx.Response(200, json={"bars": {"BTC/USD": [
            {"t": prior.isoformat(), "o": 100, "h": 110, "l": 90, "c": 105, "v": 10},
            {"t": current.isoformat(), "o": 105, "h": 111, "l": 100, "c": 108, "v": 5}
        ]}, "next_page_token": None})
    job = {"symbol":"BTC/USD", "timeframe":"1Hour",
           "start_at":(prior-timedelta(hours=1)).isoformat(),
           "end_at":(current+timedelta(hours=1)).isoformat(), "token":None}
    with ac.CryptoData(transport=httpx.MockTransport(reply)) as data:
        bars, token = data.bars(job)
    assert token is None
    assert len(bars) == 1
    assert bars[0][2] == prior.isoformat()


def test_background_pages_commit_only_verified_data(monkeypatch, tmp_path):
    _database(monkeypatch, tmp_path)
    now = datetime(2026, 11, 7, 16, tzinfo=UTC)
    with storage.connect() as db:
        db.execute("""INSERT INTO ac_jobs (symbol,timeframe,start_at,end_at,state)
            VALUES(?,?,?,?, 'PENDING')""",
            ("BTC/USD", "1Day", "2026-10-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00"))
    class Provider:
        def bars(self, job):
            return [("BTC/USD", "1Day", "2026-10-15T00:00:00+00:00",
                    10.0, 11.0, 9.0, 10.5, 400.0,
                    "alpaca_crypto_us_quote_midpoint", now.isoformat())], None
    assert ac.backfill_step(Provider(), now) is True
    assert ac.backfill_step(Provider(), now) is False
    assert storage.one("SELECT COUNT(*) AS n FROM ac_bars")["n"] == 1
    assert storage.one("SELECT state FROM ac_jobs WHERE symbol='BTC/USD'")["state"] == "COMPLETE"


def test_paper_execution_never_uses_equity_credentials_or_same_account(monkeypatch):
    monkeypatch.setenv("ALPACA_CRYPTO_PAPER_KEY", "dedicated-test-key")
    monkeypatch.setenv("ALPACA_CRYPTO_PAPER_SECRET", "test-secret")
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_ACCOUNT_ID", "stocks-paper")
    monkeypatch.setenv("ALPACA_CRYPTO_PAPER_ACCOUNT_ID", "stocks-paper")
    with pytest.raises(ap.CryptoPaperError, match="distinct"):
        ap.expected_account()
    monkeypatch.setenv("ALPACA_CRYPTO_PAPER_ACCOUNT_ID", "crypto-paper")
    assert ap.expected_account() == "crypto-paper"


def test_crypto_short_and_margin_are_never_broker_submittable(monkeypatch):
    monkeypatch.setenv("ALPACA_CRYPTO_PAPER_KEY", "dedicated-test-key")
    monkeypatch.setenv("ALPACA_CRYPTO_PAPER_SECRET", "test-secret")
    monkeypatch.setenv("ALPACA_CRYPTO_ALLOW_PAPER_ORDERS", "1")
    calls = []
    def transport(req):
        calls.append(req)
        return httpx.Response(200, json={})
    with ap.CryptoPaperClient(transport=httpx.MockTransport(transport)) as broker:
        with pytest.raises(ap.CryptoPaperError):
            broker.submit({
                "symbol": "BTC/USD", "side": "sell", "type": "market",
                "time_in_force": "gtc", "notional": "25",
                "client_order_id": "acp1-" + "a"*40,
            })
        with pytest.raises(ap.CryptoPaperError):
            broker.submit({
                "symbol": "ETH/USD", "side": "buy", "type": "market",
                "time_in_force": "gtc", "notional": "25",
                "margin": "2", "client_order_id": "acp1-" + "b"*40,
            })
        with pytest.raises(ap.CryptoPaperError):
            broker.submit({
                "symbol": "ETH/USD", "side": "buy", "type": "market",
                "time_in_force": "day", "notional": "25",
                "client_order_id": "acp1-" + "b"*40,
            })
    assert not calls


def test_ambiguous_order_is_never_retried(monkeypatch, tmp_path):
    _database(monkeypatch, tmp_path)
    class Uncertain:
        def submit(self, payload):
            raise ap.CryptoPaperError("crypto_paper_transport_uncertain")
    first = ap._submit_intent(Uncertain(), "account-1", "BTC/USD", "buy",
                              "2026-11-07T15:00:00Z", "test", notional="35.00")
    second = ap._submit_intent(Uncertain(), "account-1", "BTC/USD", "buy",
                               "2026-11-07T15:00:00Z", "test", notional="35.00")
    assert first == "uncertain_intent_no_automatic_retry"
    assert second == "duplicate_intent_refused"
    assert storage.one("SELECT COUNT(*) AS n FROM ac_intents")["n"] == 1
    assert storage.one("SELECT state FROM ac_intents")["state"] == "UNCERTAIN"
