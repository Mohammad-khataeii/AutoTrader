from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from autotrader.domain import MarketFeatures, StrategySignal, new_id
from autotrader.research.regimes import Regime, classify

VERSION = "4.0.0"


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    hypothesis: str
    inputs: tuple[str, ...]
    entry: str
    invalidation: str
    exit: str
    holding_bars: int
    regimes: tuple[Regime, ...]
    filter_only: bool = False
    version: str = VERSION
    cost_assumption: str = "side-aware IOC, configurable spread/fee/slippage, finite depth"
    risk_policy: str = "long-only EUR500, <=3 positions, <=EUR100 each, <=EUR5 planned loss"
    results: str = "No validated edge until a frozen OOS report passes all research gates"


BULL = (Regime.STRONG_BULL, Regime.MODERATE_BULL, Regime.COMPRESSION, Regime.EXPANSION)
REGISTRY = (
    StrategySpec("A_TREND_PULLBACK", "A pullback that holds trend can resume upward", ("EMA9", "EMA21", "EMA50", "OHLC", "ATR"), "bull trend, low touches EMA9, close recovers EMA9", "close loses EMA21 or protective stop", "three ATR-spaced targets, bid stop, time expiry", 12, BULL),
    StrategySpec("B_COMPRESSION_BREAKOUT", "A narrow prior range can expand with confirmed demand", ("prior Bollinger width", "prior resistance", "volume", "close"), "prior width below threshold, completed close breaks resistance, elevated volume", "failed breakout or bid stop", "ATR targets and time expiry", 12, BULL),
    StrategySpec("C_BREAKOUT_RETEST", "A completed breakout holding its prior boundary can continue", ("prior resistance", "previous close", "low", "close"), "previous close above resistance, current retest holds", "close below retest level", "ATR targets and time expiry", 10, BULL),
    StrategySpec("D_VOLUME_ACCUMULATION", "Elevated demand above VWAP in an upward trend can persist", ("relative volume", "VWAP", "EMA21", "EMA50"), "relative volume above threshold, close above VWAP, upward EMA trend", "VWAP/trend failure or protective stop", "ATR targets and time expiry", 8, BULL),
    StrategySpec("E_RELATIVE_STRENGTH", "An established trend outperforming BTC/ETH may persist", ("20-bar returns", "BTC/ETH", "EMA21", "EMA50"), "20-bar excess return positive above threshold with upward trend", "relative strength reversal or bid stop", "ATR targets and time expiry", 10, (Regime.STRONG_BULL, Regime.MODERATE_BULL)),
    StrategySpec("F_MEAN_REVERSION", "A contained range dip can revert when selling slows", ("Bollinger lower", "RSI", "EMA trend", "drawdown"), "range/compression, near lower band, RSI below35, close recovers previous close", "downtrend classification or bid stop", "ATR targets and short time expiry", 4, (Regime.RANGE, Regime.COMPRESSION)),
    StrategySpec("G_FAILED_BREAKOUT_FILTER", "Resistance rejection invalidates a proposed long breakout", ("high", "close", "prior resistance"), "never opens positions", "high exceeds prior resistance but close loses it", "veto new entries", 0, tuple(Regime), True),
    StrategySpec("H_RISK_OFF_FILTER", "Uncertain, bearish or illiquid markets require cash preservation", ("regime", "higher timeframe confirmation"), "never opens positions", "bear, liquidity stress, uncertainty or completed higher-timeframe veto", "veto new entries; position risk policy remains authoritative", 0, tuple(Regime), True),
)


