"""Candidate/rollback image proof against an entire isolated restored cluster.

No initialization, migration, worker, scanner or funding method is called.
Database-enforced read-only sessions also reject accidental writes.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.shadow.versions import compatibility

TABLES = ("accounts", "balances", "financial_journal", "orders", "fills", "positions",
          "capital_reservations", "exit_intents", "exit_targets", "exit_plans",
          "risk_periods", "cooldowns", "equity_snapshots", "ai_budgets", "ai_usage",
          "order_transitions", "risk_evaluations", "portfolio_snapshots", "market_marks")


async def verify() -> dict:
    url = make_url(os.environ["DATABASE_URL"])
    if (os.environ.get("AUTOTRADER_ISOLATED_RESTORE") != "1"
        or url.host != "restore-postgres" or url.database != "autotrader"
        or os.environ.get("LIVE_TRADING_ENABLED") != "false"):
        raise ValueError("isolated_cluster_required_production_targets_refused")
    metadata = json.loads(Path("/backup-set.json").read_text())
    results = []
    for record in metadata["databases"]:
        engine = create_async_engine(url.set(database=record["database"]),
            connect_args={"server_settings": {"default_transaction_read_only": "on"}},
            isolation_level="REPEATABLE READ")
        try:
            async with engine.connect() as connection, connection.begin():
                factory = async_sessionmaker(bind=connection, expire_on_commit=False)
                repo = PersistentTradingRepository(factory)
                repo.account_id = record["account_id"]
                async def seal():
                    result = {}
                    for table in TABLES:
                        rows = await connection.execute(text("SELECT to_jsonb(t)::text FROM " + table + " t ORDER BY to_jsonb(t)::text"))
                        sha, count = hashlib.sha256(), 0
                        for row in rows:
                            sha.update(row[0].encode() + b"\n")
                            count += 1
                        result[table] = {"rows": count, "sha256": sha.hexdigest()}
                    return result
                before = await seal()
                if record.get("financial_seal") and before != record["financial_seal"]:
                    raise ValueError("restored_financial_seal_differs_from_backup")
                accounts = list((await connection.execute(text("SELECT account_id FROM accounts"))).scalars())
                if accounts != [record["account_id"]]:
                    raise ValueError("restored_account_identity_mismatch")
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                if revision != "0011_v42_shadow_isolation":
                    raise ValueError("candidate_requires_schema_change")
                funding = (await connection.execute(text("SELECT count(*),sum(cash_delta) FROM financial_journal WHERE event_type='INITIAL_FUNDING'"))).one()
                if funding != (1, Decimal(500)):
                    raise ValueError("missing_or_duplicate_funding")
                runtime = None
                if record["manifest"]:
                    marker = (await connection.execute(text("SELECT manifest_json,manifest_hash FROM shadow_identity WHERE singleton=1"))).one()
                    if json.loads(marker[0]) != record["manifest"] or marker[1] != record["manifest_hash"]:
                        raise ValueError("restored_immutable_manifest_changed")
                    runtime = compatibility(record["manifest"])
                    if not runtime["compatible"]:
                        raise ValueError("restored_runtime_incompatible:" + record["account_id"])
                else:
                    registry = (await connection.execute(text("SELECT experiment_id,database_name,state,manifest_json FROM shadow_experiments ORDER BY experiment_id"))).all()
                    expected = sorted([r for r in metadata["databases"] if r["manifest"]], key=lambda r: r["manifest"]["experiment_id"])
                    if [(r[0], r[1], r[2], json.loads(r[3])) for r in registry] != [(r["manifest"]["experiment_id"], r["database"], r["state"], r["manifest"]) for r in expected]:
                        raise ValueError("restored_registry_incomplete_or_changed")
                    for child in expected:
                        archive = await connection.scalar(text("SELECT payload_json FROM system_state WHERE key=:key"), {"key": "shadow_archive:" + child["manifest"]["experiment_id"]})
                        if (json.loads(archive) if archive else None) != child.get("archive"):
                            raise ValueError("archive_marker_changed")
                async with factory() as session:
                    reconciliation = await repo._verify(session, Decimal(500))
                if reconciliation or await seal() != before:
                    raise ValueError("restored_reconciliation_or_immutability_failed")
                results.append({"account_id": record["account_id"], "database": record["database"],
                    "manifest_hash": record.get("manifest_hash"), "runtime": runtime,
                    "schema": revision, "funding_count": funding[0], "financial_seal": before,
                    "reconciliation": reconciliation, "financial_history_unchanged": True})
        finally:
            await engine.dispose()
    return {"status": "PASS", "accounts": results, "database_count": len(results),
            "schema_migration": False, "worker_started": False, "funding_created": False,
            "production_route": False, "server_enforced_read_only": True}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(verify())))
