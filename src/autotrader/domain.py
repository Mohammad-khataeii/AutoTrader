from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def quantize_down(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class DecisionAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    WAIT = "WAIT"
    REDUCE = "REDUCE"
    CANCEL_PENDING_ENTRY = "CANCEL_PENDING_ENTRY"


class DataQuality(StrEnum):
    GOOD = "GOOD"
    STALE = "STALE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    INVALID = "INVALID"


class RuntimeHealth(StrEnum):
    HEALTHY = "HEALTHY"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    RISK_HALTED = "RISK_HALTED"
    RECOVERING = "RECOVERING"


@dataclass(frozen=True)
class TradingPair:
    symbol: str
    base_asset: str
    quote_asset: str
    price_step: Decimal = Decimal("0.01")
    quantity_step: Decimal = Decimal("0.00000001")
    min_order_quote: Decimal = Decimal("5")
    min_order_base: Decimal = Decimal("0")
    max_order_base: Decimal | None = None
    status: str = "active"


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not self.currency:
            raise ValueError("Money currency is required.")

    def require_currency(self, currency: str) -> None:
        if self.currency != currency:
            raise ValueError(f"Currency mismatch: {self.currency} cannot be used as {currency}.")


@dataclass(frozen=True)
class Candle:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    timeframe: str = "1m"
    source: str = "unknown"


@dataclass(frozen=True)
class OrderBookLevel:
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class OrderBook:
    symbol: str
    timestamp: datetime
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    source: str

    @property
    def best_bid(self) -> Decimal | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    @property
    def mid(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / Decimal("2")


@dataclass(frozen=True)
class MarketFeatures:
    symbol: str
    timestamp: datetime
    timeframe: str
    data_quality: DataQuality
    metadata: dict[str, Any]
    rsi: Decimal | None = None
    macd: Decimal | None = None
    macd_signal: Decimal | None = None
    ema_9: Decimal | None = None
    ema_21: Decimal | None = None
    ema_50: Decimal | None = None
    ema_200: Decimal | None = None
    atr: Decimal | None = None
    bollinger_upper: Decimal | None = None
    bollinger_mid: Decimal | None = None
    bollinger_lower: Decimal | None = None
    vwap: Decimal | None = None
    adx: Decimal | None = None
    relative_volume: Decimal | None = None
    momentum: Decimal | None = None
    volatility: Decimal | None = None
    support: Decimal | None = None
    resistance: Decimal | None = None
    order_book_imbalance: Decimal | None = None
    spread_bps: Decimal | None = None
    breakout_distance: Decimal | None = None
    volume_acceleration: Decimal | None = None


@dataclass(frozen=True)
class StrategySignal:
    signal_id: str
    strategy_id: str
    symbol: str
    timestamp: datetime
    score: Decimal
    data_quality: DataQuality
    evidence: dict[str, Any]
    entry_conditions: list[str]
    invalidation_conditions: list[str]
    estimated_cost_bps: Decimal
    explanation: str


@dataclass(frozen=True)
class AIAssessment:
    assessment_id: str
    symbol: str
    timestamp: datetime
    provider: str
    model: str
    suggested_action: DecisionAction
    assessment: str
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    identified_risks: list[str]
    suggested_entry_conditions: list[str]
    suggested_invalidation_conditions: list[str]
    uncertainty: str
    explanation: str
    tokens_used: int = 0
    estimated_cost_usd: Decimal = Decimal("0")
    failed: bool = False


@dataclass(frozen=True)
class RiskEvaluation:
    evaluation_id: str
    accepted: bool
    checks: dict[str, bool]
    reasons: list[str]
    max_quantity: Decimal
    reserved_quote: Decimal


@dataclass(frozen=True)
class TradingDecision:
    decision_id: str
    symbol: str
    timestamp: datetime
    action: DecisionAction
    signal_ids: list[str]
    ai_assessment_id: str | None
    proposed_quote_amount: Decimal
    proposed_quantity: Decimal
    entry_price: Decimal | None
    stop_loss: Decimal | None
    take_profit_targets: tuple[Decimal, Decimal, Decimal] | tuple[()]
    accepted: bool
    rejected_reason: str | None
    explanation: str


@dataclass
class Balance:
    asset: str
    available: Decimal
    reserved: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return self.available + self.reserved


@dataclass
class Position:
    position_id: str
    symbol: str
    quantity: Decimal
    average_entry_price: Decimal
    opened_at: datetime
    realized_pnl: Decimal = Decimal("0")
    protective_stop: Decimal | None = None
    take_profit_targets: list[Decimal] = field(default_factory=list)
    original_quantity: Decimal | None = None
    target_quantities: list[Decimal] = field(default_factory=list)
    target_filled_quantities: list[Decimal] = field(default_factory=list)
    closed_at: datetime | None = None

    @property
    def exposure(self) -> Decimal:
        return self.quantity * self.average_entry_price


@dataclass
class Order:
    order_id: str
    client_order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    quantity: Decimal
    quote_amount: Decimal
    limit_price: Decimal | None
    status: OrderStatus
    created_at: datetime
    decision_id: str | None = None
    simulated: bool = True
    filled_quantity: Decimal = Decimal("0")
    average_fill_price: Decimal | None = None
    rejection_reason: str | None = None


@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    symbol: str
    side: Side
    quantity: Decimal
    price: Decimal
    fee: Decimal
    timestamp: datetime
    simulated: bool = True
    position_id: str | None = None
