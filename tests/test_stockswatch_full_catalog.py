"""Offline coverage: full Alpaca equity catalogue is research-only and bounded."""
from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from stockswatch import asset_catalog as catalog


class FullCatalogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="sw-catalog-")
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)/"catalog.sqlite3"
        patcher = patch.object(catalog, "CATALOG_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def inventory():
        # A representative complete listing, not broker-specific identifiers.
        entries = [
            {"symbol": f"ZZ{i:04d}", "name": f"Research {i}", "exchange": "NASDAQ",
             "class":"us_equity", "status":"active", "tradable":True}
            for i in range(103)
        ]
        entries[0].update(symbol="AAPL",name="Apple")
        entries[1].update(symbol="ZZ0001",exchange="OTC")
        entries[2]["tradable"] = False
        entries.append({"symbol":"BTC/USD","class":"crypto","status":"active",
                        "exchange":"CRYPTO","tradable":True})
        return entries

    def test_sync_keeps_original_trade_universe_separate(self):
        result = catalog.save_inventory(self.inventory(),
                        datetime(2026,11,9,22,0,tzinfo=UTC))
        self.assertEqual(result["assets"],103)
        self.assertEqual(result["original"],1)
        self.assertEqual(result["tradable"],102)
        self.assertEqual(result["history_rows"],0)
        aapl = catalog.browse("AAPL")["results"][0]
        self.assertEqual(aapl["status"],"ORIGINAL")
        self.assertEqual(aapl["original"],1)
        otc = catalog.browse("ZZ0001")["results"][0]
        self.assertEqual(otc["exchange"],"OTC")
        self.assertEqual(otc["status"],"PENDING")
        self.assertEqual(len(catalog.REGISTRY),102)

    def test_sync_is_idempotent_and_fail_closed_for_truncated_inventory(self):
        data = self.inventory()
        catalog.save_inventory(data)
        catalog.save_inventory(data)
        self.assertEqual(catalog.report()["assets"],103)
        with self.assertRaisesRegex(ValueError,"suspiciously_small"):
            catalog.save_inventory(data[:2])
        self.assertEqual(catalog.report()["active"],103)

    def test_injection_is_literal_and_pagination_is_limited(self):
        catalog.save_inventory(self.inventory())
        self.assertEqual(catalog.browse("'; DROP TABLE",limit=25)["total"],0)
        with self.assertRaisesRegex(ValueError,"catalog_query_invalid"):
            catalog.browse(limit=1000)
        self.assertEqual(catalog.report()["assets"],103)

    def test_complete_paged_daily_bars_and_invalid_price(self):
        now=datetime(2026,11,9,22,0,tzinfo=UTC)
        sample={"t":"2026-11-06T05:00:00Z","o":100,"h":110,
                "l":95,"c":105,"v":1000}
        class Response:
            status_code=200
            def __init__(self,content): self.content=content
            def json(self):return self.content
            def raise_for_status(self): pass
        class Client:
            def __init__(self): self.calls=[]
            def get(self,url,**kwargs):
                self.calls.append(kwargs["params"].copy())
                if len(self.calls)==1:
                    return Response({"bars":{"ZZ0001":[sample]},"next_page_token":"second"})
                return Response({"bars":{"ZZ0002":[sample]},"next_page_token":None})
        client=Client()
        with patch.object(catalog.market,"alpaca_headers",return_value={}):
            bars=catalog.fetch_daily(client,["ZZ0001","ZZ0002"],now)
        self.assertEqual(len(client.calls),2)
        self.assertEqual(client.calls[1]["page_token"],"second")
        self.assertEqual(set(bars),{"ZZ0001","ZZ0002"})
        self.assertEqual(len(bars["ZZ0001"]),1)
        self.assertEqual(len(bars["ZZ0002"]),1)
        with self.assertRaises(ValueError):
            catalog._parse_bar({**sample,"h":99},"2026-11-06",now)

    def test_data_write_is_not_financial_or_order_state(self):
        catalog.save_inventory(self.inventory())
        now=datetime(2026,11,9,22,0,tzinfo=UTC)
        catalog._write_daily({"ZZ0001":{
            "2026-11-06":("2026-11-06",10.,11.,9.,10.,1000.)}},now)
        self.assertEqual(catalog.browse("ZZ0001")["results"][0]["status"],"PARTIAL")
        with catalog.connect(readonly=True) as db:
            tables={r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables,{
            "sw_catalog_assets","sw_catalog_daily","sw_catalog_metadata"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
