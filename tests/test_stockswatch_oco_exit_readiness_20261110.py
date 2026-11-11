"""StocksWatch regression tests for OCO coordination and shared broker account.

No network, broker credentials, API server, or order submission is needed.
"""
from __future__ import annotations

import ast
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from stockswatch.broker_shared_state import shared_state_matches


ROOT=Path(__file__).resolve().parents[1]
PAPER=(ROOT/"stockswatch/alpaca_paper.py").read_text()
OCO=(ROOT/"stockswatch/profit_oco.py").read_text()
READY=(ROOT/"stockswatch/readiness.py").read_text()
API=(ROOT/"stockswatch/app.py").read_text()


def _function(source,name,extra=None):
    """Compile one reviewed pure helper without importing broker dependencies."""
    parsed=ast.parse(source)
    nodes=[x for x in parsed.body if isinstance(x,ast.FunctionDef) and x.name==name]
    if len(nodes)!=1:raise AssertionError("function_not_unique: "+name)
    module=ast.Module(body=[nodes[0]],type_ignores=[])
    ast.fix_missing_locations(module)
    env=dict(extra or {})
    exec(compile(module,"<reviewed-source>","exec"),env)
    return env[name]


def _base():
    stock={"symbol":"AAPL","asset_id":"s1","qty":"4","qty_available":"4",
           "side":"long","avg_entry_price":"200","asset_class":"us_equity"}
    crypto={"symbol":"BTCUSD","asset_id":"c1","qty":"0.02","qty_available":"0.02",
            "side":"long","avg_entry_price":"73000","asset_class":"crypto"}
    order={"id":"oid1","client_order_id":"cryptoid","symbol":"BTCUSD",
           "side":"buy","status":"new","qty":"0.01","filled_qty":"0",
           "type":"market","limit_price":None,"stop_price":None}
    return {"positions":[stock],"other_positions":[crypto],
            "open_orders":[],"other_open_orders":[order]}


class SharedBrokerRegressions(unittest.TestCase):
    def test_crypto_holdings_and_orders_do_not_falsely_block_stock_exit(self):
        s=_base()
        self.assertTrue(shared_state_matches(
            s,s["positions"]+s["other_positions"],
            s["other_open_orders"]+s["open_orders"]))

    def test_changed_crypto_order_fails_closed(self):
        s=_base()
        changed=[{**s["other_open_orders"][0],"status":"filled"}]
        self.assertFalse(shared_state_matches(
            s,s["positions"]+s["other_positions"],changed))

    def test_changed_crypto_position_fails_closed(self):
        s=_base()
        changed=[*s["positions"],{**s["other_positions"][0],"qty":"0.03"}]
        self.assertFalse(shared_state_matches(s,changed,s["other_open_orders"]))

    def test_unknown_extra_order_and_duplicate_position_fail(self):
        s=_base()
        self.assertFalse(shared_state_matches(
            s,s["positions"]+s["other_positions"],
            s["other_open_orders"]+[{"id":"unexpected"}]))
        self.assertFalse(shared_state_matches(
            s,s["positions"]*2+s["other_positions"],s["other_open_orders"]))

    def test_missing_broker_evidence_fails(self):
        s=_base()
        self.assertFalse(shared_state_matches(s,None,[]))
        self.assertFalse(shared_state_matches(s,[],None))


class OCOExitRegressions(unittest.TestCase):
    def _verify(self):
        class Lock:
            @staticmethod
            def decimal(x):
                d=Decimal(str(x))
                if d<=0 or not d.is_finite():raise ValueError("invalid")
                return d
        return _function(OCO,"_verify_strategy_exit",{
            "profit_lock":Lock,"connect":lambda:None,"utc":lambda:"now",
            "_STATES":{"new","accepted","pending_new","partially_filled"},
        })

    def _data(self):
        record={"account_id":"paper","symbol":"AAPL","client_id":"swg1-client",
                "entry_client_id":"swp2-abc","stop_leg_id":"leg1",
                "current_stop":"190","target":"225","qty":"4"}
        request={"root_order_id":"root1","requested_limit":"202.50",
                 "state":"VERIFIED_ACTIVE"}
        root={"id":"root1","client_order_id":"swg1-client","symbol":"AAPL",
              "side":"sell","order_class":"oco","type":"limit",
              "time_in_force":"gtc","status":"new","limit_price":"202.50",
              "qty":"4","legs":[{"id":"leg1","side":"sell","type":"stop",
                                  "status":"new","stop_price":"190",
                                  "symbol":"AAPL","qty":"4"}]}
        return record,request,root

    def test_verified_same_oco_lower_target_preserves_stop(self):
        record,req,root=self._data()
        self.assertEqual(self._verify()([root],record,req),"oco_exit_limit_verified")

    def test_held_contingent_stop_is_verified_during_exit_handoff(self):
        record,req,root=self._data()
        root["legs"][0]["status"]="held"
        self.assertEqual(self._verify()([root],record,req),"oco_exit_limit_verified")

    def test_missing_parent_never_authorizes_another_sell(self):
        record,req,root=self._data()
        self.assertIn("unverified",self._verify()([],record,req))

    def test_modified_stop_leg_fails_closed(self):
        record,req,root=self._data()
        root["legs"][0]["id"]="other"
        self.assertEqual(self._verify()([root],record,req),"oco_exit_stop_leg_changed")

    def test_stop_lowered_fails_closed(self):
        record,req,root=self._data()
        root["legs"][0]["stop_price"]="189"
        self.assertEqual(self._verify()([root],record,req),
                         "oco_exit_stop_target_or_quantity_invalid")

    def test_exit_limit_above_requested_or_below_stop_fails(self):
        record,req,root=self._data()
        root["limit_price"]="205"
        self.assertEqual(self._verify()([root],record,req),
                         "oco_exit_stop_target_or_quantity_invalid")
        root["limit_price"]="180"
        self.assertEqual(self._verify()([root],record,req),
                         "oco_exit_stop_target_or_quantity_invalid")

    def test_uncertain_network_order_is_never_retried_or_cancelled(self):
        body=OCO.split("def request_strategy_exit(",1)[1].split(
            "\ndef _snapshot_position(",1)[0]
        self.assertIn("INSERT OR IGNORE INTO sw_oco_exit_requests",body)
        self.assertIn("patch_outcome_uncertain_no_retry",body)
        self.assertLess(body.index("INSERT OR IGNORE INTO sw_oco_exit_requests"),
                        body.index('client._request("PATCH"'))
        self.assertNotIn('client._request("DELETE"',body)
        self.assertNotIn('client._request("POST"',body)

    def test_off_hours_verification_is_deferred_not_protection_failure(self):
        self.assertIn("oco_broker_verification_deferred_off_session",OCO)
        self.assertLess(OCO.index("if saved and nested is None:"),
                        OCO.index("if saved and nested is not None:"))


