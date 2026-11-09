"""Offline regression tests for crypto-only continuation and replay.

No network, broker mutation, stocks trading, or persistent databases.
"""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from stockswatch import alpaca_crypto as ac
from stockswatch.crypto_continuation import evaluate_pullback
from stockswatch.crypto_strategy_replay import _trade, replay


class ContinuationUnitTests(unittest.TestCase):
    def setUp(self):
        self.candles = [
            {"o": 100.2, "h": 101.15, "l": 100.2, "c": 100.5, "v": 5}
            for _ in range(40)
        ]
        self.candles[-1] = {"o": 100.6, "h": 101.1, "l": 100.5,
                            "c": 101.0, "v": 100}

    def test_clean_reclaim(self):
        d = evaluate_pullback(self.candles, 100.6, 1.0, 58.0)
        self.assertTrue(d["passed"], d)

    def test_zero_volume_does_not_approve(self):
        self.candles[-1]["v"] = 0
        self.assertFalse(evaluate_pullback(self.candles,100.6,1.0,58)["passed"])

    def test_chasing_large_extension_does_not_approve(self):
        self.candles[-1].update(o=103.1,c=104.0,h=104.2)
        self.assertFalse(evaluate_pullback(self.candles,100.6,1.0,58)["passed"])

    def test_rsi_near_overbought_does_not_approve(self):
        self.assertFalse(evaluate_pullback(self.candles,100.6,1.0,71)["passed"])

    def _history(self):
        now = datetime(2026,11,9,20,0,tzinfo=timezone.utc)
        last_hour = now - timedelta(hours=1)
        hourly=[]
        for i in range(260):
            bar=dict(self.candles[0])
            bar["ts"] = (last_hour-timedelta(hours=259-i)).isoformat()
            hourly.append(bar)
        hourly[-1].update(dict(self.candles[-1]))
        daily=[]
        for i in range(260):
            daily.append({"ts":(now.replace(hour=0)-timedelta(days=260-i)).isoformat(),
                          "o":99,"h":103,"l":98,"c":101,"v":100})
        return now,hourly,daily

    def test_legacy_breakout_remains_hold_but_continuation_can_buy(self):
        now,hourly,daily=self._history()
        def fake_ema(values,n):
            if n==20:return 100.6
            if n==50:return 100.1
            return 99.0 if values is not None and len(values)>0 and values[0]==100.5 else 90.0
        with patch.object(ac,"_ema",side_effect=[100.6,100.1,99.0,90.0]*2),\
             patch.object(ac,"_atr",return_value=1.0),\
             patch.object(ac,"_rsi",return_value=58.0):
            before=ac.evaluate_completed_bars("AAVE/USD",hourly,daily,now,
                                              allow_continuation=False)
            after=ac.evaluate_completed_bars("AAVE/USD",hourly,daily,now,
                                             allow_continuation=True)
        self.assertEqual(before["action"],"HOLD")
        self.assertEqual(after["action"],"BUY")
        self.assertEqual(after["reason"],"daily_uptrend_hourly_pullback_reclaim")
        self.assertEqual(after["gates"]["entry_strategy"],"continuation")

    def test_cannot_use_incomplete_hourly_candle(self):
        now,hourly,daily=self._history()
        hourly[-1]["ts"]=now.isoformat()
        with self.assertRaises(ac.CryptoDataError):
            ac.evaluate_completed_bars("AAVE/USD",hourly,daily,now,
                                       allow_continuation=True)

    def test_research_only_pair_cannot_be_buy(self):
        now,hourly,daily=self._history()
        with patch.object(ac,"_ema",side_effect=[100.6,100.1,99.0,90.0]),\
             patch.object(ac,"_atr",return_value=1.0),\
             patch.object(ac,"_rsi",return_value=58.0):
            x=ac.evaluate_completed_bars("AAVE/USDC",hourly,daily,now,
                                         allow_continuation=True)
        self.assertEqual(x["action"],"HOLD")
        self.assertEqual(x["reason"],"non_usd_quote_research_only")

    def test_stop_first_when_both_levels_touched(self):
        signal = {
          "bar_at":"2026-11-09T19:00:00+00:00", "price":100,
          "stop":98, "target":105,
          "gates":{"entry_strategy":"continuation"},
        }
        nextbar=[{"ts":"2026-11-09T20:00:00+00:00",
                  "o":100,"h":106,"l":97,"c":101}]
        trade,held=_trade("AAVE/USD",signal,nextbar)
        self.assertEqual(trade["exit"],"stop_first")
        self.assertLess(trade["r"],0)
        self.assertEqual(held,1)

    def test_replay_with_missing_history_refuses_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"ledger.sqlite3"
            with sqlite3.connect(path) as conn:
                conn.execute("""CREATE TABLE ac_bars
                    (symbol TEXT,timeframe TEXT,ts TEXT,o REAL,h REAL,
                     l REAL,c REAL,v REAL,source TEXT,ingested_at TEXT)""")
            result=replay(path)
        self.assertFalse(result["approved"])
        self.assertEqual(result["state"],"INSUFFICIENT_HISTORY")


if __name__ == "__main__":
    unittest.main()
