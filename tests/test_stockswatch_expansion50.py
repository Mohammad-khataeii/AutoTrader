"""Offline tests: 50 new liquid paper equities and GET-only daily archive.

No live Alpaca HTTP calls, no broker orders and no real ledger mutations.
"""
from __future__ import annotations
import sqlite3
import tempfile
import unittest
from datetime import UTC,datetime,date,timedelta
from pathlib import Path
from unittest.mock import patch

from stockswatch import storage,backfill,expansion50_history as w
from stockswatch.sessions import calendar,completed_day,history_days,instant
from stockswatch.universe import (
    REGISTRY, ASSETS, LEGACY, ADDITIONS, EXPANSION50, NEW, BENCHMARKS,
)

NOW=datetime(2026,11,9,16,0,tzinfo=UTC)
EXTRA={s for s,_,_ in EXPANSION50}


class ExpansionFiftyTests(unittest.TestCase):
    def test_preserves_all_52_original_instruments_and_50_new(self):
        self.assertEqual(len(EXPANSION50),50)
        self.assertEqual(len(LEGACY),32)
        self.assertEqual(len(ADDITIONS),20)
        self.assertEqual(len(REGISTRY),102)
        self.assertEqual(len(ASSETS),102)
        self.assertEqual(len({s for s,_,_ in ASSETS}),102)
        self.assertEqual({x for x,_,_ in ASSETS[:52]},
                         {x for x,_,_ in (*LEGACY,*ADDITIONS)})
        self.assertEqual(BENCHMARKS,{"SPY","QQQ"})
        self.assertTrue(EXTRA.issubset(NEW))
        self.assertTrue(all(REGISTRY[s]["instrument_type"]=="COMPANY_EQUITY" for s in EXTRA))
        self.assertTrue(all(REGISTRY[s]["strategies"]==("EOD_LONG","INTRADAY_LONG","SHORT") for s in EXTRA))

    def test_resumable_history_jobs_prioritize_recent_data_and_limit_minute_disk(self):
        requested=list(backfill.jobs(NOW,new_only=True,minute_days=20))
        self.assertTrue(requested)
        new_daily=[row for row in requested if row[0]=="IBM" and row[1]=="1Day"]
        previous_daily=[row for row in requested if row[0]=="TSLA" and row[1]=="1Day"]
        new_minute=[row for row in requested if row[0]=="IBM" and row[1]=="1Min"]
        previous_minute=[row for row in requested if row[0]=="TSLA" and row[1]=="1Min"]
        self.assertTrue(10<=len(new_daily)<=23)
        self.assertGreater(len(previous_daily),100)
        self.assertEqual(len(new_minute),5)
        self.assertEqual(len(previous_minute),19)
        # The `new_only` flag restricts DAILY jobs to newly added symbols;
        # the existing minute-history queue intentionally still includes
        # the original legacy tickers. Never silently remove that coverage.
        daily=[row for row in requested if row[1]=="1Day"]
        minute=[row for row in requested if row[1]=="1Min"]
        self.assertTrue(all(row[0] in NEW for row in daily))
        self.assertTrue(any(row[0] not in NEW for row in minute))
        self.assertTrue(all(row[0] in REGISTRY for row in requested))
        self.assertEqual(len(new_daily),len(set((x[3],x[4]) for x in new_daily)))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="sw-expansion50-",dir="/dev/shm")
        self.addCleanup(self.temp.cleanup)
        self.db=str(Path(self.temp.name)/"offline.sqlite3")
        pp=patch.object(storage,"DB_PATH",self.db)
        pp.start()
        self.addCleanup(pp.stop)
        storage.init()
        storage.init_execution()
        backfill.initialize()
        w.initialize()

    def test_data_backfill_does_not_certify_current_execution_or_touch_other_symbols(self):
        day=completed_day(NOW)
        bars=[{"day":d,"o":100.0,"h":102.0,"l":99.0,"c":101.0,"v":10000.0}
              for d in history_days(day)]
        self.assertEqual(len(bars),201)
        w._store("IBM",bars,NOW,day)
        self.assertTrue(w.verify_201("IBM",day))
        self.assertFalse(w.verify_201("ABBV",day))
        with sqlite3.connect(self.db) as c:
            count=lambda table:c.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]
            self.assertEqual(count("bars"),201)
            self.assertEqual(count("sw_historical_bars"),201)
            self.assertEqual(count("sw_eod_observations"),0)
            self.assertEqual(count("sw_price_checks"),0)
            self.assertEqual(count("sw_alpaca_intents") if
                             c.execute("SELECT name FROM sqlite_master WHERE name='sw_alpaca_intents'").fetchone()
                             else 0,0)
        w._store("IBM",bars,NOW,day)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM bars").fetchone()[0],201)

    def test_outside_universe_refused_and_no_data_added(self):
        with self.assertRaisesRegex(ValueError,"outside_allowlist"):
            w._store("AAPL",[],NOW,completed_day(NOW))
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM bars").fetchone()[0],0)

    def test_incomplete_history_cannot_be_classified_as_ready(self):
        day=completed_day(NOW)
        dates=history_days(day)
        bars=[{"day":d,"o":100.0,"h":102.0,"l":99.0,"c":101.0,"v":10000.0}
              for d in dates[:-1]]
        w._store("IBM",bars,NOW,day)
        self.assertFalse(w.verify_201("IBM",day))


if __name__=="__main__":
    unittest.main(verbosity=2)
