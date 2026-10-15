from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AuditMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Asset(Base, AuditMixin):
    __tablename__ = "assets"
    symbol: Mapped[str] = mapped_column(String(24), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))


class TradingPairModel(Base, AuditMixin):
    __tablename__ = "trading_pairs"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    base_asset: Mapped[str] = mapped_column(String(24), ForeignKey("assets.symbol"))
    quote_asset: Mapped[str] = mapped_column(String(24))
    price_step: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    quantity_step: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    min_order_quote: Mapped[Decimal] = mapped_column(Numeric(28, 12))


class MarketCandle(Base):
    __tablename__ = "market_candles"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    observation_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    high: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    low: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    close: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    volume: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    source: Mapped[str] = mapped_column(String(64))


class MarketFeature(Base, AuditMixin):
    __tablename__ = "market_features"
    feature_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    data_quality: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text)


class StrategySignalModel(Base, AuditMixin):
    __tablename__ = "strategy_signals"
    signal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    score: Mapped[Decimal] = mapped_column(Numeric(12, 8))
    data_quality: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text)


class AIAssessmentModel(Base, AuditMixin):
    __tablename__ = "ai_assessments"
    assessment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    failed: Mapped[bool] = mapped_column(Boolean, default=False)
    tokens_used: Mapped[int] = mapped_column(default=0)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=0)
    payload_json: Mapped[str] = mapped_column(Text)


class TradingDecisionModel(Base, AuditMixin):
    __tablename__ = "trading_decisions"
    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(32))
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text)
    orders: Mapped[list[OrderModel]] = relationship(back_populates="decision")


class OrderModel(Base, AuditMixin):
    __tablename__ = "orders"
    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str | None] = mapped_column(ForeignKey("trading_decisions.decision_id"))
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    quote_amount: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    filled_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    average_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    position_id: Mapped[str | None] = mapped_column(ForeignKey("positions.position_id"), index=True)
    exit_intent_id: Mapped[str | None] = mapped_column(ForeignKey("exit_intents.exit_intent_id"), unique=True)
    exit_target_id: Mapped[str | None] = mapped_column(ForeignKey("exit_targets.target_id"), index=True)
    execution_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    decision: Mapped[TradingDecisionModel | None] = relationship(back_populates="orders")


class FillModel(Base, AuditMixin):
    __tablename__ = "fills"
    fill_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), index=True)
    position_id: Mapped[str | None] = mapped_column(ForeignKey("positions.position_id"), index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    exit_intent_id: Mapped[str | None] = mapped_column(ForeignKey("exit_intents.exit_intent_id"), index=True)
    exit_target_id: Mapped[str | None] = mapped_column(ForeignKey("exit_targets.target_id"), index=True)
    attribution_status: Mapped[str] = mapped_column(String(32), default="CONFIRMED", server_default="UNRESOLVED")
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    price: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    fee: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)


class SystemEvent(Base, AuditMixin):
    __tablename__ = "system_events"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    message: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class NewsEvent(Base, AuditMixin):
    __tablename__ = "news_events"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    title: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class RiskEvaluationModel(Base, AuditMixin):
    __tablename__ = "risk_evaluations"
    evaluation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str | None] = mapped_column(ForeignKey("trading_decisions.decision_id"))
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    reserved_quote: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    payload_json: Mapped[str] = mapped_column(Text)


class OrderTransitionModel(Base, AuditMixin):
    __tablename__ = "order_transitions"
    transition_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class BalanceModel(Base, AuditMixin):
    __tablename__ = "balances"
    asset: Mapped[str] = mapped_column(String(24), primary_key=True)
    available: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    reserved: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)


class CapitalReservationModel(Base, AuditMixin):
    __tablename__ = "capital_reservations"
    reservation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.order_id"), index=True)
    asset: Mapped[str] = mapped_column(String(24), default="EUR")
    amount: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    status: Mapped[str] = mapped_column(String(32), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)


class PositionModel(Base, AuditMixin):
    __tablename__ = "positions"
    position_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    cost_basis: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0, server_default="0")
    highest_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    initial_stop: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    trailing_distance: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_monitored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    original_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    average_entry_price: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    protective_stop: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    target_1: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    target_2: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    target_3: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    target_1_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    target_2_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    target_3_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    target_1_filled_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    target_2_filled_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    target_3_filled_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    state: Mapped[str] = mapped_column(String(32), index=True, default="OPEN")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PortfolioSnapshotModel(Base, AuditMixin):
    __tablename__ = "portfolio_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    available_cash: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    reserved_cash: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    open_exposure: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class StrategyVersionModel(Base, AuditMixin):
    __tablename__ = "strategy_versions"
    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    __table_args__ = (UniqueConstraint("strategy_id", "version", name="uq_strategy_version"),)


