"""Explicit financial identity, immutable journal, durable risk and AI reservations.

Legacy accounting is preserved and quarantined, never reconstructed from symbols.
"""
from __future__ import annotations

import json
import os

import sqlalchemy as sa
from alembic import op

revision = "0006_v34_accounting"
down_revision = "0005_v3_3_ledger"
branch_labels = None
depends_on = None


def ident(name: str, reference: str | None = None, **kw: object) -> sa.Column:
    args = [sa.ForeignKey(reference)] if reference else []
    return sa.Column(name, sa.String(64), *args, **kw)


def money(name: str, **kw: object) -> sa.Column:
    return sa.Column(name, sa.Numeric(28, 12), **kw)


def created() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.add_column("market_candles", sa.Column("observation_key", sa.String(128), nullable=True))
    op.create_index("uq_market_candle_observation", "market_candles", ["observation_key"], unique=True)
    op.create_table("accounts", ident("account_id", primary_key=True), sa.Column("currency", sa.String(8), nullable=False), money("initial_cash", nullable=False), sa.Column("control", sa.String(32), nullable=False), created())
    op.add_column("positions", ident("account_id", nullable=True))
    op.add_column("positions", money("cost_basis", nullable=False, server_default="0"))
    for field in ("highest_price", "initial_stop", "trailing_distance"):
        op.add_column("positions", money(field, nullable=True))
    for field in ("expires_at", "last_monitored_at"):
        op.add_column("positions", sa.Column(field, sa.DateTime(timezone=True)))
    with op.batch_alter_table("positions") as batch:
        batch.create_foreign_key("fk_position_account", "accounts", ["account_id"], ["account_id"])
    op.create_index("ix_positions_account_id", "positions", ["account_id"])
    op.create_table("exit_plans", ident("exit_plan_id", primary_key=True), ident("position_id", "positions.position_id", nullable=False, unique=True), sa.Column("strategy_id", sa.String(64), nullable=False), sa.Column("settings_json", sa.Text(), nullable=False), created())
    op.create_table("exit_targets", ident("target_id", primary_key=True), ident("position_id", "positions.position_id", nullable=False, index=True), ident("exit_plan_id", "exit_plans.exit_plan_id", nullable=False, index=True), sa.Column("target_number", sa.Integer(), nullable=False), money("target_price", nullable=False), money("original_planned_quantity", nullable=False), money("filled_quantity", nullable=False), money("reserved_quantity", nullable=False), money("remaining_quantity", nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), created(), sa.UniqueConstraint("exit_plan_id", "target_number", name="uq_exit_plan_target"), sa.CheckConstraint("filled_quantity >= 0 AND reserved_quantity >= 0 AND remaining_quantity >= 0", name="ck_target_nonnegative"), sa.CheckConstraint("filled_quantity + reserved_quantity <= original_planned_quantity", name="ck_target_allocation"))
    op.create_table("exit_intents", ident("exit_intent_id", primary_key=True), ident("position_id", "positions.position_id", nullable=False, index=True), ident("exit_plan_id", "exit_plans.exit_plan_id"), ident("exit_target_id", "exit_targets.target_id", index=True), sa.Column("reason", sa.String(64), nullable=False), money("quantity", nullable=False), money("reserved_quantity", nullable=False), sa.Column("status", sa.String(32), nullable=False, index=True), sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True), created())
    for table in ("orders", "fills"):
        op.add_column(table, ident("account_id", nullable=True))
        op.add_column(table, ident("exit_intent_id", nullable=True))
        op.add_column(table, ident("exit_target_id", nullable=True))
        if table == "orders":
            op.add_column(table, ident("position_id", nullable=True))
            op.add_column(table, sa.Column("execution_json", sa.Text(), nullable=False, server_default="{}"))
        else:
            op.add_column(table, sa.Column("attribution_status", sa.String(32), nullable=False, server_default="UNRESOLVED"))
        with op.batch_alter_table(table) as batch:
            for column, target in (("account_id", "accounts.account_id"), ("position_id", "positions.position_id"), ("exit_intent_id", "exit_intents.exit_intent_id"), ("exit_target_id", "exit_targets.target_id")):
                target_table, target_col = target.split(".")
                batch.create_foreign_key(f"fk_{table}_{column}", target_table, [column], [target_col])
            if table == "orders":
                batch.create_unique_constraint("uq_order_exit_intent", ["exit_intent_id"])
        for column in ("account_id", "exit_target_id"):
            op.create_index(f"ix_{table}_{column}", table, [column])
        op.create_index(f"ix_{table}_{'position_id' if table == 'orders' else 'exit_intent_id'}", table, ["position_id" if table == "orders" else "exit_intent_id"])
    op.create_table("financial_journal", ident("ledger_event_id", primary_key=True), sa.Column("event_key", sa.String(160), nullable=False, unique=True), ident("account_id", "accounts.account_id", nullable=False, index=True), sa.Column("currency", sa.String(8), nullable=False), sa.Column("event_type", sa.String(32), nullable=False, index=True), ident("position_id", "positions.position_id", index=True), ident("order_id", "orders.order_id", index=True), ident("fill_id", "fills.fill_id", index=True), *[money(field, nullable=False) for field in ("cash_delta", "reserved_delta", "quantity_delta", "cost_basis_delta", "realized_pnl_delta")], sa.Column("reconciliation_state", sa.String(32), nullable=False), sa.Column("payload_json", sa.Text(), nullable=False), created())
    op.create_table("market_marks", sa.Column("symbol", sa.String(32), primary_key=True), money("price", nullable=False), sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("source", sa.String(64), nullable=False))
    op.create_table("equity_snapshots", ident("snapshot_id", primary_key=True), ident("account_id", "accounts.account_id", nullable=False, index=True), money("equity", nullable=False), sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True), sa.Column("degraded", sa.Boolean(), nullable=False), created())
    op.create_table("risk_periods", ident("period_id", primary_key=True), ident("account_id", "accounts.account_id", nullable=False), money("start_equity", nullable=False))
    op.create_table("cooldowns", sa.Column("symbol", sa.String(32), primary_key=True), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("strategy_id", sa.String(64), nullable=False))
    op.create_table("ai_budgets", sa.Column("month", sa.String(7), primary_key=True), sa.Column("spent", sa.Numeric(18, 8), nullable=False), sa.Column("reserved", sa.Numeric(18, 8), nullable=False))
    op.create_table("ai_usage", ident("request_id", primary_key=True), sa.Column("month", sa.String(7), sa.ForeignKey("ai_budgets.month"), nullable=False, index=True), sa.Column("model", sa.String(128), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("reserved_cost", sa.Numeric(18, 8), nullable=False), sa.Column("actual_cost", sa.Numeric(18, 8)), sa.Column("input_tokens", sa.Integer(), nullable=False), sa.Column("output_tokens", sa.Integer(), nullable=False), sa.Column("error", sa.Text()), created())
    op.create_table("legacy_attribution_report", ident("fill_id", "fills.fill_id", primary_key=True), ident("previous_position_id"), sa.Column("reason", sa.Text(), nullable=False), created())
    conn = op.get_bind()
    if os.getenv("ENVIRONMENT") == "test" and os.getenv("AUTOTRADER_MIGRATION_FAILPOINT") == "after_ddl":
        raise RuntimeError("Injected migration failure after DDL; PostgreSQL must roll back.")
    rows = conn.execute(sa.text("SELECT fill_id, position_id FROM fills")).mappings().all()
    for row in rows:
        conn.execute(sa.text("INSERT INTO legacy_attribution_report(fill_id, previous_position_id, reason) VALUES (:fill_id, :position_id, :reason)"), {**row, "reason": "Legacy position and target attribution unproven; explicit audited remediation required"})
    if rows or conn.scalar(sa.text("SELECT COUNT(*) FROM balances")):
        conn.execute(sa.text("DELETE FROM system_state WHERE key = 'runtime_health'"))
        conn.execute(sa.text("INSERT INTO system_state(key,state,reason,payload_json) VALUES ('runtime_health','RECONCILIATION_REQUIRED','legacy_accounting_requires_remediation',:payload)"), {"payload": json.dumps({"unresolved_fills": len(rows)})})
    # Prevent UPDATE/DELETE through SQL as well as through application code.
    if conn.dialect.name == "postgresql":
        op.execute("CREATE FUNCTION reject_financial_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable financial history'; END; $$")
        for table in ("financial_journal", "fills"):
            op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_financial_mutation()")
    else:
        for table in ("financial_journal", "fills"):
            for operation in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER immutable_{table}_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable financial history'); END")


def downgrade() -> None:
    raise RuntimeError("Accounting migration is forward-only. Restore a verified backup to roll back without deleting financial history.")
