"""Read-only inventory, reviewed external archive copies and research rehydration."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from psycopg import sql

from autotrader.learning.consolidation import assert_source, now_utc, utc
from autotrader.research.data import canonical, digest

CAP_LOCK = 49100317
ACTIVE_STATES = {"SHADOW_ACTIVE","CREATING"}
DIAGNOSTIC = {"RAOE_EARLY_RECOVERY","A3_COST_AWARE_CONTINUATION","RAOE_TREND_PULLBACK"}
FINANCIAL_TABLES = frozenset(("accounts","balances","financial_journal","orders","fills","positions",
    "capital_reservations","exit_intents","exit_targets","exit_plans","risk_periods","cooldowns","equity_snapshots",
    "ai_budgets","ai_usage","order_transitions","risk_evaluations","portfolio_snapshots","market_marks"))
ARCHIVE_TABLES = {
    "research_sources":("source",4), "research_content":("hash",2),
    "research_refs":("source",11), "research_versions":("source",6), "research_links":("source",3),
    "research_errors":("source",5), "research_tasks":("source",11), "research_postmortems":("task_id",4),
}


def active_cap(value) -> int:
    n=int(value)
    if not 1<=n<=3:
        raise ValueError("shadow_active_cap_must_be_between_one_and_three")
    return n


def require_capacity(records, cap, *, existing=None):
    occupied={r["experiment_id"] for r in records if r["state"] in ACTIVE_STATES and not r.get("archived_at")}
    if existing not in occupied and len(occupied)>=active_cap(cap):
        raise ValueError("active_shadow_cap_reached_pause_existing_experiment_explicitly")
    return len(occupied)


def inventory_row(connection, source):
    assert_source(connection,source)
    accounts=list(connection.execute("SELECT account_id,currency,control FROM public.accounts ORDER BY account_id"))
    expected="shadow:"+source.identity if source.role=="SHADOW" else source.identity
    if len(accounts)!=1 or accounts[0]["account_id"]!=expected:
        raise ValueError("inventory_financial_account_scope_mismatch")
    risk=connection.execute("""SELECT
        (SELECT count(*) FROM public.positions WHERE quantity>0 OR state IN ('OPEN','PENDING')) AS positions,
        (SELECT count(*) FROM public.orders WHERE status IN ('PENDING','ACCEPTED')) AS orders,
        (SELECT count(*) FROM public.exit_intents WHERE status='OPEN') AS intents,
        (SELECT count(*) FROM public.capital_reservations WHERE status='OPEN') AS reservations,
        (SELECT count(*) FROM public.positions WHERE state='CLOSED') AS closed,
        (SELECT count(*) FROM public.positions WHERE state='CLOSED' AND realized_pnl>0) AS wins,
        (SELECT sum(realized_pnl) FROM public.positions WHERE state='CLOSED') AS realized_net_eur,
        pg_database_size(current_database()) AS database_bytes""").fetchone()
    signal=connection.execute("""SELECT count(DISTINCT (symbol,timestamp)) AS market_cycles,
        count(DISTINCT ((timestamp AT TIME ZONE 'UTC')::date)) AS observation_days
        FROM public.strategy_signals""").fetchone()
    quality=connection.execute("""SELECT count(*) FILTER(WHERE execution_json::jsonb->>'rejection_reason'='shadow_frozen_source_changed') AS frozen_source,
        count(*) FILTER(WHERE execution_json::jsonb->>'rejection_reason' LIKE 'risk_rejected:%') AS risk_rejected
        FROM public.orders WHERE status IN ('REJECTED','CANCELLED')""").fetchone()
    lease=connection.execute("SELECT state,payload_json FROM public.system_state WHERE key='coordinator_lease'").fetchone()
    heartbeat=connection.execute("""SELECT updated_at FROM public.system_state
        WHERE key IN ('worker','position_monitor') ORDER BY updated_at DESC LIMIT 1""").fetchone()
    lease_until=json.loads(lease["payload_json"]).get("expires_at") if lease and lease["state"]!="RELEASED" else None
    current=now_utc()
    frozen=None
    if source.role=="SHADOW":
        from autotrader.shadow.versions import compatibility, execution_fingerprint
        runtime=compatibility(source.manifest)
        fingerprint=source.manifest.get("execution_fingerprint")
        frozen={"runner":runtime.get("runner"),"compatible":runtime.get("compatible"),
                "reason":runtime.get("reason"),
                "native_entry_source_matches":fingerprint==execution_fingerprint()
                if fingerprint and runtime.get("runner") not in {"verified-v42","verified-v44"} else None}
    return {"database":source.database,"role":source.role,"identity":source.identity,
            "strategy":source.manifest.get("strategy_id"),"manifest_hash":digest(canonical(source.manifest)),
            "state":source.state,"archived":source.archived,"accounts":accounts,
            **{**risk,"realized_net_eur":str(risk["realized_net_eur"]) if risk["realized_net_eur"] is not None else None},
            **signal, **quality,"observed_at":current,
            "worker_heartbeat":utc(heartbeat["updated_at"]) if heartbeat else None,
            "lease_expires_at":utc(lease_until) if lease_until else None,
            "worker_lease_active":bool(lease_until and utc(lease_until)>current),
            "frozen_runtime_diagnostic":frozen,
            "backup_status":"NOT_CHECKED"}


def flat_stopped(row):
    return (row["role"]=="SHADOW" and row["state"] in {"PAUSED","STOPPED"}
            and row["accounts"][0]["control"] in {"PAUSED","STOPPED"}
            and not row["worker_lease_active"] and all(row[k]==0 for k in ("positions","orders","intents","reservations")))


def archive_plan(rows,cap=3,keep=()):
    cap=active_cap(cap)
    shadow=[r for r in rows if r["role"]=="SHADOW" and not r["archived"]]
    by_id={r["identity"]:r for r in shadow}
    if len(set(keep))!=len(keep) or len(keep)>cap or any(i not in by_id for i in keep):
        raise ValueError("invalid_keep_set")
    picks=list(keep)
    seen={by_id[i]["strategy"] for i in picks}
    ranked=sorted(shadow,key=lambda r:(
        -(2*min(r["closed"],30)+min(r["observation_days"],30)+min(r["market_cycles"]//100,10)
          + 8*(r["strategy"] in DIAGNOSTIC) + min(r["frozen_source"],20)//4
          - 5*(r["worker_lease_active"] and r["state"]=="STOPPED")),r["identity"]))
    if not keep:
        for r in ranked:
            if len(picks)>=cap:break
            if r["strategy"] not in seen:
                picks.append(r["identity"]);seen.add(r["strategy"])
    decisions=[]
    for r in rows:
        if r["role"]!="SHADOW": action="PROTECTED_FINANCIAL"
        elif r["archived"]:action="ARCHIVED_RETAIN_RECOVERY"
        elif r["identity"] in picks:action="DIAGNOSTIC_RESEARCH_CANDIDATE"
        elif not flat_stopped(r):action="KEEP_UNTIL_QUIESCENT_AND_FLAT"
        else:action="VERIFY_EXTERNAL_ARCHIVE_AND_RESTORE"
        decisions.append({**r,"recommendation":action})
    return {"status":"DRY_RUN","maximum_active_shadows":cap,"suggested_active":picks,"records":decisions,
            "active_shadows":sum(r["role"]=="SHADOW" and not r["archived"] and r["state"] in ACTIVE_STATES for r in rows),
            "policy":"Evidence volume, diagnostic coverage and strategy diversity; not a profitability or activation ranking",
            "automatic_actions":[]}


def file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def check_backup(manifest_path: Path, proof_path: Path, source):
    """Verify the staged backup format and its isolated proof by immutable bytes."""
    manifest_path=manifest_path.resolve(strict=True);proof_path=proof_path.resolve(strict=True)
    manifest=json.loads(manifest_path.read_bytes());proof=json.loads(proof_path.read_bytes())
    if (manifest.get("schema")!="aruba-staging-backup/1" or manifest.get("project")!="autotrader-aruba-test"
            or proof.get("backup_manifest_sha256")!=file_sha(manifest_path)
            or proof.get("restore_test") is not True or proof.get("network_internal") is not True
            or proof.get("source_databases_restored") is not False
            or proof.get("restore",{}).get("status")!="PASS"
            or proof["restore"].get("read_only_restore_verification") is not True):
        raise ValueError("isolated_restore_proof_not_bound_to_backup")
    matching=[r for r in manifest["databases"] if r["database"]==source.database]
    if len(matching)!=1:raise ValueError("missing_unique_recovery_dump")
    row=matching[0]
    if (row["account_id"]!="shadow:"+source.identity or row.get("manifest")!=source.manifest
            or row.get("manifest_hash")!=digest(canonical(source.manifest))
            or set(row["financial_seal"])!=FINANCIAL_TABLES):
        raise ValueError("backup_identity_or_financial_seal_mismatch")
    dump=(manifest_path.parent/row["file"]).resolve(strict=True)
    if dump.parent!=manifest_path.parent or dump.stat().st_size!=row["bytes"] or file_sha(dump)!=row["sha256"]:
        raise ValueError("recovery_dump_hash_mismatch")
    restored=[a for a in proof["restore"]["accounts"] if a["account_id"]==row["account_id"]]
    if len(restored)!=1 or restored[0].get("financial_seals")!="MATCH" or restored[0].get("reconciliation")!=[]:
        raise ValueError("isolated_account_restore_missing")
    return {"database":row["database"],"account_id":row["account_id"],"dump":str(dump),"dump_sha256":row["sha256"],
            "manifest_sha256":file_sha(manifest_path),"proof_sha256":file_sha(proof_path),
            "financial_seal":row["financial_seal"]}


def current_seal(connection, tables):
    if set(tables)!=FINANCIAL_TABLES:raise ValueError("financial_seal_scope_mismatch")
    result={}
    for table in sorted(tables):
        query=sql.SQL("SELECT to_jsonb(t)::text AS body FROM public.{} t ORDER BY to_jsonb(t)::text").format(sql.Identifier(table))
        hash_=hashlib.sha256();count=0
        with connection.cursor(name="research_seal") as cursor:
            cursor.execute(query)
            for row in cursor:
                hash_.update(row["body"].encode()+b"\n");count+=1
        result[table]={"rows":count,"sha256":hash_.hexdigest()}
    return result


def archive_copy(store, source, external: Path, recovery, *, confirmation):
    """Called with a fresh read-only flat/seal check under registry advisory lock."""
    if source.role!="SHADOW" or confirmation!=source.identity:
        raise ValueError("exact_shadow_confirmation_required")
    if external.exists() or not external.parent.is_dir() or external.parent.stat().st_dev==store.root.stat().st_dev:
        raise ValueError("new_external_archive_path_on_separate_volume_required")
    if Path(recovery["dump"]).stat().st_dev==store.root.stat().st_dev:
        raise ValueError("financial_dump_must_also_be_on_external_volume")
    if not store.db.execute("SELECT 1 FROM research_sources WHERE source=? AND identity=?",(source.database,source.identity)).fetchone():
        raise ValueError("consolidated_research_source_missing")
    counts={}
    with external.open("xb") as out, gzip.GzipFile(fileobj=out,mode="wb",mtime=0) as stream:
        def write(value): stream.write(canonical(value)+b"\n")
        write({"schema":"portable-research-archive/1","database":source.database,"identity":source.identity,
               "recovery":{k:v for k,v in recovery.items() if k!="dump"}})
        for table,(column,_) in ARCHIVE_TABLES.items():
            if table=="research_content":
                where="hash IN (SELECT content_hash FROM research_versions WHERE source=?)"
            elif table=="research_postmortems":
                where="task_id IN (SELECT id FROM research_tasks WHERE source=?)"
            else:where=f"{column}=?"
            n=0
            for row in store.db.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY {column}",(source.database,)):
                write({"table":table,"row":list(row)});n+=1
            counts[table]=n
        write({"complete":counts})
    result={"status":"EXTERNAL_RESEARCH_COPY_CREATED","archive_sha256":file_sha(external),"counts":counts,
            "database":source.database,"experiment_id":source.identity,
            "financial_recovery":recovery,"financial_database_modified":False,"drop_authorized":False}
    return result


def rehydrate(store, archive: Path, expected_sha: str):
    if file_sha(archive)!=expected_sha:raise ValueError("archive_sha256_mismatch")
    counts={k:0 for k in ARCHIVE_TABLES}
    with gzip.open(archive,"rt",encoding="utf-8") as stream, store.db:
        header=json.loads(next(stream))
        if header.get("schema")!="portable-research-archive/1" or not header["database"].startswith("autotrader_shadow_"):
            raise ValueError("invalid_archive_scope")
        for line in stream:
            entry=json.loads(line)
            if "complete" in entry:
                if entry["complete"]!=counts or next(stream,None) is not None:
                    raise ValueError("archive_completion_mismatch")
                return {"status":"RESEARCH_REHYDRATED","counts":counts,"financial_database_modified":False}
            table,row=entry["table"],entry["row"]
            _,width=ARCHIVE_TABLES[table]
            if len(row)!=width:raise ValueError("archive_row_schema_mismatch")
            source_index=1 if table=="research_tasks" else 0
            if table not in {"research_content","research_postmortems"} and row[source_index]!=header["database"]:
                raise ValueError("archive_source_scope_mismatch")
            if table=="research_sources":
                prior=store.db.execute("SELECT identity,role FROM research_sources WHERE source=?",(row[0],)).fetchone()
                if row[1:3]!=["SHADOW",header["identity"]] or prior and prior!=(row[2],row[1]):
                    raise ValueError("archive_identity_mismatch")
            if table=="research_content" and digest(row[1].encode())!=row[0]:
                raise ValueError("archive_content_hash_mismatch")
            if table=="research_postmortems" and not store.db.execute(
                    "SELECT 1 FROM research_tasks WHERE id=? AND source=?",(row[1],header["database"])).fetchone():
                raise ValueError("archive_postmortem_source_mismatch")
            placeholders=",".join("?" for _ in row)
            store.db.execute(f"INSERT OR IGNORE INTO {table} VALUES ({placeholders})",row)
            counts[table]+=1
        raise ValueError("archive_truncated")
