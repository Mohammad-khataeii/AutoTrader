"""Offline regression: session audit must include separate per-symbol observations."""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from stockswatch import session_audit


def test_nov10_session_audit_joins_per_symbol_and_filters_before_pagination(tmp_path, monkeypatch):
    db_path = tmp_path / "audit.sqlite3"
    with sqlite3.connect(db_path) as c:
        c.executescript("""
        CREATE TABLE sw_broker_decision_cycles
          (at TEXT PRIMARY KEY,session_day TEXT,status TEXT,reason TEXT,result_json TEXT);
        CREATE TABLE sw_intraday_cycles (id TEXT PRIMARY KEY,at TEXT,report_json TEXT);
        CREATE TABLE sw_intraday_observations
          (cycle_id TEXT,symbol TEXT,at TEXT,session TEXT,valid INT,action TEXT,
           evidence_json TEXT,PRIMARY KEY(cycle_id,symbol));
        CREATE TABLE sw_alpaca_intents
          (symbol TEXT,side TEXT,qty TEXT,signal_day TEXT,reason TEXT,state TEXT,
           broker_status TEXT,created_at TEXT,updated_at TEXT);
        CREATE TABLE sw_protection
          (symbol TEXT,qty TEXT,state TEXT,broker_stop TEXT,updated_at TEXT,last_error TEXT);
        """)
        for day, symbol, code in (
            ("2026-11-09", "AAPL", "prior_session"),
            ("2026-11-10", "ABBV", "intraday_entry_candidate"),
            ("2026-11-11", "ACN", "later_session"),
        ):
            at=f"{day}T15:00:00+00:00"
            c.execute("INSERT INTO sw_intraday_cycles VALUES(?,?,?)",
                (at,at,json.dumps({"status":"OBSERVING","execution":"WAIT","order_gate":None})))
            c.execute("INSERT INTO sw_intraday_observations VALUES(?,?,?,?,?,?,?)",
                (at,symbol,at,"CORE",1,"WATCH",json.dumps({
                    "symbol":symbol,"reason":code,"score":"3.0",
                    "candidate":True,"valid":True,"feed":"sip"})))
        at="2026-11-10T15:02:00+00:00"
        c.execute("INSERT INTO sw_broker_decision_cycles VALUES(?,?,?,?,?)",
            (at,"2026-11-10","NO_APPROVED_BROKER_SIGNAL",None,
             json.dumps({"why_no_trade":[{"symbol":"ABBV","reason":"adaptive_stock_still_declining"}]})))
    def isolated():
        return sqlite3.connect(db_path)
    monkeypatch.setattr(session_audit,"connect",isolated)
    result=session_audit.snapshot("2026-11-10",limit=1)
    assert result["broker_decision_cycle_count"]==1
    assert result["broker_cycles"][0]["why_no_trade"][0]["reason"]=="adaptive_stock_still_declining"
    assert result["intraday_cycle_count"]==1
    assert result["intraday_cycles"][0]["rows"][0]["symbol"]=="ABBV"
    assert result["intraday_cycles"][0]["rows"][0]["reason"]=="intraday_entry_candidate"
    assert result["intraday_cycles"][0]["observations_exported"]==1
    assert not result["has_more_intraday_cycles"]
    assert session_audit.snapshot("2026-11-10",offset=1,limit=1)["intraday_cycles"]==[]


def test_bad_dates_and_pages_are_rejected():
    import pytest
    with pytest.raises(ValueError):
        session_audit.snapshot("2026-13-44")
    with pytest.raises(ValueError):
        session_audit.snapshot("2035-01-01")
    with pytest.raises(ValueError):
        session_audit.snapshot("2026-11-10",limit=9999)
