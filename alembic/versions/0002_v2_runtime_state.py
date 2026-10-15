from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_v2_runtime_state"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("filled_quantity", sa.Numeric(28, 12), nullable=True, server_default="0"))
    op.add_column("orders", sa.Column("average_fill_price", sa.Numeric(28, 12), nullable=True))

    op.create_table(
        "news_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("symbol", sa.String(length=32), index=True),
        sa.Column("source", sa.String(length=64)),
        sa.Column("timestamp", sa.DateTime(timezone=True), index=True),
        sa.Column("title", sa.Text()),
        sa.Column("payload_json", sa.Text(), default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "risk_evaluations",
        sa.Column("evaluation_id", sa.String(length=64), primary_key=True),
        sa.Column("decision_id", sa.String(length=64), sa.ForeignKey("trading_decisions.decision_id")),
        sa.Column("accepted", sa.Boolean(), default=False),
        sa.Column("reserved_quote", sa.Numeric(28, 12), default=0),
        sa.Column("payload_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "order_transitions",
        sa.Column("transition_id", sa.String(length=64), primary_key=True),
        sa.Column("order_id", sa.String(length=64), sa.ForeignKey("orders.order_id"), index=True),
        sa.Column("from_status", sa.String(length=32)),
        sa.Column("to_status", sa.String(length=32), index=True),
        sa.Column("reason", sa.Text()),
        sa.Column("payload_json", sa.Text(), default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "balances",
        sa.Column("asset", sa.String(length=24), primary_key=True),
        sa.Column("available", sa.Numeric(28, 12), default=0),
        sa.Column("reserved", sa.Numeric(28, 12), default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "capital_reservations",
        sa.Column("reservation_id", sa.String(length=64), primary_key=True),
        sa.Column("order_id", sa.String(length=64), sa.ForeignKey("orders.order_id"), index=True),
        sa.Column("asset", sa.String(length=24), default="EUR"),
        sa.Column("amount", sa.Numeric(28, 12)),
        sa.Column("status", sa.String(length=32), index=True),
        sa.Column("idempotency_key", sa.String(length=128), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "positions",
        sa.Column("position_id", sa.String(length=64), primary_key=True),
        sa.Column("symbol", sa.String(length=32), unique=True, index=True),
        sa.Column("quantity", sa.Numeric(28, 12)),
        sa.Column("average_entry_price", sa.Numeric(28, 12)),
        sa.Column("realized_pnl", sa.Numeric(28, 12), default=0),
        sa.Column("protective_stop", sa.Numeric(28, 12)),
        sa.Column("target_1", sa.Numeric(28, 12)),
        sa.Column("target_2", sa.Numeric(28, 12)),
        sa.Column("target_3", sa.Numeric(28, 12)),
        sa.Column("state", sa.String(length=32), index=True, default="OPEN"),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "portfolio_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), primary_key=True),
        sa.Column("available_cash", sa.Numeric(28, 12)),
        sa.Column("reserved_cash", sa.Numeric(28, 12)),
        sa.Column("open_exposure", sa.Numeric(28, 12)),
        sa.Column("realized_pnl", sa.Numeric(28, 12), default=0),
        sa.Column("payload_json", sa.Text(), default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "strategy_versions",
        sa.Column("version_id", sa.String(length=64), primary_key=True),
        sa.Column("strategy_id", sa.String(length=64), index=True),
        sa.Column("version", sa.String(length=32)),
        sa.Column("active", sa.Boolean(), default=False),
        sa.Column("payload_json", sa.Text(), default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("strategy_id", "version", name="uq_strategy_version"),
    )
    op.create_table(
        "backtest_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("strategy_id", sa.String(length=64), index=True),
        sa.Column("symbol", sa.String(length=32), index=True),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("payload_json", sa.Text(), default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "system_incidents",
        sa.Column("incident_id", sa.String(length=64), primary_key=True),
        sa.Column("severity", sa.String(length=16), index=True),
        sa.Column("status", sa.String(length=32), index=True),
        sa.Column("message", sa.Text()),
        sa.Column("payload_json", sa.Text(), default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in [
        "system_incidents",
        "backtest_runs",
        "strategy_versions",
        "portfolio_snapshots",
        "positions",
        "capital_reservations",
        "balances",
        "order_transitions",
        "risk_evaluations",
        "news_events",
    ]:
        op.drop_table(table)
    op.drop_column("orders", "average_fill_price")
    op.drop_column("orders", "filled_quantity")

