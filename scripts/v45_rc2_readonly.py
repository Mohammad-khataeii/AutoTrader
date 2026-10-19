"""SELECT-only production inventory; pipe to backend Python stdin, no remote files."""
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from autotrader.config import Settings
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.research.data import canonical, digest
from autotrader.shadow.versions import execution_fingerprint

TABLES = ("accounts", "balances", "financial_journal", "orders", "fills", "positions",
          "capital_reservations", "exit_intents", "exit_targets", "exit_plans",
          "risk_periods", "cooldowns", "equity_snapshots", "ai_budgets", "ai_usage",
          "order_transitions", "risk_evaluations", "portfolio_snapshots", "market_marks")


async def main():
    settings = Settings()
    url = make_url(settings.database_url)
    result = {"evidence_class": "REAL_PRODUCTION_READ_ONLY_OBSERVATION",
              "captured_at": datetime.now(UTC).isoformat(), "read_only": True,
              "live_trading_enabled": settings.live_trading_enabled,
              "execution_fingerprint": execution_fingerprint(), "accounts": [],
              "operational_execution_settings": {key: str(getattr(settings, key)) for key in (
                  "allocation_profile", "default_fee_bps", "default_slippage_bps", "max_allocated_capital_eur",
                  "max_total_open_exposure_eur", "min_uncommitted_reserve_eur", "max_position_size_eur",
                  "max_simultaneous_positions", "max_planned_loss_per_trade_eur", "daily_loss_threshold_eur",
                  "weekly_loss_threshold_eur", "max_new_entries_per_day", "market_data_max_staleness_seconds")}}
    def connect(database):
        return psycopg.connect(url.set(database=database, drivername="postgresql").render_as_string(hide_password=False),
            row_factory=dict_row, options="-c default_transaction_read_only=on -c statement_timeout=30000")
    with connect(url.database) as conn:
        records = conn.execute("SELECT experiment_id,state,database_name,manifest_json FROM shadow_experiments ORDER BY experiment_id").fetchall()
        archives = {r["key"].removeprefix("shadow_archive:"): json.loads(r["payload_json"])
                    for r in conn.execute("SELECT key,payload_json FROM system_state WHERE key LIKE 'shadow_archive:%'")}
    for record in [{"experiment_id": "official", "database_name": url.database, "state": "OFFICIAL"}, *records]:
        database = record["database_name"]
        identity = record["experiment_id"]
        manifest = json.loads(record["manifest_json"]) if "manifest_json" in record else None
        data = {"identity": identity, "state": record["state"], "database_name": database,
                "manifest": manifest, "manifest_hash": digest(canonical(manifest)) if manifest else None,
                "archive": archives.get(identity), "financial_seal": {}}
        with connect(database) as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            data["schema"] = conn.execute("SELECT version_num FROM alembic_version").fetchone()["version_num"]
            for table in TABLES:
                # Stable row ordering, streaming hash; no journal payloads or secrets exported.
                rows = conn.execute("SELECT to_jsonb(t)::text AS row FROM " + table + " t ORDER BY to_jsonb(t)::text")
                sha, count = hashlib.sha256(), 0
                for row in rows:
                    sha.update(row["row"].encode() + b"\n")
                    count += 1
                data["financial_seal"][table] = {"rows": count, "sha256": sha.hexdigest()}
            data["decision_summary"] = conn.execute("SELECT action,accepted,count(*) AS count FROM trading_decisions GROUP BY action,accepted ORDER BY action,accepted").fetchall()
            data["order_refusals"] = conn.execute("SELECT side,status,execution_json::jsonb->>'rejection_reason' AS rejection_reason,count(*) AS count FROM orders GROUP BY side,status,execution_json::jsonb->>'rejection_reason' ORDER BY side,status,rejection_reason").fetchall()
            data["recent_orders"] = conn.execute("SELECT o.order_id,o.decision_id,o.symbol,o.side,o.status,o.quantity,o.quote_amount,o.execution_json::jsonb->>'rejection_reason' AS rejection_reason,o.execution_json,d.payload_json AS decision_payload,o.created_at FROM orders o LEFT JOIN trading_decisions d ON d.decision_id=o.decision_id ORDER BY o.created_at DESC LIMIT 50").fetchall()
            data["latest_accepted_buys"] = conn.execute("SELECT decision_id,symbol,created_at FROM trading_decisions WHERE accepted AND action='BUY' ORDER BY created_at DESC LIMIT 20").fetchall()
            data["balances"] = conn.execute("SELECT asset,available,reserved FROM balances ORDER BY asset").fetchall()
            data["open_positions"] = conn.execute("SELECT position_id,symbol,quantity,protective_stop FROM positions WHERE quantity>0 ORDER BY position_id").fetchall()
            data["open_orders"] = conn.execute("SELECT order_id,symbol,status FROM orders WHERE status IN ('PENDING','ACCEPTED') ORDER BY order_id").fetchall()
            data["funding"] = conn.execute("SELECT event_key,cash_delta FROM financial_journal WHERE event_type='INITIAL_FUNDING' ORDER BY event_key").fetchall()
            if manifest:
                marker = conn.execute("SELECT manifest_json,manifest_hash FROM shadow_identity WHERE singleton=1").fetchone()
                data["identity_matches"] = marker["manifest_hash"] == data["manifest_hash"] and json.loads(marker["manifest_json"]) == manifest
            data["health_states"] = conn.execute("SELECT key,state,reason,payload_json,updated_at FROM system_state WHERE key IN ('worker','scanner','runtime_health','shadow_reconciliation') OR key LIKE 'market_data:%' ORDER BY key").fetchall()
        engine = create_async_engine(url.set(database=database).render_as_string(hide_password=False), isolation_level="REPEATABLE READ",
            connect_args={"server_settings": {"default_transaction_read_only": "on", "statement_timeout": "30000"}})
        try:
            repo = PersistentTradingRepository(async_sessionmaker(engine, expire_on_commit=False))
            repo.account_id = "paper-eur" if identity == "official" else "shadow:" + identity
            async with repo.session_factory() as session:
                data["reconciliation"] = await repo._verify(session, Decimal(500))
            if identity == "official":
                result["market_data_health"] = await repo.market_data_health()
        finally:
            await engine.dispose()
        result["accounts"].append(data)
    root = Path(__import__('autotrader').__file__).parent
    result["source_hashes"] = {str(p.relative_to(root)): digest(p.read_bytes())
                              for p in sorted(root.rglob('*.py')) if '_frozen' not in p.parts}
    print(json.dumps(result, default=str))


asyncio.run(main())
