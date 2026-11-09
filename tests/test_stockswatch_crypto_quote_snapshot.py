"""Latest crypto quotes must never be confused with completed hourly research bars.

Synthetic Alpaca responses only: no network, no broker orders and no DB writes.
"""
from datetime import datetime, timedelta, timezone

import pytest

from stockswatch import alpaca_crypto as ac


def _quote(now, bid=74393.90, ask=74413.20):
    return {"t": now.isoformat(), "bp": bid, "ap": ask}


def test_live_bid_ask_is_not_stale_hourly_close(monkeypatch):
    now = datetime.now(timezone.utc)
    history_close = 74054.64
    calls = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def get(self, path, params):
            calls.append((path, params))
            assert path == "/v1beta3/crypto/us/latest/quotes"
            assert params == {"symbols": ",".join(ac.PAIRS)}
            return {"quotes": {"BTC/USD": _quote(now)}}

    monkeypatch.setattr(ac, "_quote_cached_result", None)
    monkeypatch.setattr(ac, "_quote_cached_at", 0.0)
    result = ac.latest_quotes_snapshot(factory=FakeClient)
    btc = result["quotes"]["BTC/USD"]

    assert result["available"] is True
    assert btc["available"] is True
    assert btc["bid"] == 74393.90
    assert btc["ask"] == 74413.20
    assert btc["midpoint"] == pytest.approx(74403.55)
    assert btc["midpoint"] != history_close
    assert result["quotes"]["ETH/USD"]["available"] is False

    second = ac.latest_quotes_snapshot(factory=FakeClient)
    assert second == result
    assert len(calls) == 1  # short cache prevents repeat Alpaca requests
    assert all(x[0] == "/v1beta3/crypto/us/latest/quotes" for x in calls)


def test_stale_quote_fails_closed(monkeypatch):
    old = datetime.now(timezone.utc) - timedelta(minutes=6)

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def get(self, path, params):
            return {"quotes": {"BTC/USD": _quote(old)}}

    monkeypatch.setattr(ac, "_quote_cached_result", None)
    monkeypatch.setattr(ac, "_quote_cached_at", 0.0)
    result = ac.latest_quotes_snapshot(factory=FakeClient)
    btc = result["quotes"]["BTC/USD"]
    assert btc == {"available": False, "reason": "crypto_quote_stale"}
    assert result["quotes"]["BTC/USD"].get("bid") is None


def test_crossed_quote_is_unavailable():
    now = datetime.now(timezone.utc)
    with pytest.raises(ac.CryptoDataError, match="crypto_quote_crossed"):
        ac._checked_quote(_quote(now, bid=74450, ask=74400), now)


def test_execution_quote_uses_independent_alpaca_get():
    now = datetime.now(timezone.utc)
    calls = []

    class Stub:
        def get(self, path, params):
            calls.append(params)
            return {"quotes": {"BTC/USD": _quote(now)}}

    bid, ask, observed_at = ac.CryptoData.latest_bid(Stub(), "BTC/USD")
    assert (bid, ask) == (74393.90, 74413.20)
    assert observed_at
    assert calls == [{"symbols": "BTC/USD"}]


def test_unknown_symbols_are_not_passed_through(monkeypatch):
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def get(self, path, params):
            return {"quotes": {"UNLISTED/USD": _quote(datetime.now(timezone.utc))}}

    monkeypatch.setattr(ac, "_quote_cached_result", None)
    monkeypatch.setattr(ac, "_quote_cached_at", 0.0)
    result = ac.latest_quotes_snapshot(factory=FakeClient)
    assert result["available"] is False
    assert result["quotes"] == {}
    assert result["reason"] == "crypto_quote_batch_invalid"
