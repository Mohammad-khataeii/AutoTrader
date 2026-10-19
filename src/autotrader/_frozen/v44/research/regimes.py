from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from autotrader.domain import DataQuality, MarketFeatures

VERSION = "regimes-4.0.0"


class Regime(StrEnum):
    STRONG_BULL = "STRONG_BULL"
    MODERATE_BULL = "MODERATE_BULL"
    RANGE = "RANGE"
    COMPRESSION = "COMPRESSION"
    EXPANSION = "EXPANSION"
    BEAR = "BEAR"
    LIQUIDITY_STRESS = "LIQUIDITY_STRESS"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class RegimeAssessment:
    regime: Regime
    as_of: str
    version: str
    evidence: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def classify(features: MarketFeatures, btc: MarketFeatures | None = None,
             eth: MarketFeatures | None = None) -> RegimeAssessment:
    """Observable completed-bar states. Thresholds are research parameters, not truth labels."""
    close = Decimal(str(features.metadata.get("last_close", 0)))
    short, long = features.ema_21, features.ema_50
    atr_fraction = features.atr / close if features.atr and close > 0 else None
    width = ((features.bollinger_upper - features.bollinger_lower) / features.bollinger_mid
             if features.bollinger_upper and features.bollinger_lower and features.bollinger_mid else None)
    trend = short / long - 1 if short and long else None
    benchmarks = [b for b in (btc, eth) if b and b.symbol != features.symbol and b.timestamp <= features.timestamp]
    benchmark_bear = bool(benchmarks) and all(b.ema_21 and b.ema_50 and b.ema_21 < b.ema_50 for b in benchmarks)
    drawdown = Decimal(str(features.metadata.get("drawdown_50", 0)))
    evidence = {"ema_trend_fraction": str(trend), "atr_fraction": str(atr_fraction),
        "bollinger_width": str(width), "spread_bps": str(features.spread_bps),
        "relative_volume": str(features.relative_volume), "drawdown_50": str(drawdown),
        "benchmark_bear": benchmark_bear, "benchmark_symbols": [b.symbol for b in benchmarks],
        "history_contiguous": features.metadata.get("history_contiguous", True),
        "label_source": "causal rules on observed data; no retrospective labels"}
    state = Regime.UNCERTAIN
    if features.data_quality is not DataQuality.GOOD or trend is None or atr_fraction is None or not features.metadata.get("history_contiguous", True):
        pass
    elif features.spread_bps is not None and features.spread_bps > 75:
        state = Regime.LIQUIDITY_STRESS
    elif (trend < Decimal("-.005") and close < (long or close)) or drawdown < Decimal("-.25") or (benchmark_bear and trend < 0):
        state = Regime.BEAR
    elif atr_fraction > Decimal(".09"):
        state = Regime.UNCERTAIN
    elif features.relative_volume and features.relative_volume > Decimal("1.5") and abs(features.momentum or Decimal(0)) > atr_fraction:
        state = Regime.EXPANSION
    elif width is not None and width < Decimal(".04"):
        state = Regime.COMPRESSION
    elif trend > Decimal(".015") and close > (short or close):
        state = Regime.STRONG_BULL
    elif trend > 0 and close > (long or close):
        state = Regime.MODERATE_BULL
    elif abs(trend) <= Decimal(".015"):
        state = Regime.RANGE
    return RegimeAssessment(state, features.timestamp.isoformat(), VERSION, evidence)
