"""Offline model selection and explicitly enabled research-only inference."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta
from statistics import mean, stdev

from autotrader.learning import model
from autotrader.learning.consolidation import now_utc, utc
from autotrader.learning.features import stamp
from autotrader.research.data import canonical, digest

PROTOCOL = "grouped-cost-aware-walk-forward/1"
EMBARGO = timedelta(days=1)
MIN_FOLD = 24
MIN_SELECTED = 12


def one_per_episode(rows):
    """Source preference and chronology only; returns never select the record."""
    preferred = {"PERSONAL":0,"SHADOW":1,"OPERATIONAL":2}
    unique={}
    for row in sorted(rows,key=lambda r:(preferred.get(r["role"],3),r["observed_at"],
                                          r["source"],r["record_id"],r["task_id"])):
        unique.setdefault(row["episode"],row)
    return sorted(unique.values(),key=lambda r:(r["observed_at"],r["episode"]))


def purged(rows, boundary):
    return [r for r in rows if stamp(r["end_at"])+EMBARGO<=stamp(boundary)]


def observations(store,horizon):
    query="""SELECT p.payload FROM research_postmortems p
        JOIN research_tasks t ON p.task_id=t.id WHERE t.horizon=? AND t.status='REVIEWED'
        AND p.id=(SELECT last.id FROM research_postmortems last WHERE last.task_id=p.task_id
                  ORDER BY last.evaluated_at DESC,last.id DESC LIMIT 1)
        AND NOT EXISTS (SELECT 1 FROM research_versions v
            WHERE v.source=t.source AND v.kind=t.kind AND v.record_id=t.record_id
              AND v.content_hash<>t.content_hash)
        AND (SELECT count(*) FROM research_versions v WHERE v.source=t.source AND v.kind='strategy_signals'
             AND v.record_id=json_extract(p.payload,'$.signal_id'))=1
        ORDER BY t.observed_at,t.id"""
    return [row for (raw,) in store.db.execute(query,(horizon,))
            if (row:=json.loads(raw)).get("training_eligible") is True]


def fit_prior(rows):
    if len(rows)<2*MIN_FOLD: raise ValueError("insufficient_prior_rows")
    boundary=rows[int(len(rows)*.8)]["observed_at"]
    fit=purged(rows,boundary)
    cal=[r for r in rows if r["observed_at"]>=boundary]
    if min(len(fit),len(cal))<MIN_FOLD: raise ValueError("insufficient_purged_fit_or_calibration")
    return model.fit(fit,cal)


def nonoverlap(rows, mask):
    """One standardized research position at a time across correlated markets."""
    selected=[];until=None
    for row,take in zip(rows,mask,strict=True):
        if take and (until is None or row["observed_at"]>=until):
            selected.append(row);until=row["end_at"]
    return selected


def metrics(rows):
    nets=[r["target"]["net_return"] for r in rows]
    stress=[r["stress_target"]["net_return"] for r in rows]
    total=peak=drawdown=0.
    clusters=defaultdict(list)
    for row,net in zip(rows,nets,strict=True):
        total+=net;peak=max(peak,total);drawdown=max(drawdown,peak-total)
        clusters[row["observed_at"][:10]].append(net)
    daily=[mean(v) for v in clusters.values()]
    ci=None
    if len(daily)>=10:
        center=mean(daily);half=1.96*stdev(daily)/(len(daily)**.5)
        ci=[center-half,center+half]
    wins=sum(n for n in nets if n>0);loss=-sum(n for n in nets if n<0)
    return {"trades":len(nets),"standardized_net_return_sum":sum(nets),
            "expectancy":mean(nets) if nets else None,"stress_expectancy":mean(stress) if stress else None,
            "daily_cluster_mean_ci_approx":ci,"daily_clusters":len(daily),
            "closed_return_drawdown":drawdown,"profit_factor":wins/loss if loss else None,
            "wins":sum(n>0 for n in nets),"losses":sum(n<0 for n in nets),
            "worst_net_return":min(nets) if nets else None,
            "mean_adverse_excursion":mean(r["target"]["mae"] for r in rows) if rows else None,
            "round_trip_cost_estimate_sum":sum(r["cost_fraction"] for r in rows),
            "turnover_normalized_entry_and_exit":2*len(rows),
            "provenance":"MODELED_NO_FILL_STANDARDIZED_NOTIONAL_NOT_ACCOUNT_EQUITY"}


def compare(rows,fitted):
    predictions=[model.predict(fitted,r["features"]) for r in rows]
    mask=[model.research_selected(r["baseline_eligible"],p) for r,p in zip(rows,predictions,strict=True)]
    chosen=nonoverlap(rows,mask);baseline=nonoverlap(rows,[r["baseline_eligible"] for r in rows])
    stats=metrics(chosen)
    bins=model.metrics(rows,[p["probability_net_positive"] for p in predictions],selections=mask)
    breakdown={}
    for name in ("symbol","strategy","regime"):
        groups=defaultdict(list)
        for r in chosen: groups[r["features"].get(name,r.get(name,"UNKNOWN"))].append(r)
        breakdown[name]={k:metrics(v) for k,v in sorted(groups.items())}
    return {"model":stats,"deterministic":metrics(baseline),"NO_TRADE":metrics([]),"segments":breakdown,
            "Brier":bins["brier"],"calibration_error":bins["calibration_error"],"calibration_bins":bins["calibration_bins"],
            "modeled_positive_unselected":sum(not take and r["stress_target"]["net_return"]>0 for take,r in zip(mask,rows,strict=True)),
            "modeled_negative_unselected":sum(not take and r["stress_target"]["net_return"]<0 for take,r in zip(mask,rows,strict=True))}


def passes(report):
    x,b=report["model"],report["deterministic"]
    return (x["trades"]>=MIN_SELECTED and (x["expectancy"] or 0)>0 and (x["stress_expectancy"] or 0)>0
            and x["standardized_net_return_sum"]>=b["standardized_net_return_sum"]
            and x["closed_return_drawdown"]<=b["closed_return_drawdown"]
            and report["calibration_error"]<=.2)


def train(store, *, horizon, holdout_start, holdout_end, untouched=False):
    start,end=utc(holdout_start),utc(holdout_end)
    if not untouched or not start<end<=now_utc(): raise ValueError("explicit_untouched_past_holdout_required")
    if store.db.execute("SELECT 1 FROM research_holdouts WHERE evaluation_start<? AND evaluation_end>?",(end,start)).fetchone():
        raise ValueError("holdout_already_consumed_or_overlapping")
    # Neither selection nor reported OOS claims may reuse a prior holdout.
    used=store.db.execute("SELECT evaluation_start,evaluation_end FROM research_holdouts").fetchall()
    raw=observations(store,horizon)
    eligible=[r for r in raw if not any(r["observed_at"]<b and r["end_at"]>a for a,b in used)]
    # Filter each partition BEFORE grouping so holdout content cannot choose fit rows.
    prior=one_per_episode(purged(eligible,start))
    held=one_per_episode([r for r in eligible if start<=r["observed_at"] and r["end_at"]<=end])
    body={"protocol":PROTOCOL,"status":"INSUFFICIENT_EVIDENCE","horizon":horizon,
          "holdout_start":start,"holdout_end":end,"created_at":now_utc(),
          "eligible_rows":len(raw),"prior_episodes":len(prior),"holdout_episodes":len(held),
          "primary_execution_authorized":False,"automatic_promotion":False}
    def finish():
        with store.db:
            identity=store.artifact(body)
            store.set("consolidation_candidate",{"id":identity,"status":body["status"],"created_at":body["created_at"]})
        return {"model_id":identity,**body}
    if (len(prior)<model.CONFIG["min_episodes"] or len(held)<MIN_FOLD
            or len({r["observed_at"][:10] for r in prior})<model.CONFIG["min_days"]):
        body["reason"]="independent_time_and_episode_coverage_insufficient"
        return finish()
    try:
        body["walk_forward"]=[]
        for lo,hi in ((.55,.75),(.75,1.)):
            left=prior[int(len(prior)*lo)]["observed_at"]
            right=prior[int(len(prior)*hi)]["observed_at"] if hi<1 else start
            fit_rows=purged(prior,left)
            evaluation=[r for r in prior if left<=r["observed_at"] and r["end_at"]<right]
            if len(evaluation)<MIN_FOLD: raise ValueError("insufficient_walk_forward_window")
            body["walk_forward"].append({"start":left,"end":right,"fit_episodes":len(fit_rows),
                                         "results":compare(evaluation,fit_prior(fit_rows))})
        if not all(passes(f["results"]) for f in body["walk_forward"]):
            body.update(status="WALK_FORWARD_REJECTED",reason="preholdout_model_did_not_beat_risk_and_cost_controls")
            return finish()
        fitted=fit_prior(prior)
    except ValueError as error:
        body["reason"]=str(error)
        return finish()
    # Persist consumption before evaluating. A crash cannot permit a second look.
    with store.db:
        store.db.execute("INSERT INTO research_holdouts VALUES (?,?,?)",(start,end,PROTOCOL))
    result=compare(held,fitted)
    stats=result["model"]
    interval=stats["daily_cluster_mean_ci_approx"]
    valid=passes(result) and bool(interval and interval[0]>0)
    body.update(status="VALIDATED_FOR_PAPER_ADVISORY" if valid else "HOLDOUT_REJECTED",
                model=fitted, holdout=result, holdout_consumed=True,
                training_start=prior[0]["observed_at"],training_end=prior[-1]["end_at"],
                dataset_hash=digest(canonical([prior,held])),
                downside_return=sorted(r["target"]["net_return"] for r in prior)[int(.05*len(prior))],
                downside_basis="Unconditional training fifth percentile of modeled net return",
                reason="independent_holdout_supports_advisory_only" if valid else "holdout_cost_risk_or_uncertainty_failed")
    return finish()


def authorize(store,identity,confirmation):
    artifact=store.read_artifact(identity)
    if (confirmation!=identity or artifact.get("protocol")!=PROTOCOL or artifact.get("status")!="VALIDATED_FOR_PAPER_ADVISORY"
            or artifact.get("primary_execution_authorized") is not False):
        raise ValueError("validated_exact_model_and_explicit_confirmation_required")
    if not 0<= (stamp(now_utc())-stamp(artifact["holdout_end"])).total_seconds() <= 30*86400:
        raise ValueError("holdout_evidence_stale")
    with store.db:
        store.set("consolidation_scorer",{"id":identity,"operator_enabled_at":now_utc(),"paper_advisory_only":True})


def score(store, snapshot, *, now, enabled, paper_only, baseline_eligible):
    selection=store.get("consolidation_scorer")
    if not enabled or not paper_only or not selection or selection.get("paper_advisory_only") is not True:
        return {"status":"ABSTAIN_DISABLED","execution_authorized":False}
    identity=selection["id"]
    artifact=store.read_artifact(identity)
    if (artifact.get("protocol")!=PROTOCOL or artifact.get("status")!="VALIDATED_FOR_PAPER_ADVISORY"
            or not 0<=(stamp(now)-stamp(artifact["holdout_end"])).total_seconds()<=30*86400):
        return {"status":"ABSTAIN_STALE_OR_UNVALIDATED","execution_authorized":False}
    if not 0<=(stamp(now)-stamp(snapshot["known_at"])).total_seconds()<=60:
        return {"status":"ABSTAIN_STALE_SNAPSHOT","execution_authorized":False}
    outcomes={}
    for (raw,) in store.db.execute("""SELECT r.payload FROM research_forecast_reviews r
        JOIN research_forecasts f ON f.id=r.forecast_id WHERE f.model_id=? ORDER BY f.created_at DESC LIMIT 100""",(identity,)):
        row=json.loads(raw)
        if row.get("selected") and row.get("stressed_return") is not None and row.get("episode"):
            outcomes.setdefault(row["episode"],row["stressed_return"])
    if len(outcomes)>=20 and mean(outcomes.values())<=0:
        return {"status":"ABSTAIN_OUTCOME_DRIFT","model_id":identity,"execution_authorized":False}
    prediction=model.predict(artifact["model"],snapshot)
    if prediction["feature_drift_fraction"]>.2:
        return {"status":"ABSTAIN_FEATURE_DRIFT","model_id":identity,"execution_authorized":False}
    selected=model.research_selected(baseline_eligible,prediction)
    return {**prediction,"status":"PAPER_ADVISORY_CANDIDATE" if selected else "NO_ADVISORY_CANDIDATE",
            "selected":selected,"model_id":identity,"horizon":artifact["horizon"],
            "downside_return":artifact["downside_return"],"downside_basis":artifact["downside_basis"],
            "execution_authorized":False,"data_known_at":snapshot["known_at"]}
