"""Alpaca Paper bridge tests: offline-only, no real HTTP or broker orders."""
import os
import unittest
from unittest.mock import patch

import httpx

from stockswatch.alpaca_paper import (
    PAPER_ORIGIN, PREFIX, PaperClient, account_ui, cid_for, safe_number,
)


class AlpacaPaperBridgeTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "STOCKSWATCH_ALPACA_PAPER_KEY": "TEST_KEY",
            "STOCKSWATCH_ALPACA_PAPER_SECRET": "TEST_SECRET",
            "STOCKSWATCH_ALPACA_PAPER_ACCOUNT_ID": "expected-paper-account",
            "STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS": "0",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_paper_hostname_and_account_identity(self):
        requests = []
        def handle(request):
            requests.append(request)
            self.assertEqual(request.url.scheme, "https")
            self.assertEqual(request.url.host, "paper-api.alpaca.markets")
            self.assertEqual(request.headers.get("APCA-API-KEY-ID"), "TEST_KEY")
            return httpx.Response(200, json={
                "id": "expected-paper-account", "currency": "USD", "status": "ACTIVE",
                "cash": "100000.00", "equity": "100000.00", "trading_blocked": False,
            })
        with PaperClient(transport=httpx.MockTransport(handle)) as c:
            self.assertEqual(c.account()["cash"], "100000.00")
            self.assertEqual(c._client.base_url.host, "paper-api.alpaca.markets")
        self.assertEqual(len(requests), 1)

    def test_account_mismatch_fails_closed(self):
        def handle(req):
            return httpx.Response(200, json={
                "id": "SOME-OTHER-ACCOUNT", "currency": "USD", "status": "ACTIVE",
                "cash": "250000.00", "equity": "250000.00"})
        with PaperClient(transport=httpx.MockTransport(handle)) as c:
            with self.assertRaisesRegex(RuntimeError, "account_mismatch"):
                c.account()

    def test_paper_orders_default_disabled_even_with_paper_credentials(self):
        called = []
        def handle(req):
            called.append(req)
            return httpx.Response(200, json={"id": "1"})
        cid = cid_for("expected-paper-account", "AAPL", "2026-11-06", "BUY")
        with PaperClient(transport=httpx.MockTransport(handle)) as c:
            with self.assertRaisesRegex(RuntimeError, "orders_disabled"):
                c.submit({"client_order_id": cid, "side": "buy", "time_in_force": "day"})
        self.assertEqual(called, [])

    def test_client_id_stable_and_scoped(self):
        a = cid_for("one", "MSFT", "2026-11-06", "BUY")
        self.assertEqual(a, cid_for("one", "MSFT", "2026-11-06", "BUY"))
        self.assertNotEqual(a, cid_for("one", "MSFT", "2026-11-06", "SELL"))
        self.assertNotEqual(a, cid_for("other", "MSFT", "2026-11-06", "BUY"))
        self.assertTrue(a.startswith(PREFIX))
        self.assertEqual(len(a), 45)

    def test_snapshot_broker_equity_and_no_margin_as_cash(self):
        snapshot = {
            "account": {
                "account_number": "PA3BGBBEBYTY", "equity": "100000.00",
                "last_equity": "100000.00", "cash": "100000.00", "buying_power": "400000.00"},
            "positions": [], "orders": [], "fills": [],
            "history": {"timestamp": [1793900000], "equity": [100000.0], "base_value": 100000},
        }
        with patch("stockswatch.alpaca_paper.one", return_value={"paused": 1}):
            view = account_ui(snapshot)
        self.assertEqual(view["account"]["equity"], 100000)
        self.assertEqual(view["account"]["cash"], 100000)
        self.assertEqual(view["account"]["buying_power"], 400000)
        self.assertTrue(view["account"]["paused"])
        self.assertEqual(view["broker_account"]["source"], "Alpaca Paper Trading API")
        self.assertEqual(view["account"]["account_masked"], "…BYTY")

    def test_paper_order_lookup_404_is_safe_and_not_sent_to_live_host(self):
        called = []
        def handle(req):
            called.append(str(req.url))
            return httpx.Response(404, json={"message": "order not found"})
        cid = cid_for("test", "AAPL", "2026-11-06", "BUY")
        with PaperClient(transport=httpx.MockTransport(handle)) as c:
            self.assertIsNone(c.by_client_id(cid))
        self.assertEqual(len(called), 1)
        self.assertTrue(called[0].startswith(PAPER_ORIGIN + "/v2/orders:by_client_order_id"))

    def test_nan_cash_not_accepted(self):
        self.assertEqual(safe_number("nan"), 0)
        self.assertEqual(safe_number("inf"), 0)


if __name__ == "__main__":
    unittest.main()
