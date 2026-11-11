"""Authenticated read-only, date-filtered StocksWatch broker-decision audit.

Only evidence recorded by the local paper broker is returned; the response
does not pretend that account P&L is realized stock P&L, or that IEX is SIP.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json
import re

from .storage import connect

NY = ZoneInfo("America/New_York")


def session_bounds(day):
    if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("audit_invalid_market_day")
    parsed = date.fromisoformat(day)
    if parsed > datetime.now(NY).date() or parsed < date(2020, 1, 1):
        raise ValueError("audit_market_day_out_of_range")
    a = datetime.combine(parsed, datetime.min.time(), NY).astimezone(timezone.utc)
    b = datetime.combine(parsed + timedelta(days=1), datetime.min.time(), NY).astimezone(timezone.utc)
    return a.isoformat(), b.isoformat()


def snapshot(day, *, offset=0, limit=100):
    a, b = session_bounds(day)
    if not (0 <= offset <= 100000 and 1 <= limit <= 250):
        raise ValueError("audit_invalid_page")
    with connect() as db:
        db.execute("PRAGMA query_only=ON")
        db.row_factory = __import__("sqlite3").Row
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        def query(sql, args=()):
            return [dict(x) for x in db.execute(sql, args).fetchall()]
        if "sw_broker_decision_cycles" in tables:
            n = db.execute("""SELECT COUNT(*) FROM sw_broker_decision_cycles
              WHERE session_day=?""", (day,)).fetchone()[0]
            cycles = query("""SELECT at,status,reason,result_json FROM sw_broker_decision_cycles
              WHERE session_day=? ORDER BY at LIMIT ? OFFSET ?""",(day,limit,offset))
            for cycle in cycles:
                report = json.loads(cycle.pop("result_json"))
                cycle["why_no_trade"] = report.get("why_no_trade", [])
                cycle["broker_orders_submitted"] = report.get("broker_orders_submitted", 0)
                cycle["signals"] = report.get("signals", [])
        else:
            n, cycles = 0, []
        intents = query("""SELECT symbol,side,qty,signal_day,reason,state,broker_status,
          created_at,updated_at FROM sw_alpaca_intents
          WHERE created_at>=? AND created_at<? ORDER BY created_at""", (a,b)) if "sw_alpaca_intents" in tables else []
        intraday_count = db.execute("""SELECT COUNT(*) FROM sw_intraday_cycles
          WHERE at>=? AND at<?""", (a,b)).fetchone()[0] if "sw_intraday_cycles" in tables else 0
        intraday_cycles = query("""SELECT id,at,report_json FROM sw_intraday_cycles
          WHERE at>=? AND at<? ORDER BY at LIMIT ? OFFSET ?""", (a,b,limit,offset)) if "sw_intraday_cycles" in tables else []
        for row in intraday_cycles:
            report = json.loads(row.pop("report_json"))
            observations = query("""SELECT symbol,action,evidence_json
              FROM sw_intraday_observations WHERE cycle_id=?
              ORDER BY symbol LIMIT 200""", (row.pop("id"),)) if "sw_intraday_observations" in tables else []
            per_symbol = []
            for observation in observations:
                detail = json.loads(observation.pop("evidence_json"))
                per_symbol.append({
                    "symbol": observation["symbol"], "action": observation["action"],
                    "reason": detail.get("reason"), "score": detail.get("score"),
                    "candidate": detail.get("candidate"), "valid": detail.get("valid"),
                    "feed": detail.get("feed"), "quote_at": detail.get("quote_at"),
                })
            row.update(status=report.get("status"), execution=report.get("execution"),
                       order_gate=report.get("order_gate"), phase=report.get("phase"),
                       market_risk=report.get("market_risk"), rows=per_symbol,
                       observations_exported=len(per_symbol))
        if "sw_intraday_observations" in tables:
            observed = query("""SELECT action,COUNT(*) AS count
              FROM sw_intraday_observations WHERE at>=? AND at<?
              GROUP BY action ORDER BY count DESC""", (a,b))
        else:
            observed=[]
        protection = query("""SELECT symbol,qty,state,broker_stop,updated_at,last_error
          FROM sw_protection ORDER BY symbol""") if "sw_protection" in tables else []
    return {
        "market_day":day,"timezone":"America/New_York","read_only":True,
        "broker_decision_cycle_count":n,"broker_cycles":cycles,
        "intraday_cycle_count":intraday_count,"intraday_cycles":intraday_cycles,
        "intraday_actions":observed,"entry_intents":intents,
        "protection_current_not_historical":protection,
        "offset":offset,"limit":limit,
        "has_more_broker_cycles":offset+len(cycles)<n,
        "has_more_intraday_cycles":offset+len(intraday_cycles)<intraday_count,
        "financial_scope":"No account-level realized P&L attributed to stock strategy",
        "market_price_scope":"IEX-only local evidence; independent SIP needed for execution benchmark",
    }
