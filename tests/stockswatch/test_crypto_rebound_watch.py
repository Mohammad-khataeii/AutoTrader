"""Unit tests for pure research-only early-rebound scoring."""
from datetime import datetime, timedelta, timezone
from stockswatch.crypto_rebound_watch import assess, market_breadth


def _bars():
    anchor = datetime(2026, 11, 11, tzinfo=timezone.utc)
    values = [110 - i * 0.48 for i in range(20)] + [100.2, 99.8, 100.0, 100.7]
    return [{"ts": (anchor + timedelta(hours=i)).isoformat(),
             "o": v, "h": v + 0.3, "l": v - 0.3, "c": v, "v": 1.0}
            for i, v in enumerate(values)]


def test_confirmed_shadow_does_not_create_order():
    result = assess(_bars(), 0.75, 47)
    assert result["passed"] is True
    assert 0 < result["stop"] < 100.7 < result["target"]
    assert set(result) == {"passed", "checks", "score", "stop", "target"}


def test_zero_volume_is_not_executable_trade_evidence():
    bars = _bars()
    bars[-1]["v"] = 0
    assert not assess(bars, 0.75, 47)["passed"]


def test_missing_recent_hour_fails_closed():
    bars = _bars()
    bars[-2]["ts"] = bars[-3]["ts"]
    assert not assess(bars, 0.75, 47)["passed"]


def test_falling_knife_rejected():
    bars = _bars()
    bars[-1]["c"] = bars[-2]["c"] - 1
    assert not assess(bars, 0.75, 47)["passed"]


def test_no_chasing_large_rebound():
    bars = _bars()
    bars[-1]["c"] += 5
    assert not assess(bars, 0.75, 47)["passed"]


def test_invalid_or_short_history_fails_closed():
    assert not assess(_bars()[:10], 0.75, 47)["passed"]
    bars = _bars()
    bars[-1]["c"] = float('nan')
    assert not assess(bars, 0.75, 47)["passed"]
    assert not assess(_bars(), 0, 47)["passed"]


def test_breadth_uses_only_executable_signal_rows():
    xs = [{"symbol": "BTC/USD", "action": "HOLD"},
          {"symbol": "ETH/USD", "action": "HOLD"},
          {"symbol": "SOL/USD", "action": "WAIT"}]
    g = {"BTC/USD": {"hourly_uptrend": False,"daily_above_ema200": False,
                     "shadow_rebound_watch": True},
         "ETH/USD": {"hourly_uptrend": False, "daily_above_ema200": False}}
    r = market_breadth(xs, g)
    assert r["regime"] == "BROAD_DOWNTREND"
    assert r["usd_ready"] == 2
    assert r["usd_waiting"] == 1
    assert r["shadow_rebound_watch_count"] == 1
