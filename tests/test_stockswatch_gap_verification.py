"""Regression tests for certified stock price-gap handling; no broker calls."""
import ast
import sqlite3
import unittest
from pathlib import Path

from stockswatch.gap_audit import classify, pending, reason_for_gap


def bar(day, close, opened=None):
    return {"day": day, "o": opened if opened is not None else close,
            "c": close, "source": "alpaca_iex_daily", "adjustment": "RAW"}


def ledger():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE sw_historical_gap_proofs(
            symbol TEXT,gap_day TEXT,previous_day TEXT,raw_prev_close REAL,
            raw_next_open REAL,status TEXT,verified_at TEXT,source TEXT,
            PRIMARY KEY(symbol,gap_day));
        CREATE TABLE sw_history_actions(symbol TEXT, day TEXT, kind TEXT);
    """)
    return c


class GapAuditRegression(unittest.TestCase):
    def test_earnings_gap_requires_matching_raw_and_adjusted_reference(self):
        self.assertEqual(
            classify(100, 78, 100, 78, 100, 78),
            "VERIFIED_UNADJUSTED_MARKET_GAP",
        )
        self.assertEqual(classify(100, 78, 100.5, 78, 100, 78), "VERIFIED_UNADJUSTED_MARKET_GAP")

    def test_split_like_adjustment_must_remain_blocked(self):
        self.assertEqual(
            classify(100, 78, 100, 78, 100, 99),
            "CORPORATE_ACTION_ADJUSTMENT_DETECTED",
        )
        self.assertEqual(
            classify(100, 9.9, 100, 9.9, 10, 9.9),
            "CORPORATE_ACTION_ADJUSTMENT_DETECTED",
        )

    def test_unrelated_raw_source_cannot_approve_gap(self):
        self.assertEqual(classify(100, 78, 80, 78, 80, 78), "RAW_REFERENCE_MISMATCH")
        self.assertEqual(classify(100, 63, 100, 63, 100, 63), "EXTREME_GAP_REQUIRES_REVIEW")

    def test_no_proof_is_not_approval(self):
        with ledger() as c:
            self.assertEqual(
                reason_for_gap(c, "FDX", bar("2026-05-29", 100), bar("2026-06-01", 78, 78), 110),
                "historical_gap_verification_pending",
            )

    def test_completed_matching_proof_allows_only_that_history(self):
        prev, curr = bar("2026-05-29", 100), bar("2026-06-01", 78, 78)
        with ledger() as c:
            c.execute(
                "INSERT INTO sw_historical_gap_proofs VALUES(?,?,?,?,?,?,?,?)",
                ("FDX", curr["day"], prev["day"], 100, 78,
                 "VERIFIED_UNADJUSTED_MARKET_GAP", "2026-11-09T00:00:00Z",
                 "alpaca_iex_raw_vs_all_adjusted"),
            )
            self.assertIsNone(reason_for_gap(c, "FDX", prev, curr, 110))
            self.assertEqual(
                reason_for_gap(c, "FDX", prev, bar(curr["day"], 77, 76), 110),
                "historical_gap_verification_pending",
            )

    def test_recent_large_gap_and_known_action_stay_blocked(self):
        prev, curr = bar("2026-05-29", 100), bar("2026-06-01", 78, 78)
        with ledger() as c:
            self.assertEqual(
                reason_for_gap(c, "FDX", prev, curr, 2),
                "historical_recent_large_gap_cooling_period",
            )
            c.execute("INSERT INTO sw_history_actions VALUES('FDX','2026-06-01','forward_splits')")
            self.assertEqual(
                reason_for_gap(c, "FDX", prev, curr, 110),
                "historical_corporate_action_requires_adjustment",
            )

    def test_unmatched_proofs_are_pending_collection(self):
        prev, curr = bar("2026-05-29", 100), bar("2026-06-01", 78, 78)
        with ledger() as c:
            self.assertEqual(pending(c, "FDX", [prev, curr] + [bar("2026-06-02", 78)] * 6)[0], "FDX")
            c.execute(
                "INSERT INTO sw_historical_gap_proofs VALUES(?,?,?,?,?,?,?,?)",
                ("FDX", curr["day"], prev["day"], 100, 78, "CORPORATE_ACTION_ADJUSTMENT_DETECTED",
                 "2026-11-09T00:00:00Z", "alpaca_iex_raw_vs_all_adjusted"),
            )
            self.assertIsNone(pending(c, "FDX", [prev, curr] + [bar("2026-06-02", 78)] * 6))

    def test_source_wiring_keeps_stocks_paper_only(self):
        root = Path(__file__).resolve().parents[1]
        app = (root / "stockswatch" / "app.py").read_text()
        service = (root / "stockswatch" / "service.py").read_text()
        ledger_source = (root / "stockswatch" / "ledger.py").read_text()
        broker = (root / "stockswatch" / "alpaca_paper.py").read_text()
        for source in (app, service, ledger_source, broker):
            ast.parse(source)
        self.assertIn("await refresh_proofs(client, now, limit=6)", service)
        self.assertIn("reason_for_gap(c, symbol, previous, current", ledger_source)
        self.assertIn("entry_window_closed_remaining_broker_gates_not_evaluated", broker)
        self.assertIn("historical_gap_proofs", app)
        self.assertIn("paper_only': True", app)


if __name__ == "__main__":
    unittest.main()
