"""StocksWatch-only OCO regression checks; no broker POSTs or real ledger writes."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
import unittest
import sqlite3
import tempfile
from pathlib import Path

from stockswatch import profit_oco as po, alpaca_paper as paper, profit_lock, storage
from stockswatch.intraday_market import ObservationError
from stockswatch.sessions import NY

UTC=timezone.utc
NOW=datetime(2026,11,9,15,30,tzinfo=UTC)

class Quotes:
    def __init__(self,stamp,bid="290",ask="290.10"):
        self.row={"t":stamp.isoformat(),"bp":bid,"ap":ask}
    def snapshots(self,symbols,feed):
        if symbols!=["ABBV"] or feed!="iex":
            raise AssertionError("unexpected market feed")
        return {"ABBV":{"latestQuote":self.row}}

class OcoFixTests(unittest.TestCase):
    def quote(self,at,checked):
        with patch.object(po,"session",return_value=(NOW-timedelta(hours=2),NOW+timedelta(hours=2))):
            return po._find_live_quote(Quotes(at),"ABBV",NOW-timedelta(seconds=40),quote_now=checked)
    def test_fresh_quote_not_compared_to_old_broker_cycle_timestamp(self):
        checked=NOW
        bid,ts=self.quote(checked-timedelta(seconds=2),checked)
        self.assertEqual(bid,Decimal("290"))
        self.assertEqual(ts,(checked-timedelta(seconds=2)).isoformat())
    def test_small_provider_clock_skew_tolerated(self):
        self.quote(NOW+timedelta(seconds=4),NOW)
    def test_quote_older_than_twenty_seconds_rejected(self):
        with self.assertRaises(po.ProtectionError):
            self.quote(NOW-timedelta(seconds=21),NOW)
    def test_quote_future_more_than_five_seconds_rejected(self):
        with self.assertRaises(po.ProtectionError):
            self.quote(NOW+timedelta(seconds=6),NOW)
    def test_crossed_and_wide_quotes_rejected(self):
        with patch.object(po,"session",return_value=(NOW-timedelta(hours=2),NOW+timedelta(hours=2))):
            for bid,ask in (("290","289"),("290","295"),("0","290")):
                with self.subTest(bid=bid,ask=ask):
                    with self.assertRaises((po.ProtectionError,ObservationError)):
                        po._find_live_quote(Quotes(NOW,bid,ask),"ABBV",NOW,quote_now=NOW)

    @staticmethod
    def certified_daily():
        cal=__import__("stockswatch.sessions",fromlist=["calendar"]).calendar()
        sessions=[x.date().isoformat() for x in cal.sessions_window("2026-11-06",-15)]
        return [{"day":d,"o":100+i,"h":102+i,"l":99+i,"c":101+i,
                 "v":10000,"source":"alpaca_iex_daily","adjustment":"RAW",
                 "observed_at":"2026-11-08T12:00:00+00:00"} for i,d in enumerate(sessions)]

    def test_certified_history_archive_fallback_does_not_mutate_stock_bars(self):
        # Exercise the real SQLite SELECT rather than mocking a module-level
        # rows() reference: the emergency script imports the patched manager
        # under the same name as the running package. Mocking rows() was not
        # stable across that loader and incorrectly rejected valid fixtures.
        expected=self.certified_daily()
        with tempfile.TemporaryDirectory(prefix="oco-certified-", dir="/dev/shm") as directory:
            db=str(Path(directory)/"offline.sqlite3")
            with sqlite3.connect(db) as c:
                c.execute("""CREATE TABLE sw_eod_observations(
                    symbol TEXT, day TEXT, o REAL,h REAL,l REAL,c REAL,v REAL,
                    source TEXT,adjustment TEXT,observed_at TEXT)""")
                c.execute("""CREATE TABLE sw_historical_bars(
                    symbol TEXT,timeframe TEXT,feed TEXT,adjustment TEXT,
                    at TEXT,trade_date TEXT,phase TEXT,observed_at TEXT,
                    o TEXT,h TEXT,l TEXT,c TEXT,v TEXT)""")
                c.executemany("""INSERT INTO sw_historical_bars VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?)""",[
                    ("ABBV","1Day","iex","raw",r["day"]+"T05:00:00+00:00",
                     r["day"],"DAILY",r["observed_at"],r["o"],r["h"],
                     r["l"],r["c"],r["v"]) for r in expected
                ])
            with patch.object(storage,"DB_PATH",db),\
                 patch("stockswatch.market.alpaca",
                       side_effect=AssertionError("Unexpected remote call")):
                result=po._candidate_bars("ABBV",NOW)
            self.assertEqual([r["day"] for r in result],
                             [r["day"] for r in expected])
            self.assertTrue(all(r["source"]=="alpaca_iex_daily"
                                and r["adjustment"]=="RAW" for r in result))
            with sqlite3.connect(db) as c:
                self.assertEqual(c.execute(
                    "SELECT COUNT(*) FROM sw_historical_bars").fetchone()[0],15)

    def test_certified_remote_alpaca_daily_fallback(self):
        expected=self.certified_daily()
        async_provider=AsyncMock(return_value=([
            {k:r[k] for k in ("day","o","h","l","c","v")} for r in expected
        ],"alpaca_iex_daily","RAW"))
        with patch.object(po,"rows",return_value=[]),\
             patch("stockswatch.market.alpaca",new=async_provider):
            result=po._candidate_bars("ABBV",NOW)
        self.assertEqual(len(result),15)
        self.assertEqual(result[0]["day"],expected[0]["day"])
        self.assertEqual(result[-1]["day"],expected[-1]["day"])
        self.assertEqual(result[-1]["source"],"alpaca_iex_daily")
        self.assertEqual(result[-1]["adjustment"],"RAW")

    def test_incomplete_remote_daily_sessions_fail_closed(self):
        expected=self.certified_daily()
        async_provider=AsyncMock(return_value=([
            {k:r[k] for k in ("day","o","h","l","c","v")} for r in expected[:-1]
        ],"alpaca_iex_daily","RAW"))
        with patch.object(po,"rows",return_value=[]),\
             patch("stockswatch.market.alpaca",new=async_provider):
            with self.assertRaisesRegex(po.ProtectionError,
                    "protection_certified_atr_15_sessions_unavailable"):
                po._candidate_bars("ABBV",NOW)

    def run_cycle(self,*,paused,open_orders=(),owned=True):
        p={"symbol":"ABBV","side":"long","asset_class":"us_equity",
           "qty":"40","qty_available":"40","avg_entry_price":"291.12"}
        snap={"account":{"id":"paper-id"},"positions":[p],"open_orders":list(open_orders),
              "fills":[{"id":"fill-test"}],"warnings":{}}
        with patch.object(po,"armed",return_value=True),\
             patch.object(po,"one",return_value={"paused":int(paused)}),\
             patch.object(po,"rows",return_value=[]),\
             patch.object(po,"_nested",return_value=[]),\
             patch.object(po,"_saved",return_value=None),\
             patch.object(po,"_entry_id",return_value="swp2-test"),\
             patch.object(po,"_candidate_bars",return_value=[{"dummy":True}]*15),\
             patch.object(po,"_find_live_quote",return_value=(Decimal("290"),NOW.isoformat())),\
             patch.object(po,"_create",return_value="oco_submitted_pending_broker_verification") as create,\
             patch.object(paper,"_position_owned",return_value=owned),\
             patch.object(profit_lock,"atr14",return_value=Decimal("2.5")),\
             patch("stockswatch.intraday_policy.phase_at",return_value=SimpleNamespace(name="CORE")):
            result=po.cycle(client=object(),snapshot=snap,now=NOW,data=object())
        return create,result
    def test_paused_new_buys_do_not_block_exits(self):
        create,result=self.run_cycle(paused=True)
        create.assert_called_once()
        self.assertTrue(result["changed"])
        self.assertTrue(result["stock_new_entries_paused"])
        self.assertFalse(result["new_protection_paused"])
    def test_already_reserved_shares_not_sold_again(self):
        create,result=self.run_cycle(paused=False,open_orders=[{"symbol":"ABBV","side":"sell","id":"old"}])
        create.assert_not_called()
        self.assertEqual(result["positions"][0]["reason"],"protection_competing_open_order")
    def test_unowned_shares_not_protected(self):
        create,result=self.run_cycle(paused=False,owned=False)
        create.assert_not_called()
        self.assertEqual(result["positions"][0]["reason"],"protection_position_not_eod_owned")

if __name__=="__main__":
    unittest.main(verbosity=2)
