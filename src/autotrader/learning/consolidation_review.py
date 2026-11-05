"""Trace joins, conservative forward labels and immutable postmortems."""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal as D

from autotrader.learning import features, targets
from autotrader.learning.consolidation import now_utc, referenced, utc
from autotrader.research.data import canonical, digest

REVIEW_SCHEMA = "cross-account-postmortem/1"


def gate_evidence(evidence: dict) -> dict:
    groups = {}
    for group in ("quality_policy", "primary_admission"):
        gates = (evidence.get(group) or {}).get("gates") or {}
        groups[group] = {"failed": sorted(k for k,v in gates.items() if v is False),
                         "passed": sorted(k for k,v in gates.items() if v is True),
                         "unknown": sorted(k for k,v in gates.items() if not isinstance(v,bool))}
    return {"structured":groups,"unclassified_reason_tokens":evidence.get("reasons",[]),
            "technical_eligible":evidence.get("technical_eligible"),"economic_eligible":evidence.get("economic_eligible")}


def rejection_class(reason: str | None) -> str:
    reason = reason or ""
    if "shadow_frozen_source_changed" in reason or "frozen_runtime" in reason:
        return "FROZEN_SOURCE_AUTHORITY"
    if "entry_frequency" in reason or "cooldown" in reason:
        return "FREQUENCY_OR_COOLDOWN"
    if "planned_loss" in reason:
        return "PLANNED_LOSS_LIMIT"
    if reason.startswith("risk_rejected:"):
        return "OTHER_RISK_CONTROL"
    if any(token in reason for token in ("stale","data_unavailable","missing_book")):
        return "DATA_QUALITY"
    return "OTHER_OR_UNDOCUMENTED"


def reconcile_position(position, fills, journal, exit_targets):
    """Reconcile independent cash-flow and journal P&L; refuse incomplete chains."""
    entry = [r for r in fills if r.get("side")=="BUY"]
    exits = [r for r in fills if r.get("side")=="SELL"]
    findings = []
    if (position.get("state")!="CLOSED" or not position.get("closed_at") or not entry or not exits
            or not journal or any(r.get("simulated") is not True or r.get("attribution_status")!="CONFIRMED" for r in fills)
            or len(entry)+len(exits)!=len(fills)
            or any(r.get("account_id")!=position.get("account_id") for r in [*fills,*journal])
            or any(r.get("currency")!="EUR" or r.get("reconciliation_state")!="CONFIRMED" for r in journal)):
        return {"status":"INCONCLUSIVE_FINANCIAL_CHAIN","position_id":position["position_id"]}
    try:
        fill_numbers=[[D(str(r[k])) for k in ("quantity","price","fee")] for r in fills]
        pnl_numbers=[D(str(position["realized_pnl"])),*(D(str(r["realized_pnl_delta"])) for r in journal)]
        if (any(not v.is_finite() for values in fill_numbers for v in values)
                or any(q<=0 or price<=0 or fee<0 for q,price,fee in fill_numbers)
                or any(not n.is_finite() for n in pnl_numbers)):
            raise ValueError("invalid_financial_value")
    except (ArithmeticError,ValueError,KeyError,TypeError):
        return {"status":"INCONCLUSIVE_FINANCIAL_VALUES","position_id":position["position_id"]}
    qty_in = sum((D(str(r["quantity"])) for r in entry), D(0))
    qty_out = sum((D(str(r["quantity"])) for r in exits), D(0))
    buy = sum((D(str(r["quantity"]))*D(str(r["price"])) for r in entry), D(0))
    sell = sum((D(str(r["quantity"]))*D(str(r["price"])) for r in exits), D(0))
    fees = sum((D(str(r["fee"])) for r in fills), D(0))
    net = D(str(position["realized_pnl"]))
    journal_net = sum((D(str(r["realized_pnl_delta"])) for r in journal), D(0))
    fill_ids = {r["fill_id"] for r in fills}
    journal_fill_ids = {r["fill_id"] for r in journal if r.get("fill_id")}
    balanced = (qty_in>0 and qty_in==qty_out and len(fill_ids)==len(fills) and fill_ids<=journal_fill_ids
                and abs(net-journal_net)<=D(".000001") and abs(net-(sell-buy-fees))<=D(".000001"))
    price = buy/qty_in if qty_in else None
    initial_stop = D(str(position["initial_stop"])) if position.get("initial_stop") is not None else None
    target_qty = sum((D(str(r["filled_quantity"])) for r in exit_targets), D(0)) if exit_targets else None
    if target_qty == 0: findings.append("NO_RECORDED_TARGET_QUANTITY")
    return {"status":"RECONCILED" if balanced else "FINANCIAL_MISMATCH","position_id":position["position_id"],
            "entry_vwap":str(price) if price else None,"exit_vwap":str(sell/qty_out) if qty_out else None,
            "gross_pnl_eur":str(sell-buy),"fees_eur":str(fees),"net_pnl_eur":str(net),
            "journal_net_eur":str(journal_net),"net_return":float(net/(buy+sum((D(str(r["fee"])) for r in entry),D(0)))) if balanced and buy>0 else None,
            "initial_stop":str(initial_stop) if initial_stop is not None else None,
            "initial_stop_fraction":float((price-initial_stop)/price) if price and initial_stop is not None else None,
            "last_protective_stop":position.get("protective_stop"),"trailing_distance":position.get("trailing_distance"),
            "target_filled_quantity":str(target_qty) if target_qty is not None else None,
            "closed_at":position["closed_at"],"fill_ids":sorted(fill_ids),
            "journal_ids":[r["ledger_event_id"] for r in journal],"findings":findings}