class ReadinessRiskRegressions(unittest.TestCase):
    def test_readiness_endpoint_requires_authentication(self):
        self.assertIn("@app.get('/api/stockswatch/trading-readiness', dependencies=[Depends(authenticated)])",API)
        self.assertIn("return snapshot(service)",API)

    def test_readiness_does_not_import_missing_live_broker_window_constant(self):
        # The deployed custom Alpaca broker can omit OPEN_WINDOW entirely.
        # Importing it in the read-only UI module caused Docker smoke failure.
        module=ast.parse(READY)
        broker_imports=[n for n in module.body if isinstance(n,ast.ImportFrom)
                        and n.module=="alpaca_paper"]
        self.assertEqual(len(broker_imports),1)
        self.assertNotIn("OPEN_WINDOW",
                         [n.name for n in broker_imports[0].names])
        self.assertIn("eod_window=timedelta(hours=1)",READY)
        self.assertIn("alpaca_paper._open_window",READY)

    def test_process_health_not_used_as_trading_authorization(self):
        self.assertIn("health_semantics",READY)
        self.assertIn("broker_cycle_not_recent",READY)
        self.assertIn("unresolved_broker_order_intents",READY)
        self.assertIn("independent_intraday_order_gate",READY)
        self.assertIn("FIRST_60_MINUTES_CORE_ONLY",READY)

    def test_schema_additions_are_idempotent_on_existing_sqlite(self):
        import sqlite3
        def schema(source):
            module=ast.parse(source)
            for n in module.body:
                if isinstance(n,ast.Assign) and any(
                        isinstance(t,ast.Name) and t.id=="SCHEMA" for t in n.targets):
                    return n.value.value
            raise AssertionError("schema_missing")
        db=sqlite3.connect(":memory:")
        for _ in range(2):
            db.executescript(schema(PAPER))
            db.executescript(schema(OCO))
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master")}
        self.assertIn("sw_paper_risk_peaks",tables)
        self.assertIn("sw_oco_exit_requests",tables)
        db.close()

    def test_missing_broker_history_requires_verified_recent_highwater(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS sw_paper_risk_peaks",PAPER)
        self.assertIn("def _record_verified_account_peak(snapshot):",PAPER)
        self.assertIn("_record_verified_account_peak(snapshot)",PAPER)
        self.assertIn("timedelta(days=3)",PAPER)
        self.assertIn("alpaca_paper_risk_history_never_verified",PAPER)
        self.assertIn("alpaca_paper_risk_history_missing_or_stale",PAPER)
        self.assertIn("alpaca_paper_drawdown_or_daily_loss_pause",PAPER)

    def test_stock_buy_still_blocks_on_crypto_orders_but_exit_does_not(self):
        self.assertIn('if symbol not in known and snapshot.get("other_open_orders"):',PAPER)
        self.assertIn("request_strategy_exit(client,snapshot,signal,account_id,now)",PAPER)
        self.assertNotIn('if snapshot.get("other_open_orders"):\n        return',PAPER)

    def test_pausing_new_stock_entries_does_not_disable_verified_exits(self):
        self.assertIn("new_stock_entry_paused_exit_protection_continues",PAPER)
        self.assertIn('if action == "BUY" and (one("SELECT paused',PAPER)
        self.assertNotIn('return {**result, **preview, "status": "BROKER_PAUSED"}',PAPER)

    def test_late_eod_entry_policy_remains_separate_from_sip_intraday(self):
        self.assertIn('"late_session_eod_entries":False',READY)
        self.assertIn('"independent_intraday_order_gate":order_gate()',READY)
        self.assertIn("OPEN_WINDOW = timedelta(hours=1)",PAPER)

    def test_pure_time_freshness(self):
        fn=_function(READY,"_fresh",{"datetime":datetime,"timedelta":timedelta,"UTC":UTC})
        now=datetime(2026,11,10,6,30,tzinfo=UTC)
        self.assertTrue(fn((now-timedelta(seconds=80)).isoformat(),now,150))
        self.assertFalse(fn((now-timedelta(seconds=151)).isoformat(),now,150))
        self.assertFalse(fn((now+timedelta(seconds=1)).isoformat(),now,150))


if __name__=="__main__":
    unittest.main()
