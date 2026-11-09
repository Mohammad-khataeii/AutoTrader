"""Offline coverage of 70-market AlpacaCrypto catalog, quote units and warmup.

No network, no actual paper orders, no data writes outside /dev/shm.
"""
from __future__ import annotations
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

from stockswatch import alpaca_crypto as ac, alpaca_crypto_paper as ap
from stockswatch import crypto_expansion50_warmup as worker,storage

UTC=timezone.utc


class CryptoPlus50Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="ac-plus50-",dir="/dev/shm")
        self.addCleanup(tmp.cleanup)
        db=Path(tmp.name)/"offline.sqlite3"
        patcher=patch.object(storage,"DB_PATH",str(db))
        patcher.start()
        self.addCleanup(patcher.stop)
        ac.initialize()
        worker.initialize()
        self.now=datetime.now(UTC).replace(minute=32,second=0,microsecond=0)

    def test_exact_50_more_pairs_preserve_existing_20(self):
        self.assertEqual(len(ac.BASE_PAIRS),10)
        self.assertEqual(len(ac.EXPANSION_PAIRS),10)
        self.assertEqual(len(ac.EXPANSION50_PAIRS),50)
        self.assertEqual(len(ac.PAIRS),70)
        self.assertEqual(len(set(ac.PAIRS)),70)
        self.assertEqual(ac.PAIRS[:20],ac.BASE_PAIRS+ac.EXPANSION_PAIRS)
        self.assertEqual(len(ac.EXECUTION_PAIRS),33)
        self.assertEqual(len(ac.RESEARCH_ONLY_PAIRS),37)
        self.assertTrue(all(p.endswith("/USD") for p in ac.EXECUTION_PAIRS))
        self.assertTrue(all(not p.endswith("/USD") for p in ac.RESEARCH_ONLY_PAIRS))
        with storage.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ac_assets").fetchone()[0],70)

    def test_cross_quote_cannot_create_paper_order(self):
        with self.assertRaises(ap.CryptoPaperError):
            ap._canonical("BTC/USDT")
        with self.assertRaises(ap.CryptoPaperError):
            ap._canonical("ETH/BTC")
        self.assertEqual(ap._canonical("BAT/USD"),"BAT/USD")
        payload={"symbol":"BTC/USDT","side":"buy","type":"market",
            "time_in_force":"gtc","notional":"15",
            "client_order_id":"acp1-"+"a"*40}
        with patch.object(ap,"enabled",return_value=True):
            with self.assertRaisesRegex(ap.CryptoPaperError,"crypto_unsafe_order_payload"):
                ap.CryptoPaperClient.submit(None,payload)

    def test_asset_verification_avoids_research_only_trading(self):
        def asset(sym):
            return {"symbol":sym,"class":"crypto","status":"active","tradable":True,
                "fractionable":True,"shortable":False,"marginable":False,
                "min_order_size":"0.001","min_trade_increment":"0.000001",
                "price_increment":"0.00000001"}
        class Broker:
            def assets(self):
                return [asset("BAT/USD"),asset("AAVE/USDC")]
        ap.verify_assets(Broker())
        with storage.connect() as db:
            eligible=db.execute("SELECT eligible FROM ac_assets WHERE symbol='BAT/USD'").fetchone()[0]
            other=db.execute("SELECT eligible,reason FROM ac_assets WHERE symbol='AAVE/USDC'").fetchone()
        self.assertEqual(eligible,1)
        self.assertEqual(other["eligible"],0)
        self.assertEqual(other["reason"],"research_only_non_usd_quote")

    def test_research_only_cross_quote_never_emits_buy(self):
        now=self.now
        hour=ac._floor(now,"1Hour")-timedelta(hours=1)
        day=ac._floor(now,"1Day")-timedelta(days=1)
        hourly=[{"ts":(hour-timedelta(hours=259-i)).isoformat(),
                 "o":2.0,"h":2.1,"l":1.9,"c":2.0,"v":100.0}
                 for i in range(260)]
        hourly[-1].update(c=2.4,h=2.5,l=2.3)
        daily=[{"ts":(day-timedelta(days=259-i)).isoformat(),
                "o":2.0,"h":2.1,"l":1.9,"c":2.0,"v":100.0}
               for i in range(260)]
        def fake_rows(sql,params=()):
            self.assertIn("ORDER BY ts DESC",sql)
            if "timeframe='1Hour'" in sql: return hourly[::-1]
            if "timeframe='1Day'" in sql: return daily[::-1]
            self.fail("Unexpected query")
        with patch.object(ac,"rows",side_effect=fake_rows),\
             patch.object(ac,"_ema",side_effect=lambda x,n:1.4 if n==20 else 1.1 if n==50 else 0.9),\
             patch.object(ac,"_rsi",return_value=60.0),\
             patch.object(ac,"_atr",return_value=0.02):
            result=ac.signal("BTC/USDT",now)
            eligible=ac.signal("BAT/USD",now)
        self.assertEqual(result["action"],"HOLD")
        self.assertEqual(result["reason"],"non_usd_quote_research_only")
        self.assertEqual(eligible["action"],"BUY")

    def test_latest_quote_requests_are_bounded_and_currency_aware(self):
        batches=[]
        class FakeData:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def get(self,path,params):
                names=params["symbols"].split(",")
                batches.append(names)
                selfpath="/v1beta3/crypto/us/latest/quotes"
                assert path==selfpath
                return {"quotes":{x:{"t":datetime.now(UTC).isoformat(),
                    "bp":"99","ap":"100"} for x in names}}
        with patch.object(ac,"_quote_cached_result",None),\
             patch.object(ac,"_quote_cached_at",0):
            result=ac.latest_quotes_snapshot(factory=FakeData)
        self.assertTrue(result["available"])
        self.assertEqual([len(x) for x in batches],[20,20,20,10])
        self.assertEqual(result["quotes"]["ETH/BTC"]["quote_currency"],"BTC")
        self.assertFalse(result["quotes"]["ETH/BTC"]["paper_execution_pair"])
        self.assertTrue(result["quotes"]["BAT/USD"]["paper_execution_pair"])

    def test_paced_history_warmup_populates_native_quote_rows_idempotently(self):
        now=self.now
        class FakeData:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def bars(self,job):
                tf=job["timeframe"]
                end=ac._stamp(job["end_at"])
                unit=timedelta(hours=1) if tf=="1Hour" else timedelta(days=1)
                records=[]
                for i in range(260,0,-1):
                    stamp=end-i*unit
                    records.append((job["symbol"],tf,stamp.isoformat(),
                        2.0,2.1,1.9,2.0,150.0,
                        "alpaca_crypto_us_quote_midpoint",now.isoformat()))
                return records,None
        with patch.object(ac,"CryptoData",FakeData),patch.object(ac.time,"sleep",return_value=None):
            result=worker.run(max_pairs=1,now=now)
        self.assertEqual(result["attempted"][0]["symbol"],ac.EXPANSION50_PAIRS[0])
        self.assertEqual(result["attempted"][0]["status"],"READY_HISTORY")
        self.assertTrue(worker.ready(worker.counts(ac.EXPANSION50_PAIRS[0],now)))
        with storage.connect() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM ac_bars WHERE symbol=?",
                (ac.EXPANSION50_PAIRS[0],)).fetchone()[0],520)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ac_intents").fetchone()[0],0)
        with patch.object(ac,"CryptoData",FakeData):
            second=worker.run(max_pairs=1,now=now)
        self.assertNotEqual(second["attempted"][0]["symbol"],ac.EXPANSION50_PAIRS[0])


if __name__=="__main__":
    unittest.main(verbosity=2)
