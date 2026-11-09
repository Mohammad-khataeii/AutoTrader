"""Regression contract for the read-only StocksWatch decision audit.

Run without Docker, broker credentials, network, or database.
"""
import ast
from pathlib import Path
import unittest

APP = Path(__file__).resolve().parents[1] / "stockswatch" / "app.py"
SOURCE = APP.read_text()
TREE = ast.parse(SOURCE)


def find_function(name):
    return next((n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name), None)


class DecisionAuditContract(unittest.TestCase):
    def test_audit_route_remains_authenticated(self):
        fn = find_function("decision_audit")
        self.assertIsNotNone(fn)
        routes = [d for d in fn.decorator_list if isinstance(d, ast.Call)
                  and isinstance(d.func, ast.Attribute) and d.func.attr == "get"]
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].args[0].value, "/api/stockswatch/decision-audit")
        self.assertTrue(any(k.arg == "dependencies" and "authenticated" in ast.unparse(k.value)
                            for k in routes[0].keywords))

    def test_audit_is_read_only_and_does_not_submit_broker_orders(self):
        fn = find_function("decision_audit")
        body = ast.unparse(fn)
        self.assertIn("PRAGMA query_only=ON", body)
        self.assertIn("series(c, symbol, day, now)", body)
        self.assertIn("actual_gates", body)
        self.assertIn("broker_asset_verification_missing_or_expired", body)
        for forbidden in (".submit(", "client.post(", ".execute('INSERT", ".execute('UPDATE",
                          "set_broker_paused(", "run_paper_cycle(", "service.start("):
            self.assertNotIn(forbidden, body)

    def test_all_symbols_are_audited(self):
        fn = find_function("decision_audit")
        body = ast.unparse(fn)
        self.assertIn("FROM assets ORDER BY symbol", body)
        self.assertIn("for a in assets:", body)
        self.assertIn("'tickers': output", body)
        self.assertIn("'evaluated_by_live_broker'", body)

    def test_scanner_does_not_conflate_refresh_and_evaluation(self):
        fn = find_function("scanner")
        self.assertIsNotNone(fn)
        body = ast.unparse(fn)
        self.assertIn("price_refreshes_this_cycle", body)
        self.assertIn("evaluated_tickers", body)


if __name__ == "__main__":
    unittest.main()