class BacktestRunModel(Base, AuditMixin):
    __tablename__ = "backtest_runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class SystemIncidentModel(Base, AuditMixin):
    __tablename__ = "system_incidents"
    incident_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class SystemStateModel(Base, AuditMixin):
    __tablename__ = "system_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AccountModel(Base, AuditMixin):
    __tablename__ = "accounts"
    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    currency: Mapped[str] = mapped_column(String(8))
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    control: Mapped[str] = mapped_column(String(32), default="RUNNING")


class ExitPlanModel(Base, AuditMixin):
    __tablename__ = "exit_plans"
    exit_plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position_id: Mapped[str] = mapped_column(ForeignKey("positions.position_id"), unique=True)
    strategy_id: Mapped[str] = mapped_column(String(64), default="ensemble-v3.4")
    settings_json: Mapped[str] = mapped_column(Text, default="{}")


class ExitTargetModel(Base, AuditMixin):
    __tablename__ = "exit_targets"
    target_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position_id: Mapped[str] = mapped_column(ForeignKey("positions.position_id"), index=True)
    exit_plan_id: Mapped[str] = mapped_column(ForeignKey("exit_plans.exit_plan_id"), index=True)
    target_number: Mapped[int] = mapped_column()
    target_price: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    original_planned_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    filled_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    reserved_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("exit_plan_id", "target_number", name="uq_exit_plan_target"),
        CheckConstraint("filled_quantity >= 0 AND reserved_quantity >= 0 AND remaining_quantity >= 0", name="ck_target_nonnegative"),
        CheckConstraint("filled_quantity + reserved_quantity <= original_planned_quantity", name="ck_target_allocation"),
    )


class ExitIntentModel(Base, AuditMixin):
    __tablename__ = "exit_intents"
    exit_intent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position_id: Mapped[str] = mapped_column(ForeignKey("positions.position_id"), index=True)
    exit_plan_id: Mapped[str | None] = mapped_column(ForeignKey("exit_plans.exit_plan_id"))
    exit_target_id: Mapped[str | None] = mapped_column(ForeignKey("exit_targets.target_id"), index=True)
    reason: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    reserved_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    status: Mapped[str] = mapped_column(String(32), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)


class JournalEventModel(Base, AuditMixin):
    __tablename__ = "financial_journal"
    ledger_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_key: Mapped[str] = mapped_column(String(160), unique=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    currency: Mapped[str] = mapped_column(String(8))
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    position_id: Mapped[str | None] = mapped_column(ForeignKey("positions.position_id"), index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.order_id"), index=True)
    fill_id: Mapped[str | None] = mapped_column(ForeignKey("fills.fill_id"), index=True)
    cash_delta: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    reserved_delta: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    cost_basis_delta: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    realized_pnl_delta: Mapped[Decimal] = mapped_column(Numeric(28, 12), default=0)
    reconciliation_state: Mapped[str] = mapped_column(String(32), default="CONFIRMED")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class MarketMarkModel(Base):
    __tablename__ = "market_marks"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(64))


class EquitySnapshotModel(Base, AuditMixin):
    __tablename__ = "equity_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    equity: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    degraded: Mapped[bool] = mapped_column(Boolean)


class RiskPeriodModel(Base):
    __tablename__ = "risk_periods"
    period_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    start_equity: Mapped[Decimal] = mapped_column(Numeric(28, 12))


class CooldownModel(Base):
    __tablename__ = "cooldowns"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    strategy_id: Mapped[str] = mapped_column(String(64))


class AIBudgetModel(Base):
    __tablename__ = "ai_budgets"
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    spent: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=0)
    reserved: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=0)


class AIUsageModel(Base, AuditMixin):
    __tablename__ = "ai_usage"
    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    month: Mapped[str] = mapped_column(ForeignKey("ai_budgets.month"), index=True)
    model: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    reserved_cost: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(32), default="openai")
    candidate_symbol: Mapped[str] = mapped_column(String(32))
    cached_input_tokens: Mapped[int] = mapped_column(default=0)
    cache_write_tokens: Mapped[int] = mapped_column(default=0)
    pricing_json: Mapped[str] = mapped_column(Text)
