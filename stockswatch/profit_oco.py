"""Alpaca Paper equity OCO TP + monotone stop manager.

Separate from entry ranking. Safety invariants:
- paper URL only, single verified EOD-owned long position, no overlapping orders;
- durable CREATE/PATCH intent before the network write; no blind retry;
- only read broker-verified stop levels as effective protection;
- never lower a stop; no automatic OCO cancellation or second sell;
- disabled unless a second explicit server opt-in accompanies normal paper orders.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from . import profit_lock
from .sessions import NY, completed_day, instant, session
from .storage import connect, one, rows, utc

log = logging.getLogger(__name__)
PREFIX = "swg1-"
_STATES = {"new","accepted","pending_new","partially_filled"}
_END = {"filled","canceled","expired","rejected","replaced"}
_lock = threading.Lock()
_last = {"status":"STARTING","positions":[],"paper_orders_enabled":False}
SCHEMA = """
CREATE TABLE IF NOT EXISTS sw_protection (
 account_id TEXT NOT NULL, symbol TEXT NOT NULL,
 entry_client_id TEXT NOT NULL, qty TEXT NOT NULL,
 entry TEXT NOT NULL, atr TEXT NOT NULL,
 initial_stop TEXT NOT NULL, current_stop TEXT NOT NULL,
 target TEXT NOT NULL, highwater TEXT NOT NULL,
 client_id TEXT NOT NULL UNIQUE, root_order_id TEXT, stop_leg_id TEXT,
 state TEXT NOT NULL, requested_stop TEXT, broker_stop TEXT,
 last_quote_at TEXT, updated_at TEXT NOT NULL, last_error TEXT,
 PRIMARY KEY(account_id,symbol));
