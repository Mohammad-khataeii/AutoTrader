"""Fail-closed crypto paper regression tests, without account access."""
import ast
import sqlite3
import unittest
from decimal import Decimal
from pathlib import Path

from stockswatch.crypto_trade_safety import (
    depth_limited_notional,
    untraded_quote_outlier,
)

ROOT = Path(__file__).resolve().parents[1]
CRYPTO = ROOT / "stockswatch" / "alpaca_crypto.py"
BROKER = ROOT / "stockswatch" / "alpaca_crypto_paper.py"


class CryptoSafetyTests(unittest.TestCase):
    def test_zero_trade_31_percent_quote_wick_is_blocked(self):
        bars = [
            {"ts": "2026-11-10T03:00:00+00:00",
             "o": 1.112, "h": 1.128, "l": 1.11, "c": 1.121, "v": 0},
            {"ts": "2026-11-10T04:00:00+00:00",
             "o": 1.116, "h": 1.468084399, "l": 1.11205,
             "c": 1.468084399, "v": 0},
        ]
        result = untraded_quote_outlier(bars)
        self.assertEqual(result["reason"], "untraded_quote_outlier")
        self.assertEqual(result["bar_at"], "2026-11-10T04:00:00+00:00")

    def test_normal_quote_only_candle_is_not_rejected(self):
        bars = [{"ts": str(i), "o": 100, "h": 101, "l": 99,
                 "c": 100.1, "v": 0} for i in range(25)]
        self.assertIsNone(untraded_quote_outlier(bars))

    def test_positive_volume_market_jump_not_blindly_quarantined(self):
        bars = [{"ts": "02", "o": 100, "h": 135, "l": 100,
                 "c": 130, "v": 200}]
        self.assertIsNone(untraded_quote_outlier(bars))

    def test_invalid_candle_is_blocked(self):
        self.assertEqual(untraded_quote_outlier([
            {"ts": "04", "o": 100, "h": 98, "l": 95, "c": 100, "v": 0}
        ])["reason"], "invalid_candle")

    def test_pepe_depth_limits_to_small_bid_and_ask(self):
        value, why = depth_limited_notional(
            "4000", "0.00000516", "0.00000514", "109124096", "215956551")
        self.assertEqual(value, Decimal("112.61"))
        self.assertEqual(why, "crypto_entry_depth_capped")

    def test_thin_depth_blocks_minimum_order(self):
        value, why = depth_limited_notional(
            4000, 1.12, 1.11, 20, 20)
        self.assertIsNone(value)
        self.assertEqual(why, "crypto_entry_depth_below_minimum")

    def test_nonfinite_or_missing_depth_blocks_entry(self):
        for asksize in (0, -1, float("nan"), None, "inf", "garbage"):
            self.assertIsNone(depth_limited_notional(
                100, 1.02, 1.0, asksize, 200)[0])

    def test_never_raise_size_above_existing_risk_budget(self):
        capped, _ = depth_limited_notional(
            30, 10.1, 10, 200, 200)
        self.assertEqual(capped, Decimal("30.00"))

    def test_schema_audit_is_additive_and_immutable(self):
        source=CRYPTO.read_text()
        tree=ast.parse(source)
        schema=next(n.value.value for n in tree.body
                    if isinstance(n,ast.Assign)
                    and any(getattr(t,"id",None)=="SCHEMA" for t in n.targets))
        db=sqlite3.connect(":memory:")
        db.executescript(schema)
        for _ in range(2):
            db.execute("""INSERT OR IGNORE INTO ac_signal_audit
                (symbol,bar_at,first_evaluated_at,action,reason,score,price,stop,target,gates_json)
                VALUES('PEPE/USD','2026-11-10T03:00:00Z','2026-11-10T04:01:00Z',
                'BUY','continuation',0.75,0.00000515,0.00000491,0.00000559,'{}')""")
        self.assertEqual(db.execute("SELECT count(*) FROM ac_signal_audit").fetchone()[0],1)
        self.assertIn("ac_admission_audit",
                      {row[0] for row in db.execute("SELECT name FROM sqlite_master")})
        db.close()

    def test_broker_original_protection_untouched(self):
        a=CRYPTO.read_text()
        b=BROKER.read_text()
        ast.parse(a);ast.parse(b)
        self.assertIn("untraded_quote_outlier(hourly)", a)
        self.assertIn("latest_entry_quote", a)
        self.assertIn("s[\"bar_at\"],last_blocked", b)
        self.assertIn("depth_limited_notional(", b)
        self.assertIn('bid,ask,stamp=data.latest_bid(symbol)', b)
        self.assertIn("ac_managed", b)
        self.assertNotIn("paper-api.alpaca.markets/v2/orders", a)


if __name__=="__main__":
    unittest.main()
