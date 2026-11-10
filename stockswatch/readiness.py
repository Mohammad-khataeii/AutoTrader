"""Authenticated, read-only operational readiness. Never calls the broker.

Basic /healthz proves only process liveness. This separately reports if
existing workers, paper reconciliation and source data are ready to evaluate.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .alpaca_paper import OPEN_WINDOW, broker_mode, orders_enabled
from .intraday_policy import order_gate, phase_at
from .sessions import completed_day, next_day, session
from .storage import connect


def _fresh(value,now,seconds):
    if not isinstance(value,str):
        return False
    try:
        ts=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        return False
    return ts.tzinfo is not None and timedelta(0)<=now-ts.astimezone(UTC)<=timedelta(seconds=seconds)


def snapshot(service,now=None):
    now=now or datetime.now(UTC)
    day=completed_day(now)
    opened,_=session(next_day(day))
    eod_open=opened<=now<opened+OPEN_WINDOW
    phase=phase_at(now)
    # Read-only means not even refreshing the account through Alpaca here.
    with connect() as c:
        c.execute("PRAGMA query_only=ON")
        checks=c.execute("""SELECT COUNT(*) FROM assets a JOIN sw_price_checks q
           ON a.symbol=q.symbol WHERE a.enabled=1 AND q.day=?
           AND q.status='OK'""",(day,)).fetchone()[0]
        enabled=c.execute("SELECT COUNT(*) FROM assets WHERE enabled=1").fetchone()[0]
        uncertain=c.execute("""SELECT COUNT(*) FROM sw_alpaca_intents
           WHERE state IN ('PREPARED','UNKNOWN')""").fetchone()[0]
        oco=c.execute("""SELECT state,COUNT(*) FROM sw_protection
           GROUP BY state""").fetchall()
        handoff=c.execute("""SELECT state,COUNT(*) FROM sw_oco_exit_requests
           GROUP BY state""").fetchall()
        risk=c.execute("SELECT MAX(verified_at) FROM sw_paper_risk_peaks").fetchone()[0]
        historical=c.execute("""SELECT state,COUNT(*) FROM sw_history_jobs
           GROUP BY state""").fetchall()
    broker=service.broker_result
    status=broker.get("status","UNKNOWN")
    healthy_broker=service.broker_task is not None and not service.broker_task.done()
    recent_broker=_fresh(broker.get("at"),now,150)
    bad_statuses={"BROKER_CYCLE_ERROR","BROKER_CHECK_FAILED",
       "UNCERTAIN_BROKER_INTENT","BROKER_ORDER_UNCERTAIN",
       "BROKER_ORDER_WITHOUT_LOCAL_INTENT","BROKER_STATE_CHANGED_RECHECK_NEXT_CYCLE",
       "PROTECTION_MONITOR_UNAVAILABLE"}
    problems=[]
    if not healthy_broker:problems.append("broker_worker_not_running")
    if not recent_broker:problems.append("broker_cycle_not_recent")
    if status in bad_statuses:problems.append("broker_cycle_"+status.lower())
    if uncertain:problems.append("unresolved_broker_order_intents")
    if any(row[0] in ("UNKNOWN","REPLACE_UNCERTAIN","UNVERIFIED") for row in oco):
        problems.append("protection_reconciliation_required")
    if any(row[0] in ("PREPARED","UNCERTAIN") for row in handoff):
        problems.append("oco_exit_replacement_requires_broker_proof")
    if checks<enabled:problems.append("daily_price_evidence_incomplete")
    paper=broker_mode()
    return {
        "as_of":now.isoformat(),"read_only":True,"broker_mode":"alpaca_paper" if paper else "local",
        "paper_orders_enabled":orders_enabled() if paper else False,
        "status":("NOT_READY" if problems else
                  "EOD_ENTRY_WINDOW_OPEN" if eod_open else "WAITING_FOR_EOD_ENTRY_WINDOW"),
        "problems":problems,
        "broker":{"worker_alive":healthy_broker,"last_status":status,
                  "last_cycle_at":broker.get("at"),"fresh":recent_broker,
                  "unresolved_intents":uncertain},
        "daily_data":{"completed_session":day,"certified_assets":checks,
                      "enabled_assets":enabled},
        "protection":{"states":{k:n for k,n in oco},
                      "exit_handoffs":{k:n for k,n in handoff}},
        "portfolio_risk":{"last_verified_broker_peak_at":risk,
                          "peak_recent":_fresh(risk,now,3*86400)},
        "historical_download":{"jobs_by_state":{k:n for k,n in historical},
                              "worker_alive":service.history_task is not None
                              and not service.history_task.done()},
        "session_routes":{
            "eod_admission":"FIRST_60_MINUTES_CORE_ONLY",
            "eod_window_open":eod_open,
            "next_eod_window":opened.isoformat(),
            "intraday_phase":phase.name,
            "independent_intraday_order_gate":order_gate(),
            "late_session_eod_entries":False,
            "note":"Later-session trades require the existing independent SIP intraday engine and its pinned preflight; never reuse a stale EOD signal."
        },
        "health_semantics":"Not an order authorization; individual orders still require fresh broker and ownership checks",
    }
