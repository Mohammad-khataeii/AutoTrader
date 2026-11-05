"""Bounded collection and reporting for the existing dedicated research worker."""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
from collections import Counter
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from autotrader.learning.consolidation import acquire, acquire_fresh_signals, connect_read_only, now_utc, sources, utc
from autotrader.learning.consolidation_model import score
from autotrader.learning.consolidation_review import eligible_feature, mature
from autotrader.learning.consolidation_schema import migrate
from autotrader.learning.features import finite, stamp
from autotrader.learning.store import Store
from autotrader.research.data import atomic_write, canonical, digest

LOG=logging.getLogger(__name__)
SOURCE_ENV="AUTOTRADER_RESEARCH_SOURCE_URL"


def root_for(research_root):
    return Path(research_root).parent/"reports"/"consolidation"


@contextmanager
def locked_store(root):
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (root/"consolidation.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        store=Store(root)
        try:
            migrate(store)
            yield store
        finally:
            store.close()


def read_url():
    from sqlalchemy.engine import make_url
    if not os.environ.get(SOURCE_ENV):
        raise ValueError("dedicated_read_only_research_source_url_required")
    return make_url(os.environ[SOURCE_ENV])


def registered(url):
    with connect_read_only(url) as connection:
        return sources(connection,url.database)


def collect(store,url,*,batch=500,source_budget=None,horizons=(15,60,240,1440),sweep=False):
    inventory=registered(url)
    start=store.get("consolidation_source_rotation",0)%len(inventory)
    selected=inventory[start:]+inventory[:start]
    selected=selected[:source_budget]
    results=[]
    for source in selected:
        try:
            with connect_read_only(url.set(database=source.database)) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                result=acquire(store,connection,source,batch=batch,sweep=sweep,horizons=horizons)
            results.append({"source":source.database,"role":source.role,"status":"COLLECTED","tables":result})
        except (KeyError,ValueError,TypeError) as error:
            results.append({"source":source.database,"role":source.role,"status":"SOURCE_UNAVAILABLE",
                            "error_type":type(error).__name__})
        except Exception as error:
            # Do not expose source DSNs; only explicitly handle PostgreSQL errors.
            import psycopg
            if not isinstance(error,psycopg.Error):raise
            results.append({"source":source.database,"role":source.role,"status":"SOURCE_UNAVAILABLE",
                            "error_type":type(error).__name__})
    with store.db:
        store.set("consolidation_source_rotation",(start+len(selected))%len(inventory))
        store.set("consolidation_collection",{"observed_at":now_utc(),"registered_sources":len(inventory),
                                             "incremental":not sweep,"sources":results})
    return results


def forecast(store, *, enabled, paper_only, now=None):
    now=now or now_utc()
    if not enabled or not paper_only:return 0
    since=utc(stamp(now)-timedelta(seconds=60));count=0
    # No old signal is scored at a retrospective timestamp.
    rows=store.db.execute("""SELECT r.source,r.content_hash,c.payload FROM research_refs r
        JOIN research_content c ON c.hash=r.content_hash JOIN research_sources s ON r.source=s.source
        WHERE r.kind='strategy_signals' AND s.role='PERSONAL' AND r.known_at BETWEEN ? AND ?
        ORDER BY r.known_at DESC,r.record_id LIMIT 100""",(since,now)).fetchall()
    with store.db:
        for source,content_hash,raw in rows:
            signal=json.loads(raw);evidence=signal["payload_json"].get("evidence",{})
            try:
                snapshot=eligible_feature(store,source,signal,now)
                observed=stamp(snapshot["known_at"])
                age=(stamp(now)-observed).total_seconds()
                saved_age=finite(evidence["economics"]["measurements"]["entry"]["book_age_seconds"])
                if not -2<=saved_age<=20 or saved_age+age>20 or int(stamp(now).timestamp())//300!=int(observed.timestamp())//300:
                    store.set("consolidation_scoring_state","ABSTAIN_STALE_OR_LATE_QUOTE")
                    continue
                result=score(store,snapshot,now=now,enabled=True,paper_only=paper_only,
                             baseline_eligible=evidence.get("entry_eligible") is True)
                store.set("consolidation_scoring_state",result["status"])
            except (KeyError,TypeError,ValueError,ArithmeticError,OSError):
                store.set("consolidation_scoring_state","ABSTAIN_INVALID_EVIDENCE_OR_ARTIFACT")
                continue
            if "selected" not in result:continue
            task=store.db.execute("""SELECT id,due_at FROM research_tasks WHERE source=? AND kind='strategy_signals'
                AND record_id=? AND content_hash=? AND horizon=?""",
                (source,signal["signal_id"],content_hash,result["horizon"])).fetchone()
            if not task or task[1]<=now:continue
            identity=digest(canonical([result["model_id"],task[0]]))
            measurement=evidence["economics"]["measurements"]
            payload={"task_id":task[0],"due_at":task[1],"created_at":now,"symbol":signal["symbol"],
                     "signal_id":signal["signal_id"],"snapshot":snapshot,"source":source,
                     "execution_quote":measurement["entry"],"entry_plan":evidence["entry_plan"],
                     "expected_range":{"conditional_expected_return":result["conditional_expected_net_return"],
                                       "training_downside_return":result["downside_return"],
                                       "is_prediction_interval":False},
                     "source_hash":content_hash,"prediction":result}
            count+=store.db.execute("INSERT OR IGNORE INTO research_forecasts VALUES (?,?,?,?)",
                                    (identity,now,result["model_id"],canonical(payload).decode())).rowcount
    return count


def review_forecasts(store, *, now=None, limit=200):
    now=now or now_utc()
    rows=store.db.execute("""SELECT f.id,f.payload,p.id,p.payload FROM research_forecasts f
        JOIN research_tasks t ON t.id=json_extract(f.payload,'$.task_id')
        JOIN research_postmortems p ON p.task_id=t.id
        WHERE t.status='REVIEWED' AND t.due_at<=? AND NOT EXISTS(
          SELECT 1 FROM research_forecast_reviews a WHERE a.forecast_id=f.id)
        AND p.id=(SELECT last.id FROM research_postmortems last WHERE last.task_id=t.id
                  ORDER BY last.evaluated_at DESC,last.id DESC LIMIT 1)
        ORDER BY f.created_at,f.id LIMIT ?""",(now,limit)).fetchall()
    with store.db:
        for identity,raw,post_id,post_raw in rows:
            original,post=json.loads(raw),json.loads(post_raw)
            value=post.get("stress_target",{}).get("net_return")
            selected=original["prediction"]["selected"]
            outcome={"forecast_id":identity,"postmortem_id":post_id,"evaluated_at":now,
                     "selected":selected,"stressed_return":value,"episode":post.get("episode"),
                     "agreement":None if value is None else (original["prediction"]["probability_net_positive"]>=.5)==(value>0),
                     "scope":"MODELED_OUTCOME_NO_FILL","classification":post["classification"],
                     "why":post.get("why"),"next_investigation":post.get("next_investigation")}
            key=digest(canonical([identity,post_id]))
            store.db.execute("INSERT OR IGNORE INTO research_forecast_reviews VALUES (?,?,?)",
                             (key,identity,canonical(outcome).decode()))
    return len(rows)


def publish(store):
    status=store.get("consolidation_candidate")
    scorer=store.get("consolidation_scorer")
    reviews=[json.loads(r[0]) for r in store.db.execute(
        "SELECT payload FROM research_postmortems ORDER BY evaluated_at DESC,id DESC LIMIT 100")]
    forecasts=[json.loads(r[0]) for r in store.db.execute(
        "SELECT payload FROM research_forecasts ORDER BY created_at DESC,id DESC LIMIT 10")]
    finance={(r["source"],f["position_id"]):f for r in reviews for f in r.get("financial",[])
             if f["status"]=="RECONCILED"}
    fees={}
    for (source,_),position in finance.items():
        fees[source]=fees.get(source,Decimal(0))+Decimal(position["fees_eur"])
    summary={"schema":"consolidation-status/1","observed_at":now_utc(),
             "status":status["status"] if status else "COLLECTING_EVIDENCE",
             "model_candidate":status,"paper_advisory_authorization":scorer,
             "model_promotion":"NO_AUTOMATIC_MODEL_PROMOTION",
             "live_authorized":False,"execution_authorized":False,
             "collection":store.get("consolidation_collection"),
             "source_count":store.db.execute("SELECT count(*) FROM research_sources").fetchone()[0],
             "unique_market_candle_contents":store.db.execute("SELECT count(DISTINCT content_hash) FROM research_refs WHERE kind='market_candles'").fetchone()[0],
             "source_errors":store.db.execute("SELECT count(*) FROM research_errors").fetchone()[0],
             "review_tasks":dict(store.db.execute("SELECT status,count(*) FROM research_tasks GROUP BY status")),
             "forecast_count":store.db.execute("SELECT count(*) FROM research_forecasts").fetchone()[0],
             "reviewed_forecasts":store.db.execute("SELECT count(*) FROM research_forecast_reviews").fetchone()[0],
             "scoring_state":store.get("consolidation_scoring_state","DISABLED_OR_AWAITING_EVIDENCE"),
             "recent_forecasts":[{"symbol":r["symbol"],"created_at":r["created_at"],"prediction":r["prediction"]}
                                 for r in forecasts],
             "recent_reconciled_fees_eur_by_source":{source:str(value) for source,value in fees.items()},
             "recent_categories":dict(Counter(r["classification"] for r in reviews)),
             "recent_reviews":[{k:r.get(k) for k in ("record_id","symbol","strategy","observed_at","horizon","classification","why","research_findings")} for r in reviews[:20]],
             "archive_plan":store.get("consolidation_archive_summary"),
             "capacity":store.get("consolidation_capacity"),
             "evidence_scope":"Bounded recent review window; modeled paths do not prove fills or future profits."}
    # Publish bounded, sanitized model evaluation summary without parameters.
    if status:
        artifact=store.read_artifact(status["id"])
        summary["evaluation"]={k:artifact.get(k) for k in ("reason","horizon","prior_episodes","holdout_episodes","holdout_start","holdout_end")}
        if artifact.get("holdout"):
            summary["evaluation"]["holdout"]={k:artifact["holdout"][k] for k in ("model","deterministic","NO_TRADE","calibration_error")}
    atomic_write(store.root/"consolidation-status.json",canonical(summary))
    return summary


def tick(settings, *, full_cycle=True, sweep=False):
    if (os.getenv("PERSONAL_PLAN_CONSOLIDATION_ENABLED")!="true"
            or not settings.paper_trading_enabled or settings.live_trading_enabled):
        return
    root=root_for(settings.research_root)
    with locked_store(root) as store:
        url=read_url()
        if os.getenv("PERSONAL_PLAN_RESEARCH_SCORING")=="true" and store.get("consolidation_scorer"):
            personal=next((r for r in registered(url) if r.role=="PERSONAL"),None)
            if personal:
                with connect_read_only(url.set(database=personal.database)) as connection:
                    acquire_fresh_signals(store,connection,personal,now_utc())
                forecast(store,enabled=True,paper_only=True)
        if full_cycle:
            collect(store,url,batch=200,source_budget=2,sweep=sweep)
            mature(store,limit=60)
            review_forecasts(store,limit=60)
            publish(store)


async def run(settings):
    if os.getenv("PERSONAL_PLAN_CONSOLIDATION_ENABLED")!="true":return
    cycle=0
    while True:
        scoring=os.getenv("PERSONAL_PLAN_RESEARCH_SCORING")=="true"
        stride=8 if scoring else 1
        try:
            await asyncio.to_thread(tick,settings,full_cycle=cycle%stride==0,sweep=(cycle//stride)%4==3)
        except BlockingIOError:
            pass  # Manual CLI or another research process owns the writer lock.
        except Exception as error:
            LOG.error("research_consolidation_cycle_failed error_type=%s",type(error).__name__)
        cycle+=1
        await asyncio.sleep(15 if scoring else 120)
