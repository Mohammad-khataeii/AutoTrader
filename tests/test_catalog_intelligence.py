"""Deterministic, zero-network tests of catalogue price research."""
import unittest
from datetime import date, timedelta

from stockswatch.catalog_intelligence import score_daily


class CatalogIntelligenceTests(unittest.TestCase):
    def bars(self, count=220, today=date(2026, 11, 9), step=0.15):
        return [
            {"day":(today-timedelta(days=count-i-1)).isoformat(),
             "c":100+step*i,"v":5000}
            for i in range(count)
        ]

    def test_sufficient_history_explained(self):
        result=score_daily(self.bars(210),today=date(2026,11,9))
        self.assertEqual(result["state"],"RESEARCH_READY")
        self.assertGreater(result["score"],0)
        self.assertGreater(result["avg_20d_iex_dollars"],0)

    def test_insufficient_history_is_not_ready(self):
        self.assertEqual(score_daily(self.bars(200))["state"],
                         "INSUFFICIENT_HISTORY")

    def test_stale_history_rejected(self):
        history=self.bars()
        self.assertEqual(score_daily(history,today=date(2026,12,5))["state"],
                         "STALE_HISTORY")

    def test_zero_volume_is_not_liquidity_evidence(self):
        history=self.bars()
        for x in history:
            x["v"]=0
        out=score_daily(history,today=date(2026,11,9))
        self.assertEqual(out["state"],"RESEARCH_READY")
        self.assertIn("iex_activity_low",out["reason"])

    def test_invalid_price_fails_closed(self):
        history=self.bars()
        history[20]["c"]=-1
        self.assertEqual(score_daily(history,today=date(2026,11,9))["state"],"INVALID_HISTORY")


if __name__=="__main__":
    unittest.main()
