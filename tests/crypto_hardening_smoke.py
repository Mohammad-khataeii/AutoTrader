"""Offline crypto-only release smoke tests. No network or real trading ledger."""
from __future__ import annotations
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from stockswatch import alpaca_crypto as ac, alpaca_crypto_paper as ap, storage

UTC=timezone.utc
NOW=datetime(2026,11,9,14,30,tzinfo=UTC)


class CryptoHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="ac-release-test-",dir="/dev/shm")
        self.addCleanup(self.temp.cleanup)
        patcher=patch.object(storage,"DB_PATH",str(Path(self.temp.name)/"paper-test.sqlite3"))
        patcher.start()
        self.addCleanup(patcher.stop)
        ac.initialize()

    @staticmethod
    def fake_candles(volume):
        hour=NOW.replace(minute=0)-timedelta(hours=1)
        day=NOW.replace(hour=0,minute=0)-timedelta(days=1)
        hourly=[{"ts":(hour-timedelta(hours=259-i)).isoformat(),
                 "c":2.0,"o":2.0,"h":2.1,"l":1.9,"v":volume}
                 for i in range(260)]
        hourly[-1].update(c=2.4,h=2.5,l=2.3)
        daily=[{"ts":(day-timedelta(days=259-i)).isoformat(),
                "c":2.0,"o":2.0,"h":2.1,"l":1.9,"v":volume}
               for i in range(260)]
        return hourly,daily

    def _signal(self,volume, *,stale=False):
        hourly,daily=self.fake_candles(volume)
        if stale:
            for r in hourly:
                r["ts"]=(datetime.fromisoformat(r["ts"])-timedelta(hours=1)).isoformat()
        def fake_rows(query,params=()):
            if "timeframe='1Hour'" in query:
                return hourly
            if "timeframe='1Day'" in query:
                return daily
            raise AssertionError("unexpected SQL")
        fake_ema=lambda values,n: 1.4 if n==20 else 1.1 if n==50 else 0.9
        with patch.object(ac,"rows",side_effect=fake_rows),\
             patch.object(ac,"_ema",side_effect=fake_ema),\
             patch.object(ac,"_rsi",return_value=60.0),\
             patch.object(ac,"_atr",return_value=0.02):
            return ac.signal("BTC/USD",NOW)

    def test_quote_allows_five_second_clock_skew_only(self):
        def quote(seconds):
            return {"t":(NOW+timedelta(seconds=seconds)).isoformat(),
                    "bp":"100","ap":"101"}
        self.assertEqual(ac._checked_quote(quote(3),NOW)["bid"],100.0)
        for future in (6,61):
            with self.assertRaises(ac.CryptoDataError):
                ac._checked_quote(quote(future),NOW)
        with self.assertRaises(ac.CryptoDataError):
            ac._checked_quote(quote(-181),NOW)

    def test_exact_completed_hour_required(self):
        self.assertEqual(self._signal(12,stale=True)["reason"],
                         "latest_completed_hourly_bar_missing")
        self.assertEqual(self._signal(12)["action"],"BUY")

    def test_quote_only_breakout_does_not_buy(self):
        result=self._signal(0)
        self.assertEqual(result["action"],"HOLD")
        self.assertEqual(result["reason"],"quote_only_breakout_no_trade_volume")
        self.assertTrue(all(result["gates"][k] for k in (
            "hourly_uptrend","daily_above_ema200","20_hour_breakout",
            "rsi_volatility_healthy")))

    def test_missing_hour_fetches_only_missing_symbols(self):
        expected=(NOW.replace(minute=0)-timedelta(hours=1)).isoformat()
        class FakeData:
            called=[]
            def bars(self,job):
                self.called.append(job["symbol"])
                return [(job["symbol"],"1Hour",expected,2.,2.1,1.9,2.,3.,
                         "offline-test",NOW.isoformat())],None
        data=FakeData()
        with patch.object(ac,"PAIRS",("BTC/USD","ETH/USD")),\
             patch.object(ac,"_recent_last_key",None),\
             patch.object(ac,"_recent_last_attempt",0.0):
            self.assertEqual(ac.ensure_latest_completed_hourly(data,NOW),"crypto_hourly_caught_up")
            self.assertEqual(sorted(data.called),["BTC/USD","ETH/USD"])
            self.assertEqual(ac.ensure_latest_completed_hourly(data,NOW),"crypto_hourly_current")
            self.assertEqual(len(data.called),2)

    def test_execution_outcome_persistence_wrapper(self):
        with patch.object(ap,"_run_paper_cycle_once",return_value="no_approved_spot_long_signal"):
            result=ap.run_paper_cycle(None,NOW)
        self.assertEqual(result,"no_approved_spot_long_signal")
        with storage.connect() as c:
            rows=c.execute("SELECT outcome FROM ac_execution_cycles").fetchall()
        self.assertEqual([row[0] for row in rows],["no_approved_spot_long_signal"])

    def test_signal_gate_schema_is_isolated(self):
        with storage.connect() as c:
            expected={"ac_signal_gates","ac_execution_cycles"}
            actual={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue(expected.issubset(actual))
            self.assertNotIn("sw_protection",actual)


if __name__=="__main__":
    unittest.main(verbosity=2)
