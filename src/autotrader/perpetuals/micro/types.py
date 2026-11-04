"""Versioned, immutable research contracts; fractions internally, percent at API edge. Untested and unvalidated."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from typing import Any, Literal

D = Decimal
Side = Literal[-1, 1]
Regime = Literal['TREND_UP', 'TREND_DOWN', 'RANGE', 'DISORDERED']
FEATURE_SCHEMA = 'perp-micro-features/1'
OUTCOME_SCHEMA = 'perp-micro-net-barriers-and-time/1'
EXECUTION_SCHEMA = 'perp-depth-estimate/1'
POLICIES = ('BTC_MICRO_CONTINUATION_V1', 'BTC_MICRO_RETEST_V1', 'BTC_MICRO_RANGE_V1')


@dataclass(frozen=True)
class Candle:
    start: int
    minutes: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None


@dataclass(frozen=True)
class Features:
    cutoff: int
    known_at: int
    reference: Decimal
    atr_fraction: Decimal
    efficiency: Decimal
    momentum_1m: Decimal
    momentum_3m: Decimal
    momentum_5m: Decimal
    acceleration: Decimal
    persistence: Decimal
    expansion: Decimal
    volume_ratio: Decimal | None
    regime: Regime
    one: tuple[Candle, ...]
    three: tuple[Candle, ...]
    five: tuple[Candle, ...]
    source_hash: str


@dataclass(frozen=True)
class Candidate:
    policy: str
    side: Side
    cutoff: int
    decision_at: int
    reference: Decimal
    target_fraction: Decimal
    stop_fraction: Decimal
    max_holding_minutes: int
    structure_level: Decimal | None
    signal_reasons: tuple[str, ...]
    rejection_reasons: tuple[str, ...]


@dataclass(frozen=True)
class Book:
    exchange_at: int
    received_at: int
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]
    update_id: int

    @property
    def mid(self) -> Decimal:
        return (self.bids[0][0] + self.asks[0][0]) / 2

    @property
    def spread(self) -> Decimal:
        return (self.asks[0][0] - self.bids[0][0]) / self.mid


@dataclass(frozen=True)
class Ticker:
    exchange_at: int
    received_at: int
    mark: Decimal
    next_funding_at: int
    indicative_funding_rate: Decimal | None


@dataclass(frozen=True)
class Intent:
    """A proposed quote request, not an accepted or persisted order."""
    key: str
    policy: str
    side: Side
    quantity: Decimal
    decision_at: int
    expires_at: int


@dataclass(frozen=True)
class DepthEstimate:
    intent_key: str
    quantity: Decimal
    mid: Decimal
    entry: Decimal
    exit_now: Decimal
    entry_cost_fraction: Decimal
    exit_cost_fraction: Decimal
    spread_fraction: Decimal
    quoted_at: int
    evidence_id: str
    classification: str = 'OBSERVED_DEPTH_ESTIMATE_NOT_A_FILL'
    schema: str = EXECUTION_SCHEMA


@dataclass(frozen=True)
class OutcomeEvidence:
    """Interface for a future reviewed challenger artifact, never a fabricated model.

    Each probability refers to this exact policy, regime, net cost schema and
    competing target/stop/time outcomes. Direction-only models cannot satisfy it.
    The serving path currently supplies no such artifact and always abstains.
    """
    model_id: str
    policy: str
    regime: str
    cost_fingerprint: str
    source_feature_hash: str
    predicted_at: int
    trained_through: int
    calibrated_through: int
    evaluated_through: int
    valid_until: int
    independent_labels: int
    reviewed: bool
    feature_schema: str
    outcome_schema: str
    probability_target: Decimal
    probability_stop: Decimal
    probability_time: Decimal
    time_exit_signed_move: Decimal
    expected_holding_minutes: Decimal
    expected_mae_fraction: Decimal
    source: str = 'FUTURE_REVIEWED_CHRONOLOGICAL_CHALLENGER'


def public(value: Any) -> Any:
    """JSON-safe output: Decimal never silently becomes a binary float."""
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: public(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {str(key): public(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [public(item) for item in value]
    return value
