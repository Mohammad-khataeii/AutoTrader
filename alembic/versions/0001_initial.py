from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("assets", sa.Column("symbol", sa.String(length=24), primary_key=True), sa.Column("name", sa.String(length=128)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("trading_pairs", sa.Column("symbol", sa.String(length=32), primary_key=True), sa.Column("base_asset", sa.String(length=24), sa.ForeignKey("assets.symbol")), sa.Column("quote_asset", sa.String(length=24)), sa.Column("price_step", sa.Numeric(28, 12)), sa.Column("quantity_step", sa.Numeric(28, 12)), sa.Column("min_order_quote", sa.Numeric(28, 12)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("market_candles", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("symbol", sa.String(length=32), index=True), sa.Column("timeframe", sa.String(length=8), index=True), sa.Column("timestamp", sa.DateTime(timezone=True), index=True), sa.Column("open", sa.Numeric(28, 12)), sa.Column("high", sa.Numeric(28, 12)), sa.Column("low", sa.Numeric(28, 12)), sa.Column("close", sa.Numeric(28, 12)), sa.Column("volume", sa.Numeric(28, 12)), sa.Column("source", sa.String(length=64)))
    op.create_table("market_features", sa.Column("feature_id", sa.String(length=64), primary_key=True), sa.Column("symbol", sa.String(length=32), index=True), sa.Column("timestamp", sa.DateTime(timezone=True), index=True), sa.Column("timeframe", sa.String(length=8)), sa.Column("data_quality", sa.String(length=32)), sa.Column("payload_json", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("strategy_signals", sa.Column("signal_id", sa.String(length=64), primary_key=True), sa.Column("strategy_id", sa.String(length=64), index=True), sa.Column("symbol", sa.String(length=32), index=True), sa.Column("timestamp", sa.DateTime(timezone=True), index=True), sa.Column("score", sa.Numeric(12, 8)), sa.Column("data_quality", sa.String(length=32)), sa.Column("payload_json", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("ai_assessments", sa.Column("assessment_id", sa.String(length=64), primary_key=True), sa.Column("symbol", sa.String(length=32), index=True), sa.Column("provider", sa.String(length=32)), sa.Column("model", sa.String(length=128)), sa.Column("failed", sa.Boolean(), default=False), sa.Column("tokens_used", sa.Integer(), default=0), sa.Column("estimated_cost_usd", sa.Numeric(18, 8), default=0), sa.Column("payload_json", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("trading_decisions", sa.Column("decision_id", sa.String(length=64), primary_key=True), sa.Column("symbol", sa.String(length=32), index=True), sa.Column("action", sa.String(length=32)), sa.Column("accepted", sa.Boolean(), default=False), sa.Column("rejected_reason", sa.Text()), sa.Column("payload_json", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("orders", sa.Column("order_id", sa.String(length=64), primary_key=True), sa.Column("decision_id", sa.String(length=64), sa.ForeignKey("trading_decisions.decision_id")), sa.Column("client_order_id", sa.String(length=64), unique=True), sa.Column("symbol", sa.String(length=32), index=True), sa.Column("side", sa.String(length=8)), sa.Column("order_type", sa.String(length=16)), sa.Column("status", sa.String(length=32), index=True), sa.Column("quantity", sa.Numeric(28, 12)), sa.Column("quote_amount", sa.Numeric(28, 12)), sa.Column("simulated", sa.Boolean(), default=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("fills", sa.Column("fill_id", sa.String(length=64), primary_key=True), sa.Column("order_id", sa.String(length=64), sa.ForeignKey("orders.order_id"), index=True), sa.Column("symbol", sa.String(length=32), index=True), sa.Column("side", sa.String(length=8)), sa.Column("quantity", sa.Numeric(28, 12)), sa.Column("price", sa.Numeric(28, 12)), sa.Column("fee", sa.Numeric(28, 12)), sa.Column("simulated", sa.Boolean(), default=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_table("system_events", sa.Column("event_id", sa.String(length=64), primary_key=True), sa.Column("severity", sa.String(length=16), index=True), sa.Column("message", sa.Text()), sa.Column("payload_json", sa.Text(), default="{}"), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))


def downgrade() -> None:
    for table in ["system_events", "fills", "orders", "trading_decisions", "ai_assessments", "strategy_signals", "market_features", "market_candles", "trading_pairs", "assets"]:
        op.drop_table(table)

