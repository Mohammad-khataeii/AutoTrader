"""Alpaca five-minute research and PAPER-only behavior."""
import os
from datetime import datetime, timedelta, timezone

import pytest

from stockswatch import crypto_micro as micro

UTC = timezone.utc


def synthetic(symbol="BTC/USD", drop_btc=False):
    start = datetime(2026,11,16,5,0,tzinfo=UTC)
    close = 100.0
    candles = []
    for i in range(36):
        change = -0.13 if i % 3 == 0 and i < 33 else 0.10
        close += change
        candles.append({
            "ts": (start + timedelta(minutes=5*i)).isoformat(),
            "o":close-0.04, "h":close+0.05, "l":close-0.25,
            "c":close, "v":4.0,
        })
    if drop_btc:
        for i in range(29,36):
            candles[i]["c"] = candles[28]["c"] * (1 - 0.003 * (i-28))
            candles[i]["o"] = candles[i]["c"]
            candles[i]["h"] = candles[i]["c"] + 0.05
            candles[i]["l"] = candles[i]["c"] - 0.25
    return candles


def test_five_minute_signal_is_causal_and_not_unconditionally_blocked():
    candles = synthetic()
    at = datetime.fromisoformat(candles[-1]["ts"]) + timedelta(minutes=5)
    result = micro.evaluate("BTC/USD",candles,at)
    assert result["action"] == "BUY", result
    assert result["reason"] == "micro_5m_momentum_paper"
    assert result["stop"] < result["price"] < result["target"]
    assert result["bar_at"].startswith("micro:")


def test_reject_incomplete_bar_and_missing_interval():
    candles=synthetic()
    at=datetime.fromisoformat(candles[-1]["ts"]) + timedelta(minutes=5)
    assert micro.evaluate("BTC/USD",candles,at-timedelta(minutes=1))["action"]=="HOLD"
    candles[-3]["ts"]=candles[-4]["ts"]
    assert micro.evaluate("BTC/USD",candles,at)["action"]=="HOLD"


def test_reject_zero_traded_volume_and_quote_spike():
    candles=synthetic()
    at=datetime.fromisoformat(candles[-1]["ts"]) + timedelta(minutes=5)
    candles[-1]["v"]=0
    assert micro.evaluate("BTC/USD",candles,at)["action"]=="HOLD"
    candles=synthetic()
    candles[-3]["v"]=0
    candles[-3]["c"]=candles[-3]["o"]*1.08
    candles[-3]["h"]=candles[-3]["c"]*1.001
    assert micro.evaluate("BTC/USD",candles,at)["reason"]=="micro_untraded_quote_spike"


def test_research_mode_never_authorizes_broker_orders(monkeypatch):
    monkeypatch.setenv("ALPACA_CRYPTO_MICRO_MODE","paper")
    monkeypatch.delenv("ALPACA_CRYPTO_ALLOW_PAPER_ORDERS",raising=False)
    assert micro.mode()=="research"
    monkeypatch.setenv("ALPACA_CRYPTO_ALLOW_PAPER_ORDERS","1")
    monkeypatch.setenv("LIVE_TRADING_ENABLED","true")
    assert micro.mode()=="research"
    monkeypatch.setenv("LIVE_TRADING_ENABLED","false")
    assert micro.mode()=="paper"


def test_bearish_btc_vetoes_altcoin():
    candles=synthetic()
    at=datetime.fromisoformat(candles[-1]["ts"]) + timedelta(minutes=5)
    btc=synthetic(drop_btc=True)
    result=micro.evaluate("ETH/USD",candles,at,btc_recent=btc)
    assert not result["gates"]["checks"]["btc_30m_not_liquidating"]


def test_quote_only_candles_are_not_traded():
    candles=synthetic()
    at=datetime.fromisoformat(candles[-1]["ts"]) + timedelta(minutes=5)
    for x in candles[-6:]:
        x["v"]=0
    assert micro.evaluate("BTC/USD",candles,at)["action"]=="HOLD"