@dataclass(frozen=True)
class StrategyParameters:
    relative_volume: Decimal = Decimal("1.5")
    compression_width: Decimal = Decimal(".06")
    breakout_buffer: Decimal = Decimal(".001")
    relative_return: Decimal = Decimal(".02")
    stop_atr: Decimal = Decimal("1.5")
    target_atr: Decimal = Decimal("1.5")

    def payload(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


class V4StrategyEngine:
    def __init__(self, parameters: StrategyParameters | None = None,
                 enabled: set[str] | None = None) -> None:
        self.parameters = parameters or StrategyParameters()
        self.enabled = enabled if enabled is not None else {s.strategy_id for s in REGISTRY}

    def generate(self, f: MarketFeatures, btc_features: MarketFeatures | None = None,
                 eth_features: MarketFeatures | None = None) -> list[StrategySignal]:
        p = self.parameters
        assessment = classify(f, btc_features, eth_features)
        close = Decimal(str(f.metadata.get("last_close", 0)))
        low = Decimal(str(f.metadata.get("last_low", 0)))
        high = Decimal(str(f.metadata.get("last_high", 0)))
        previous = Decimal(str(f.metadata.get("previous_close", 0)))
        retest = Decimal(str(f.metadata.get("retest_level", 0)))
        trend = bool(f.ema_21 and f.ema_50 and f.ema_21 > f.ema_50)
        prior_width = Decimal(str(f.metadata.get("prior_bollinger_width", 1)))
        benchmarks = [b for b in (btc_features, eth_features) if b and b.symbol != f.symbol and b.timestamp <= f.timestamp and "return_20" in b.metadata]
        relative = (Decimal(str(f.metadata.get("return_20", 0))) - sum((Decimal(str(b.metadata["return_20"])) for b in benchmarks), Decimal(0)) / len(benchmarks)) if benchmarks else None
        qualified = {
            "A_TREND_PULLBACK": bool(trend and f.ema_9 and low <= f.ema_9 <= close and close > previous),
            "B_COMPRESSION_BREAKOUT": bool(prior_width < p.compression_width and f.resistance and close > f.resistance * (1 + p.breakout_buffer) and f.relative_volume and f.relative_volume >= p.relative_volume),
            "C_BREAKOUT_RETEST": bool(retest > 0 and previous > retest * (1 + p.breakout_buffer) and low <= retest * Decimal("1.002") and close >= retest),
            "D_VOLUME_ACCUMULATION": bool(trend and f.vwap and close > f.vwap and f.relative_volume and f.relative_volume >= p.relative_volume),
            "E_RELATIVE_STRENGTH": bool(trend and relative is not None and relative > p.relative_return and close > previous),
            "F_MEAN_REVERSION": bool(f.bollinger_lower and close <= f.bollinger_lower * Decimal("1.01") and f.rsi is not None and f.rsi < 35 and close > previous),
            "G_FAILED_BREAKOUT_FILTER": bool(f.resistance and high > f.resistance * (1 + p.breakout_buffer) and close < f.resistance),
            "H_RISK_OFF_FILTER": assessment.regime in {Regime.BEAR, Regime.LIQUIDITY_STRESS, Regime.UNCERTAIN} or bool(f.metadata.get("higher_timeframe_confirmation", {}).get("veto")),
        }
        result = []
        f.metadata["regime_assessment"] = assessment.payload()
        for spec in REGISTRY:
            enabled = spec.strategy_id in self.enabled or spec.filter_only
            eligible = enabled and qualified[spec.strategy_id] and assessment.regime in spec.regimes
            evidence: dict[str, Any] = {"strategy_version": VERSION, "qualified": eligible,
                "entry_eligible": eligible and not spec.filter_only, "veto": eligible and spec.filter_only,
                "regime": assessment.regime.value, "regime_version": assessment.version,
                "parameters": p.payload(), "holding_bars": spec.holding_bars,
                "timeframe": f.timeframe,
                "relative_return": str(relative), "enabled": enabled,
                "observable_conditions": qualified[spec.strategy_id], "as_of": assessment.as_of}
            result.append(StrategySignal(new_id("sig"), spec.strategy_id, f.symbol, f.timestamp,
                Decimal(1) if eligible and not spec.filter_only else Decimal(0), f.data_quality, evidence,
                [spec.entry], [spec.invalidation], f.spread_bps or Decimal(0), spec.hypothesis))
        return result