def position_trace(store, source, position_id):
    rows = referenced(store,source,"positions",value=position_id)
    if not rows: return {"status":"POSITION_NOT_COLLECTED","position_id":position_id}
    position = rows[0]
    related = {kind:referenced(store,source,kind,column="position_id",value=position_id)
               for kind in ("orders","fills","exit_targets","exit_intents","exit_plans","financial_journal")}
    audit = reconcile_position(position,related["fills"],related["financial_journal"],related["exit_targets"])
    audit["exit_reasons"] = [r["reason"] for r in related["exit_intents"]]
    audit["entry_observations"] = [
        {"order_id":r["order_id"],"quote":r.get("execution_json",{}).get("execution_quality"),
         "planned_loss":r.get("execution_json",{}).get("planned_loss_trace")}
        for r in related["orders"] if r.get("side")=="BUY"]
    if audit["status"]=="RECONCILED":
        if D(audit["gross_pnl_eur"])>=0>D(audit["net_pnl_eur"]):
            audit["findings"].append("RECORDED_FEES_ERASED_GROSS_GAIN")
        ages=[q["quote"].get("book_age_seconds") for q in audit["entry_observations"] if q["quote"]]
        if any(age is not None and D(str(age))>20 for age in ages):
            audit["findings"].append("ENTRY_BOOK_OLDER_THAN_CURRENT_RESEARCH_AGE_LIMIT")
        try:
            start,end=utc(position["opened_at"]),utc(position["closed_at"])
            bars=price_path(store,position["symbol"],start,end)
            first=(int(features.stamp(start).timestamp())//300+1)*300
            finish=int(features.stamp(end).timestamp())//300*300
            bars=[b for b in bars if first<=features.stamp(b["timestamp"]).timestamp()<finish]
            if not bars or [int(features.stamp(b["timestamp"]).timestamp()) for b in bars]!=list(range(first,finish,300)):
                raise ValueError("incomplete_held_position_path")
            entry=D(audit["entry_vwap"])
            high=max(D(b["high"]) for b in bars)
            low=min(D(b["low"]) for b in bars)
            audit["held_market_path"]={"mfe_fraction":str(high/entry-1),"mae_fraction":str(low/entry-1),
                "candle_count":len(bars),"price_type":"MIDPOINT_NO_EXECUTION_PROOF",
                "path_hash":digest(canonical(bars)),
                "target_mid_touches":[r["target_id"] for r in related["exit_targets"] if high>=D(str(r["target_price"]))]}
        except (KeyError,ValueError,TypeError,ArithmeticError):
            audit["held_market_path"]={"status":"INCONCLUSIVE_CANDLE_COVERAGE"}
    related["order_transitions"] = [x for r in related["orders"] for x in
        referenced(store,source,"order_transitions",column="order_id",value=r["order_id"])]
    return {"position":position,"related":related,"reconciliation":audit,
            "cause_proven":False,"scope":"Realized ledger and recorded execution. Alternative exits require their own evidence."}


def decision_trace(store, source, decision_id):
    decisions = referenced(store,source,"trading_decisions",value=decision_id)
    if not decisions: return {"status":"DECISION_NOT_COLLECTED","decision_id":decision_id}
    row = decisions[0]
    orders = referenced(store,source,"orders",column="decision_id",value=decision_id)
    signals = [s for (key,) in store.db.execute("SELECT signal_id FROM research_links WHERE source=? AND decision_id=? ORDER BY signal_id",(source,decision_id))
               for s in referenced(store,source,"strategy_signals",value=key)]
    return {"decision":row,"signals":signals,"orders":orders,
            "risk_evaluations":referenced(store,source,"risk_evaluations",column="decision_id",value=decision_id),
            "unattributed_fills":[f for o in orders if not o.get("position_id")
                                  for f in referenced(store,source,"fills",column="order_id",value=o["order_id"])],
            "positions":[position_trace(store,source,p) for p in sorted({o["position_id"] for o in orders if o.get("position_id")})],
            "order_rejections":[{"order_id":r["order_id"],"reason":r.get("execution_json",{}).get("rejection_reason"),
                 "category":rejection_class(r.get("execution_json",{}).get("rejection_reason"))}
                 for r in orders if r["status"] in {"CANCELLED","REJECTED","EXPIRED"}]}


def price_path(store, symbol, start, end):
    # Read distinct content, but retain competing revisions to make conflicts visible.
    rows = store.db.execute("""SELECT DISTINCT v.content_hash,c.payload FROM research_refs r
        JOIN research_versions v USING(source,kind,record_id) JOIN research_content c ON c.hash=v.content_hash
        WHERE r.kind='market_candles' AND r.symbol=? AND r.timeframe='5m'
          AND r.observed_at>=? AND r.observed_at<? ORDER BY r.observed_at,v.content_hash""",(symbol,start,end))
    bars = [json.loads(r[1]) for r in rows]
    bars = [b for b in bars if b["source"].startswith("revolut-x")]
    by_time = {}
    for b in bars:
        at=b["timestamp"]
        if at in by_time and by_time[at]!=b:
            raise ValueError("conflicting_forward_candles")
        by_time[at]=b
    return list(by_time.values())


def eligible_feature(store, source, signal, decision_at):
    key=signal["signal_id"]
    count=store.db.execute("SELECT count(*) FROM research_versions WHERE source=? AND kind='strategy_signals' AND record_id=?",
                           (source,key)).fetchone()[0]
    known=utc(signal["created_at"])
    if count != 1 or known>decision_at:
        raise ValueError("signal_revision_or_late_ingestion")
    if signal.get("data_quality")!="GOOD":
        raise ValueError("signal_quality_not_good")
    evidence=signal["payload_json"]["evidence"]
    return features.build(evidence,signal["strategy_id"],known)


def sizing_advice(*, stop_fraction, cost_fraction, atr_fraction, risk_budget, remaining_risk, max_notional, available_cash):
    """Suggest a capped notional; never widen an existing order or submit one."""
    stop,cost,atr,budget,remaining,cap,cash = map(features.finite,
        (stop_fraction,cost_fraction,atr_fraction,risk_budget,remaining_risk,max_notional,available_cash))
    if min(stop,cost,atr,budget,remaining,cap,cash)<0 or max(stop,cost,atr)>=1:
        raise ValueError("invalid_research_sizing_inputs")
    stress=max(stop,atr)+cost
    return {"suggested_notional":min(cap,cash,min(budget,remaining)/stress) if stress else None,
            "stress_loss_fraction":stress,"stop_inside_one_atr":stop<atr,"advisory_only":True}


def costed_path(event, bars, horizon, stress=1.):
    """Use recorded net-unit targets with the existing bid-side path engine."""
    evidence=event["evidence"]
    measurement=evidence["economics"]["measurements"]
    blocked={"minimum_order_not_met","maximum_order_exceeded","invalid_partial_exit_schedule",
             "partial_exit_below_instrument_minimum","insufficient_observed_exit_depth","no_executable_entry_depth"}
    if blocked.intersection(evidence.get("reasons",[])) or blocked.intersection(evidence["economics"].get("reasons",[])):
        raise ValueError("recorded_instrument_or_depth_constraint")
    schedule=tuple(D(str(f)) for f in measurement.get("partial_exit_fractions") or ())
    if schedule!=(D(".3"),D(".4"),D(".3")):
        raise ValueError("unknown_or_unsupported_target_quantity_schedule")
    assumptions=measurement["assumptions"]
    fee=features.finite(assumptions["exit_fee_bps"])*stress/10000
    slip=features.finite(assumptions["slippage_bps"])*stress/10000
    impact=features.finite(measurement["exit_now"]["depth_impact_bps"])*stress/10000
    if not all(0<=v<1 for v in (fee,slip,impact)):
        raise ValueError("invalid_exit_cost_factors")
    factor=(1-fee)*(1-slip)*(1-impact)
    adjusted={**evidence["entry_plan"],"targets":[features.finite(t)/factor for t in evidence["entry_plan"]["targets"]]}
    holding_minutes=5*int(measurement["holding_bars"])
    if holding_minutes<=0:
        raise ValueError("invalid_plan_holding_period")
    result=targets.label({**event,"evidence":{**evidence,"entry_plan":adjusted}},bars,
                         min(horizon,holding_minutes),cost_stress=stress)
    return {**result,"target_scope":"RECORDED_NET_TARGET_THRESHOLDS_INCLUDING_EXIT_COSTS",
            "target_bid_triggers":adjusted["targets"],"requested_horizon_minutes":horizon}


def assess_task(store, task, now):
    source,kind,key,symbol,at,due,horizon=(
        task[k] for k in ("source","kind","record_id","symbol","observed_at","due_at","horizon"))
    raw = store.db.execute("SELECT payload FROM research_content WHERE hash=?",(task["content_hash"],)).fetchone()
    row=json.loads(raw[0])
    source_row=store.db.execute("SELECT role,payload FROM research_sources WHERE source=?",(source,)).fetchone()
    manifest=json.loads(source_row[1])["manifest"]
    signal=row if kind=="strategy_signals" else None
    linked=[key] if kind=="trading_decisions" else [
        r[0] for r in store.db.execute("SELECT decision_id FROM research_links WHERE source=? AND signal_id=? ORDER BY decision_id",(source,key))]
    traces=[decision_trace(store,source,d) for d in linked]
    if signal is None:
        candidates=[s for t in traces for s in t.get("signals",[]) if utc(s["created_at"])<=at and s["symbol"]==symbol]
        if len(candidates)==1: signal=candidates[0]
    financial=[p["reconciliation"] for t in traces for p in t.get("positions",[]) if "reconciliation" in p]
    # Repeated decision references do not create repeated financial outcomes.
    financial=list({f["position_id"]:f for f in financial}.values())
    reasons=[r for t in traces for r in t.get("order_rejections",[])]
    accepted=any(t.get("decision",{}).get("accepted") is True and t["decision"]["action"]=="BUY"
                 and utc(t["decision"]["created_at"])<=at for t in traces)
    recorded_admission=any(t.get("decision",{}).get("accepted") is True and t["decision"]["action"]=="BUY" for t in traces)
    outcome={"schema":REVIEW_SCHEMA,"task_id":task["id"],"source":source,"role":source_row[0],"record_id":key,
             "input_hash":task["content_hash"],"symbol":symbol,"observed_at":at,"end_at":due,"horizon":horizon,
             "decision_ids":linked,"accepted_at_cutoff":accepted,"recorded_admission":recorded_admission,
             "financial":financial,"rejections":reasons,
             "classification":"INCONCLUSIVE","training_eligible":False,"executable_outcome_proven":False}
    reconciled=[f for f in financial if f["status"]=="RECONCILED"]
    if reconciled:
        outcome["classification"]="PROFITABLE_PAPER_FILL" if all(D(f["net_pnl_eur"])>0 for f in reconciled) else "LOSING_OR_MIXED_PAPER_FILL"
    evidence=signal.get("payload_json",{}).get("evidence",{}) if signal else {}
    outcome.update(strategy=signal["strategy_id"] if signal else None,
                   signal_id=signal["signal_id"] if signal else None,gates=gate_evidence(evidence))
    # Keep actual settlement evidence distinct even when the forward path is unavailable.
    try:
        bars=price_path(store,symbol,at,due)
        first=(int(features.stamp(at).timestamp())//300+1)*300
        end=int(features.stamp(due).timestamp())//300*300
        if not bars or [int(features.stamp(b["timestamp"]).timestamp()) for b in bars]!=list(range(first,end,300)):
            # At exact boundaries price_path includes the entry bar; it is intentionally excluded.
            bars=[b for b in bars if first<=features.stamp(b["timestamp"]).timestamp()<end]
        if not bars or [int(features.stamp(b["timestamp"]).timestamp()) for b in bars]!=list(range(first,end,300)):
            raise ValueError("incomplete_future_window")
        reference=features.finite(bars[0]["open"])
        outcome["path"]={"scope":"MIDPOINT_PATH_NO_FILL","mfe":max(features.finite(b["high"]) for b in bars)/reference-1,
                         "mae":min(features.finite(b["low"]) for b in bars)/reference-1,"hash":digest(canonical(bars))}
        if not signal: raise ValueError("no_unique_priced_signal_at_decision")
        if manifest.get("data_kind") not in {"REVOLUT_X_PROSPECTIVE_PAPER","LIVE_MARKET_SHADOW"}:
            raise ValueError("source_not_attested_prospective_paper")
        snapshot=eligible_feature(store,source,signal,at)
        measurement=evidence["economics"]["measurements"]
        quote=measurement["entry"]
        if not -2<=features.finite(quote["book_age_seconds"])<=20:
            raise ValueError("stale_decision_quote")
        if features.stamp(at)-features.stamp(snapshot["known_at"])>timedelta(seconds=20):
            raise ValueError("decision_latency_exceeds_quote_budget")
        if features.finite(measurement["fillable_quantity"])<=0 or len(evidence["entry_plan"]["targets"])!=3:
            raise ValueError("no_positive_priced_plan")
        event={"observed_at":at,"symbol":symbol,"evidence":evidence}
        modeled=costed_path(event,bars,horizon)
        stress=costed_path(event,bars,horizon,stress=1.5)
        outcome.update(features=snapshot,target=modeled,stress_target=stress,training_eligible=True,
                       episode=digest(canonical([symbol,snapshot["completed_cutoff"],horizon])),
                       baseline_eligible=accepted or kind=="strategy_signals" and evidence.get("entry_eligible") is True,
                       cost_fraction=snapshot["values"][snapshot["names"].index("roundtrip_fraction")],
                       forecasts={"stop":evidence["entry_plan"]["stop"],"targets":evidence["entry_plan"]["targets"],
                                  "quote_age_seconds":quote["book_age_seconds"],"quote_is_fill":False})
        stop_atr=snapshot["values"][snapshot["names"].index("stop_distance_atr")]
        outcome["research_findings"]=["STOP_INSIDE_ONE_ATR"] if stop_atr<1 else []
        if modeled["exit_reason"]=="STOP_FIRST_CONSERVATIVE" and modeled["exit_feedback"]["mid_recovered_entry_after_stop"]:
            outcome["research_findings"].append("MID_RECOVERED_AFTER_STOP_TOUCH_NO_EXECUTION_PROOF")
        if reasons:
            outcome["research_findings"].extend(sorted({r["category"] for r in reasons}))
        if not reconciled and not recorded_admission and linked and not financial:
            outcome["classification"]="POTENTIALLY_MISSED_MODELED_ONLY" if stress["net_return"]>0 else "REJECTION_SUPPORTED_BY_MODELED_PATH"
        outcome["why"]="Modeled quote and cost stress; missing subsequent depth, execution and account feasibility."
    except (KeyError,ValueError,TypeError,ArithmeticError) as error:
        outcome["why"]=str(error)[:200]
    outcome["next_investigation"] = ("Inspect quote, original risk gates and execution chain before assigning causality."
                                     if outcome["training_eligible"] else "Resolve source coverage or missing causal execution evidence.")
    return outcome


def mature(store, *, now=None, limit=200):
    now=now or now_utc()
    if not 1<=limit<=1000: raise ValueError("invalid_review_batch")
    cursor=store.db.execute("""SELECT * FROM research_tasks WHERE status='PENDING'
        AND due_at<=? AND next_attempt_at<=? ORDER BY due_at,id LIMIT ?""",(now,now,limit))
    names=[d[0] for d in cursor.description]
    tasks=[dict(zip(names,r)) for r in cursor.fetchall()]
    with store.db:
        for task in tasks:
            review=assess_task(store,task,now)
            payload=canonical(review)
            identity=digest(payload)
            store.db.execute("INSERT OR IGNORE INTO research_postmortems VALUES (?,?,?,?)",
                             (identity,task["id"],now,payload.decode()))
            retry=(review.get("why")=="incomplete_future_window"
                   and features.stamp(now)<features.stamp(task["due_at"])+timedelta(days=7))
            store.db.execute("UPDATE research_tasks SET status=?,next_attempt_at=? WHERE id=?",
                ("PENDING" if retry else "REVIEWED",utc(features.stamp(now)+timedelta(hours=6)),task["id"]))
    return len(tasks)