CREATE INDEX IF NOT EXISTS sw_protection_state ON sw_protection(state);
"""


class ProtectionError(RuntimeError):
    pass


def initialize():
    with connect() as c:
        c.executescript(SCHEMA)


def armed():
    from .alpaca_paper import orders_enabled, broker_mode
    return (broker_mode() and orders_enabled()
        and os.getenv("STOCKSWATCH_PROTECTION_ALLOW_PAPER_ORDERS","0")=="1")


def report():
    with _lock:
        snapshot=json.loads(json.dumps(_last))
    snapshot["configured_for_paper_orders"]=armed()
    snapshot["broker_stop_execution_guaranteed"]=False
    snapshot["broker_only"]="paper-api.alpaca.markets"
    snapshot["policy"]="EOD ATR14 3-8% initial stop, 2.5R TP, ATR+MFE one-way ratchet"
    snapshot["disclaimer"]=(
        "OCO limits/stop triggers do not guarantee realized prices, especially during "
        "gaps, halts, or outside US regular hours; a pending replacement is not protection.")
    return snapshot


def _saved(account,symbol):
    return one("SELECT * FROM sw_protection WHERE account_id=? AND symbol=?",(account,symbol))


def _candidate_bars(symbol,now):
    stamp=completed_day(now)
    bars=rows("""SELECT day,o,h,l,c,v,source,adjustment,observed_at
      FROM sw_eod_observations WHERE symbol=? AND day<=?
      ORDER BY day DESC LIMIT 15""",(symbol,stamp))[::-1]
    if len(bars)!=15 or any(x["source"]!="alpaca_iex_daily" or x["adjustment"]!="RAW" for x in bars):
        raise ProtectionError("protection_certified_atr_unavailable")
    # Require 15 consecutive XNYS dates; prevent hiding a split or missing session.
    calendar=__import__("stockswatch.sessions",fromlist=["calendar"]).calendar()
    expected=[x.date().isoformat() for x in calendar.sessions_window(stamp,-14)]
    if [x["day"] for x in bars]!=expected:
        raise ProtectionError("protection_atr_session_gap")
    for b in bars:
        if not instant(b["observed_at"])<=now:
            raise ProtectionError("protection_unpublished_daily_bar")
    return bars


def _entry_id(account,symbol):
    # Alpaca Paper position ownership requires an ACK'd EOD BUY intent and
    # a complete fill history; never seize a manually opened position.
    row=one("""SELECT client_id FROM sw_alpaca_intents
       WHERE account_id=? AND symbol=? AND side='BUY'
       AND client_id LIKE ? AND broker_order_id IS NOT NULL
       ORDER BY created_at DESC LIMIT 1""",(account,symbol,"swp2-%"))
    if not row:
        raise ProtectionError("protection_entry_intent_missing")
    return row["client_id"]


def _find_live_quote(data,symbol,now):
    from .intraday_market import positive
    if not session(now.astimezone(NY).date().isoformat()):
        raise ProtectionError("protection_market_closed")
    bounds=session(now.astimezone(NY).date().isoformat())
    if not bounds[0]<=now<bounds[1]:
        raise ProtectionError("protection_core_session_only")
    result=data.snapshots([symbol],"iex")
    row=result.get(symbol) or {}
    quote=row.get("latestQuote") or {}
    try:
        age=now-instant(quote["t"])
        bid,ask=positive(quote["bp"]),positive(quote["ap"])
        if not timedelta(0)<=age<=timedelta(seconds=20) or bid>=ask:
            raise ValueError("stale_or_crossed")
        if (ask-bid)/bid>D(".0075"):
            raise ValueError("spread_too_wide")
    except (KeyError,ValueError,TypeError):
        raise ProtectionError("protection_quote_stale_or_wide") from None
    return bid,instant(quote["t"]).isoformat()


def _nested(client,account):
    items=client.get("/v2/orders",{"status":"open","limit":500,"nested":"true"})
    if not isinstance(items,list) or len(items)>=500:
        raise ProtectionError("protection_open_order_snapshot_incomplete")
    if any(not isinstance(o,dict) for o in items):
        raise ProtectionError("protection_open_order_invalid")
    return items


def _validate_pair(root,record):
    if (root.get("client_order_id")!=record["client_id"]
        or root.get("id") is None or root.get("symbol")!=record["symbol"]
        or root.get("side")!="sell" or root.get("order_class")!="oco"
        or root.get("type")!="limit" or root.get("time_in_force")!="gtc"
        or root.get("status") not in _STATES):
        raise ProtectionError("protection_oco_parent_invalid")
    try:
        tp=profit_lock.decimal(root["limit_price"])
    except (KeyError,ValueError):
        raise ProtectionError("protection_oco_target_missing") from None
    if tp!=profit_lock.decimal(record["target"]):
        raise ProtectionError("protection_oco_target_changed")
    children=root.get("legs")
    if not isinstance(children,list):
        raise ProtectionError("protection_oco_legs_unavailable")
    stops=[x for x in children if (isinstance(x,dict) and x.get("side")=="sell"
           and x.get("type")=="stop" and x.get("status") in _STATES)]
    if len(stops)!=1:
        raise ProtectionError("protection_oco_stop_missing")
    child=stops[0]
    if not re.fullmatch(r"[0-9A-Za-z-]{8,100}",str(child.get("id",""))):
        raise ProtectionError("protection_oco_stop_id_invalid")
    stop=profit_lock.decimal(child.get("stop_price"))
    qty=profit_lock.decimal(root["qty"])
    # Partial TP fills adjust remaining qty, which must never exceed entry qty.
    if qty>profit_lock.decimal(record["qty"]) or stop>=tp:
        raise ProtectionError("protection_oco_quantity_or_levels_invalid")
    if (record["root_order_id"] and root["id"]!=record["root_order_id"]):
        raise ProtectionError("protection_oco_root_changed")
    return child["id"],stop


def _set_state(record,state,*,root=None,leg=None,stop=None,requested=None,error=None,peak=None,quote_at=None):
    with connect() as c:
        c.execute("""UPDATE sw_protection SET
          state=?,root_order_id=COALESCE(?,root_order_id),
          stop_leg_id=COALESCE(?,stop_leg_id),
          broker_stop=COALESCE(?,broker_stop),
          current_stop=CASE WHEN ? IS NOT NULL THEN ? ELSE current_stop END,
          requested_stop=?,last_error=?,highwater=COALESCE(?,highwater),
          last_quote_at=COALESCE(?,last_quote_at),updated_at=?
          WHERE account_id=? AND symbol=? AND entry_client_id=?""",
        (state,root,leg,str(stop) if stop is not None else None,
         str(stop) if stop is not None else None,
         str(stop) if stop is not None else None,
         str(requested) if requested is not None else None,error,
         str(peak) if peak is not None else None,quote_at,utc(),
         record["account_id"],record["symbol"],record["entry_client_id"]))


def _create(client,account,pos,plan,entry_cid,now,bid):
    symbol=pos["symbol"]
    # Historical intent is durable before POST, so transport failures NEVER
    # cause an automatic duplicate submission.
    cid=PREFIX+hashlib.sha256(
        f"protection|{account}|{entry_cid}|{symbol}".encode()).hexdigest()[:40]
    if not profit_lock.feasible_oco(plan,bid):
        raise ProtectionError("protection_oco_levels_not_away_from_market")
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT 1 FROM sw_protection WHERE account_id=? AND symbol=?",
                     (account,symbol)).fetchone():
            c.rollback()
            return "existing_protection_record"
        c.execute("""INSERT INTO sw_protection
            (account_id,symbol,entry_client_id,qty,entry,atr,initial_stop,
             current_stop,target,highwater,client_id,state,updated_at)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,'PREPARED',?)""",
            (account,symbol,entry_cid,str(plan.qty),str(plan.entry),str(plan.atr),
             str(plan.initial_stop),str(plan.initial_stop),str(plan.target),
             str(max(plan.entry,bid)),cid,utc()))
        c.commit()
    payload={"symbol":symbol,"side":"sell","type":"limit",
        "time_in_force":"gtc","order_class":"oco","qty":str(plan.qty),
        "client_order_id":cid,
        "take_profit":{"limit_price":str(plan.target)},
        "stop_loss":{"stop_price":str(plan.initial_stop)}}
    record=_saved(account,symbol)
    try:
        # Deliberately do NOT use PaperClient.submit (its standard EOD shape
        # rejects OCO). Only this fixed validated paper route can submit OCO.
        response=client._request("POST","/v2/orders",json=payload)
        if (not isinstance(response,dict) or
            response.get("client_order_id")!=cid or
            response.get("order_class")!="oco" or
            response.get("symbol")!=symbol or response.get("side")!="sell" or
            not response.get("id")):
            raise ProtectionError("protection_post_response_unverified")
    except Exception:
        _set_state(record,"UNKNOWN",error="protection_create_outcome_uncertain")
        return "create_uncertain_blocked"
    _set_state(record,"ACKNOWLEDGED",root=response["id"])
    return "oco_submitted_pending_broker_verification"


def _ratchet(client,record,root,leg,broker_stop,bid,quote_at):
    if record["state"] in ("PREPARED","UNKNOWN","REPLACE_PENDING","REPLACE_UNCERTAIN"):
        raise ProtectionError("protection_uncertain_intent_block")
    plan=profit_lock.initial(record["entry"],record["qty"],record["atr"])
    if plan.target!=profit_lock.decimal(record["target"]):
        raise ProtectionError("protection_policy_drift")
    prior=profit_lock.decimal(record["current_stop"])
    if broker_stop+ D(".001") < prior:
        raise ProtectionError("protection_broker_stop_below_committed")
    high=max(profit_lock.decimal(record["highwater"]),bid)
    goal=profit_lock.next_stop(plan,max(broker_stop,prior),high,bid)
    with connect() as c:
        c.execute("UPDATE sw_protection SET highwater=?,last_quote_at=?,updated_at=? WHERE account_id=? AND symbol=?",
            (str(high),quote_at,utc(),record["account_id"],record["symbol"]))
    # Broker stop modification requires an actual price improvement.
    if goal <=broker_stop+D(".009"):
        return "protection_stop_unchanged"
    if goal>=bid:
        return "protection_price_below_existing_stop"
    # One-way durable replacement intent, without replay on unknown outcome.
    _set_state(record,"REPLACE_PENDING",root=root["id"],leg=leg,stop=broker_stop,requested=goal)
    try:
        response=client._request("PATCH",f"/v2/orders/{leg}",json={"stop_price":str(goal)})
        if not isinstance(response,dict) or response.get("side")!="sell":
            raise ProtectionError("protection_replace_response_unverified")
    except Exception:
        _set_state(record,"REPLACE_UNCERTAIN",error="protection_replace_outcome_uncertain",requested=goal)
        return "replace_uncertain_blocked"
    return "stop_replace_requested_pending_broker_proof"


def _sync(client,record,group):
    matches=[root for root in group if root.get("client_order_id")==record["client_id"]]
    if len(matches)!=1:
        # A 404 is NEVER interpreted as permission to sell another full qty.
        # One leg may already have filled, canceled the sibling, or replaced.
        _set_state(record,"UNVERIFIED",error="protection_oco_not_in_open_book")
        return "oco_not_verified_do_not_resubmit"
    root=matches[0]
    try:
        leg,actual=_validate_pair(root,record)
    except (ProtectionError,ValueError) as exc:
        _set_state(record,"UNVERIFIED",error=str(exc))
        return "oco_leg_verification_failed"
    previous=profit_lock.decimal(record["current_stop"])
    if record["state"] in ("REPLACE_PENDING","REPLACE_UNCERTAIN"):
        requested=profit_lock.decimal(record["requested_stop"])
        if actual<requested:
            return "oco_replace_pending_no_repeat"
    if actual<previous:
        _set_state(record,"UNVERIFIED",error="broker_stop_lower_than_saved")
        return "broker_stop_lower_than_saved"
    _set_state(record,"ACTIVE",root=root["id"],leg=leg,stop=actual)
    return "active_oco_verified"


def _snapshot_position(report,record,pos,plan,reason):
    current_stop=record["broker_stop"] if record and record.get("state")=="ACTIVE" else None
    show_stop=record["current_stop"] if record else str(plan.initial_stop)
    return {"symbol":pos["symbol"],"qty":str(pos["qty"]),
            "entry":str(plan.entry),"initial_stop":str(plan.initial_stop),
            "target":str(plan.target),"atr14":str(plan.atr),
            "planned_stop":show_stop,"verified_broker_stop":current_stop,
            "highwater":record["highwater"] if record else None,
            "trigger_profit_usd":str(profit_lock.profit_dollars(plan,show_stop)),
            "broker_state":record["state"] if record else "NOT_PLACED",
            "reason":reason,
            "paper":True}


def cycle(client,snapshot,now=None,data=None):
    """Poll verified EOD-owned LONGs, optionally create/ratchet OCO paper orders.

    Called exclusively while the shared broker_cycle_lock is held.
    """
    from . import alpaca_paper as paper
    from .intraday_market import IntradayData
    from .intraday_policy import phase_at

    global _last
    now=now or datetime.now(timezone.utc)
    account=snapshot["account"]["id"]
    enabled=armed()
    paused=(one("SELECT paused FROM sw_alpaca_state WHERE id=1") or {}).get("paused",1)
    if snapshot["warnings"].get("fills") or snapshot["warnings"].get("open_orders"):
        raise ProtectionError("protection_broker_fill_or_order_data_incomplete")
    if any(p.get("side")=="short" for p in snapshot["positions"]):
        raise ProtectionError("protection_short_inventory_requires_review")
    outcomes=[]
    changed=False
    nested=None
    core=phase_at(now).name=="CORE"
    managed={r["symbol"]:r for r in rows("SELECT * FROM sw_protection WHERE account_id=?",(account,))}
    if any(r["state"] in ("UNKNOWN","REPLACE_UNCERTAIN","UNVERIFIED") for r in managed.values()):
        # Continue showing the last evidence, but do not submit new unrelated
        # protection orders until the ambiguous broker situation is resolved.
        enabled=False
    if enabled and core and not paused and data is None:
        data=IntradayData(background=True)
        close_data=True
    else:
        close_data=False
    try:
        if enabled and core and not paused:
            nested=_nested(client,account)
        for p in snapshot["positions"]:
            if p.get("side")!="long" or p.get("asset_class")!="us_equity":
                continue
            sym=p.get("symbol")
            if not isinstance(sym,str):
                continue
            saved=managed.get(sym)
            try:
                if not paper._position_owned(p,snapshot["fills"],account):
                    raise ProtectionError("protection_position_not_eod_owned")
                if paper.money(p.get("qty_available"))!=paper.money(p.get("qty")):
                    raise ProtectionError("protection_position_qty_not_fully_available")
                entry_cid=_entry_id(account,sym)
                if saved and saved["entry_client_id"]!=entry_cid:
                    raise ProtectionError("protection_position_entry_changed")
                bars=_candidate_bars(sym,now)
                if saved:
                    plan=profit_lock.initial(saved["entry"],saved["qty"],saved["atr"])
                else:
                    plan=profit_lock.initial(p["avg_entry_price"],p["qty"],profit_lock.atr14(bars))
                if saved and (profit_lock.decimal(p["qty"])>plan.qty or
                              profit_lock.decimal(p["avg_entry_price"])!=plan.entry):
                    raise ProtectionError("protection_position_reconciled_qty_or_basis_changed")
                reason="observe_only_disabled_or_paused"
                if enabled and core and not paused:
                    if saved:
                        reason=_sync(client,saved,nested)
                        saved=_saved(account,sym)
                        if saved["state"]=="ACTIVE":
                            bid,qt=_find_live_quote(data,sym,now)
                            root=next(x for x in nested if x.get("client_order_id")==saved["client_id"])
                            outcome=_ratchet(client,saved,root,saved["stop_leg_id"],
                                             profit_lock.decimal(saved["broker_stop"]),bid,qt)
                            if outcome.startswith("stop_replace_requested"):
                                changed=True
                            reason=outcome
                    else:
                        if any(o.get("symbol")==sym for o in snapshot["open_orders"]):
                            raise ProtectionError("protection_competing_open_order")
                        bid,qt=_find_live_quote(data,sym,now)
                        reason=_create(client,account,p,plan,entry_cid,now,bid)
                        if reason.startswith("oco_submitted"):
                            changed=True
                        saved=_saved(account,sym)
                outcomes.append(_snapshot_position(report,saved,p,plan,reason))
            except Exception as exc:
                label=str(exc) if isinstance(exc,(ProtectionError,ValueError)) else type(exc).__name__
                outcomes.append({"symbol":sym,"broker_state":saved["state"] if saved else "UNPROTECTED",
                                 "reason":label,"paper":True})
        # Preserve unresolved records for positions no longer in broker snapshots
        # until broker fills and order-terminal events are reconciled explicitly.
        for sym,record in managed.items():
            if sym not in [p.get("symbol") for p in snapshot["positions"]]:
                outcomes.append({"symbol":sym,"broker_state":record["state"],
                                 "reason":"position_absent_requires_fill_reconciliation","paper":True})
    finally:
        if close_data:
            data.close()
    output={"status":"OBSERVING" if not enabled else "PAPER_OCO_MONITORING",
            "positions":outcomes,"changed":changed,"at":utc(),
            "paper_orders_enabled":bool(enabled and not paused),
            "broker_only":"paper-api.alpaca.markets"}
    with _lock:
        _last=output
    return output


def recognized_order_ids(account_id):
    """Known OCO parent/child IDs, used solely for non-entry cash accounting."""
    result=set()
    for r in rows("""SELECT root_order_id,stop_leg_id FROM sw_protection
         WHERE account_id=? AND state IN ('ACKNOWLEDGED','ACTIVE','REPLACE_PENDING',
                                            'REPLACE_UNCERTAIN','UNVERIFIED')""",(account_id,)):
        result.update(x for x in (r["root_order_id"],r["stop_leg_id"]) if x)
    return result
