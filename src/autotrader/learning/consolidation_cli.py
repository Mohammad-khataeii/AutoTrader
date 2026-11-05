"""Operator CLI; only read-only PostgreSQL and isolated research-store writes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from autotrader.learning.consolidation import TABLES, connect_read_only, sources
from autotrader.learning.consolidation_model import authorize, train
from autotrader.learning.consolidation_ops import (CAP_LOCK, archive_copy, archive_plan, check_backup,
    current_seal, flat_stopped, inventory_row, rehydrate)
from autotrader.learning.consolidation_review import decision_trace, mature, position_trace, sizing_advice
from autotrader.learning.consolidation_service import (collect, locked_store, publish, read_url,
    registered, review_forecasts)
from autotrader.research.data import canonical


def inventory(url):
    rows=[]
    for source in registered(url):
        with connect_read_only(url.set(database=source.database)) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            rows.append(inventory_row(connection,source))
    return rows


def require_complete_archive_index(store,connection,source):
    from psycopg import sql
    present={r["table_name"] for r in connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'")}
    for kind,(key,_,_) in TABLES.items():
        if kind not in present:continue
        local=store.db.execute("""SELECT record_id FROM research_refs WHERE source=? AND kind=?
            UNION SELECT record_id FROM research_errors WHERE source=? AND kind=? ORDER BY record_id""",
            (source.database,kind,source.database,kind))
        query=sql.SQL('SELECT {key}::text AS id FROM public.{table} ORDER BY {key}::text COLLATE "C"').format(
            key=sql.Identifier(key),table=sql.Identifier(kind))
        with connection.cursor(name="archive_source_ids") as cursor:
            cursor.execute(query)
            from itertools import zip_longest
            if any(a is None or b is None or a[0]!=b["id"] for a,b in zip_longest(local,cursor)):
                raise ValueError("full_source_backfill_required_before_archive:"+kind)


def prepare_archive(store,args):
    url=read_url()
    with connect_read_only(url) as root:
        root.execute("SELECT pg_advisory_xact_lock(%s)",(CAP_LOCK,))
        rows=sources(root,url.database)
        matches=[r for r in rows if r.role=="SHADOW" and r.identity==args.experiment]
        if len(matches)!=1 or args.confirm!=args.experiment:
            raise ValueError("explicit_existing_shadow_identity_required")
        source=matches[0]
        recovery=check_backup(args.backup,args.restore_proof,source)
        with connect_read_only(url.set(database=source.database)) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            if not flat_stopped(inventory_row(connection,source)):
                raise ValueError("shadow_must_be_paused_flat_reconciled_and_worker_quiescent")
            if current_seal(connection,recovery["financial_seal"])!=recovery["financial_seal"]:
                raise ValueError("source_financial_seal_differs_from_external_restore")
            require_complete_archive_index(store,connection,source)
            result=archive_copy(store,source,args.output,recovery,confirmation=args.confirm)
        # A second snapshot catches a writer or control transition during copying.
        with connect_read_only(url.set(database=source.database)) as final:
            final.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            if (not flat_stopped(inventory_row(final,source))
                    or current_seal(final,recovery["financial_seal"])!=recovery["financial_seal"]):
                raise ValueError("source_changed_during_archive_copy_no_retirement_eligibility")
        receipt=args.output.with_suffix(args.output.suffix+".receipt.json")
        with receipt.open("xb") as output:
            output.write(canonical({**result,"status":"ELIGIBLE_FOR_MANUAL_RETIREMENT_REVIEW"}))
        return {**result,"receipt":str(receipt),"status":"ELIGIBLE_FOR_MANUAL_RETIREMENT_REVIEW"}


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store",type=Path,required=True,help="Dedicated research directory, never a financial database")
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("migrate")
    p=sub.add_parser("inventory");p.add_argument("--cap",type=int,default=3)
    p=sub.add_parser("archive-plan");p.add_argument("--cap",type=int,default=3);p.add_argument("--keep",action="append",default=[])
    p=sub.add_parser("backfill");p.add_argument("--batch",type=int,default=500)
    p.add_argument("--horizon",type=int,action="append");p.add_argument("--sweep",choices=("mutable","all"))
    p=sub.add_parser("review");p.add_argument("--limit",type=int,default=200)
    p.add_argument("--retry-missing-paths",action="store_true")
    p=sub.add_parser("trace");p.add_argument("source");p.add_argument("kind",choices=("decision","position"));p.add_argument("identity")
    p=sub.add_parser("audit-personal");p.add_argument("--output",type=Path)
    p=sub.add_parser("train");p.add_argument("--horizon",type=int,default=240)
    p.add_argument("--holdout-start",required=True);p.add_argument("--holdout-end",required=True)
    p.add_argument("--attest-untouched",action="store_true")
    p=sub.add_parser("authorize-scorer");p.add_argument("model_id");p.add_argument("--confirm",required=True)
    sub.add_parser("disable-scorer")
    p=sub.add_parser("size-advice");p.add_argument("inputs",type=Path)
    p=sub.add_parser("prepare-archive");p.add_argument("experiment");p.add_argument("--confirm",required=True)
    p.add_argument("--backup",type=Path,required=True);p.add_argument("--restore-proof",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("rehydrate");p.add_argument("archive",type=Path);p.add_argument("--sha256",required=True)
    p=sub.add_parser("record-capacity");p.add_argument("report",type=Path)
    sub.add_parser("status")
    args=parser.parse_args()
    with locked_store(args.store) as store:
        cmd=args.command
        if cmd=="migrate":result={"status":"RESEARCH_SCHEMA_READY","financial_migrations":False}
        elif cmd in {"inventory","archive-plan"}:
            result=archive_plan(inventory(read_url()),args.cap,getattr(args,"keep",()))
            shadows=[r for r in result["records"] if r["role"]=="SHADOW"]
            summary={k:result[k] for k in ("active_shadows","maximum_active_shadows","suggested_active","policy")}
            summary["archived_shadows"]=sum(r["archived"] for r in shadows)
            summary["records"]=[{k:r[k] for k in ("identity","strategy","state","archived","closed","realized_net_eur","frozen_source")}
                                for r in shadows[:50]]
            with store.db:store.set("consolidation_archive_summary",summary)
        elif cmd=="backfill":
            result=collect(store,read_url(),batch=args.batch,sweep="all" if args.sweep=="all" else bool(args.sweep),
                           horizons=tuple(args.horizon or (15,60,240,1440)))
        elif cmd=="review":
            if args.retry_missing_paths:
                with store.db:
                    store.db.execute("""UPDATE research_tasks SET status='PENDING',next_attempt_at=due_at
                        WHERE status='REVIEWED' AND id IN (SELECT task_id FROM research_postmortems
                        WHERE json_extract(payload,'$.why')='incomplete_future_window')
                        AND id NOT IN (SELECT task_id FROM research_postmortems
                        WHERE json_extract(payload,'$.training_eligible')=1)""")
            result={"postmortems_processed":mature(store,limit=args.limit),"forecasts_reviewed":review_forecasts(store)}
        elif cmd=="trace":result=(decision_trace if args.kind=="decision" else position_trace)(store,args.source,args.identity)
        elif cmd=="audit-personal":
            rows=store.db.execute("""SELECT r.source,r.record_id FROM research_refs r JOIN research_sources s ON s.source=r.source
                JOIN research_content c ON c.hash=r.content_hash WHERE r.kind='positions' AND s.role='PERSONAL'
                AND json_extract(c.payload,'$.state')='CLOSED' ORDER BY r.observed_at,r.record_id""").fetchall()
            result={"closed_positions_collected":len(rows),"positions":[position_trace(store,s,i) for s,i in rows],
                    "scope":"Full collected source rows, conditional on completed backfill; no causal loss attribution."}
            if args.output:
                with args.output.open("xb") as output:output.write(canonical(result))
        elif cmd=="train":
            result=train(store,horizon=args.horizon,holdout_start=args.holdout_start,
                         holdout_end=args.holdout_end,untouched=args.attest_untouched)
        elif cmd=="authorize-scorer":
            authorize(store,args.model_id,args.confirm);result=store.get("consolidation_scorer")
        elif cmd=="disable-scorer":
            with store.db:store.set("consolidation_scorer",None)
            result={"status":"SCORER_DISABLED"}
        elif cmd=="size-advice":result=sizing_advice(**json.loads(args.inputs.read_bytes()))
        elif cmd=="prepare-archive":result=prepare_archive(store,args)
        elif cmd=="rehydrate":result=rehydrate(store,args.archive,args.sha256)
        elif cmd=="record-capacity":
            report=json.loads(args.report.read_bytes())
            if report.get("schema")!="staging-capacity/1":raise ValueError("capacity_report_schema")
            result={k:report[k] for k in ("schema","status","required_bytes","available_bytes","shortfall_bytes")}
            with store.db:store.set("consolidation_capacity",result)
        else:result=publish(store)
        if cmd not in {"trace","size-advice","audit-personal","status"}:publish(store)
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__=="__main__":main()
