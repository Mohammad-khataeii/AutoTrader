"""Frozen, bounded unvalidated hypotheses. D2 is exclusively a veto filter."""

from decimal import Decimal as D
from typing import Any

from autotrader.domain import MarketFeatures, StrategySignal, new_id
from autotrader.research.regimes import Regime, classify
from autotrader.research.strategies import BULL, StrategyParameters, StrategySpec

VERSION = "4.2.0-experimental.1"
EXPERIMENTAL_REGISTRY = (
    StrategySpec(
        "A2_CONFIRMED_PULLBACK",
        "Reject extended pullbacks; require completed higher trend and recovery",
        ("5m OHLC", "15m/1h complete EMA", "ATR"),
        "controlled EMA9 recovery above previous high, higher trend",
        "bid stop or trend invalidation",
        "ATR targets; 12 bars",
        12,
        BULL,
        version=VERSION,
    ),
    StrategySpec(
        "B2_CONFIRMED_COMPRESSION",
        "Confirm acceptance after a volume breakout instead of buying its first impulse",
        ("prebreak width", "previous close", "range", "volume", "15m/1h"),
        "previous breakout, present range hold, no chase, higher trend",
        "failed breakout or bid stop",
        "ATR targets; 12 bars",
        12,
        BULL,
        version=VERSION,
    ),
    StrategySpec(
        "C2_LIQUID_RETEST",
        "Require green retest recovery, higher trend and executable cost/depth quality",
        ("range", "previous high", "volume", "15m/1h", "live depth at gateway"),
        "retest holds and closes above previous high; volume quality",
        "bid stop or failed retest",
        "ATR targets; 10 bars",
        10,
        BULL,
        version=VERSION,
    ),
    StrategySpec(
        "D2_MOMENTUM_QUALITY",
        "Reject extension, weakening demand, adverse benchmarks or wide spread",
        ("ATR extension", "volume", "BTC/ETH", "spread"),
        "never opens a position",
        "extension >2 ATR, falling volume with falling close, bearish benchmarks, spread >25bps",
        "veto only",
        0,
        tuple(Regime),
        True,
        version=VERSION,
    ),
    StrategySpec(
        "E2_ABSOLUTE_RELATIVE_STRENGTH",
        "Require absolute BTC/ETH uptrends alongside relative outperformance",
        ("20-bar excess return", "BTC/ETH EMA", "15m/1h"),
        "absolute benchmark trends and local recovery",
        "benchmark weakness or bid stop",
        "ATR targets; 10 bars",
        10,
        (Regime.STRONG_BULL, Regime.MODERATE_BULL),
        version=VERSION,
    ),
    StrategySpec(
        "F2_RESTRICTED_RANGE",
        "Limit reversion to range conditions with nonbearish completed higher context",
        ("range", "RSI", "Bollinger", "15m/1h"),
        "RANGE only, lower-band recovery, not higher downtrend",
        "bearish transition or bid stop",
        "ATR targets; 4 bars",
        4,
        (Regime.RANGE,),
        version=VERSION,
    ),
)


class ExperimentalStrategyEngine:
    def __init__(
        self, parameters: StrategyParameters | None = None, enabled: set[str] | None = None
    ):
        self.parameters = parameters or StrategyParameters(stop_atr=D(2), target_atr=D(2))
        self.enabled = (
            enabled if enabled is not None else {s.strategy_id for s in EXPERIMENTAL_REGISTRY}
        )

    def generate(
        self,
        f: MarketFeatures,
        btc_features: MarketFeatures | None = None,
        eth_features: MarketFeatures | None = None,
    ) -> list[StrategySignal]:
        p = self.parameters
        assessment = classify(f, btc_features, eth_features)
        f.metadata["regime_assessment"] = assessment.payload()
        context = f.metadata.get("experimental_context", {})
        ready = bool(context.get("ready"))
        higher_bull = ready and all(context[k]["bull"] for k in ("15m", "60m"))
        higher_safe = ready and not any(context[k]["bear"] for k in ("15m", "60m"))
        close = D(str(f.metadata.get("last_close", 0)))
        previous = D(str(f.metadata.get("previous_close", 0)))
        low = D(str(f.metadata.get("last_low", 0)))
        retest = D(str(f.metadata.get("retest_level", 0)))
        atr = f.atr or D(0)
        extended = bool(atr > 0 and f.ema_21 and (close - f.ema_21) / atr > 2)
        benchmarks = [b for b in (btc_features, eth_features) if b and b.timestamp == f.timestamp]
        benchmark_safe = len(benchmarks) == 2 and all(
            b.ema_21
            and b.ema_50
            and b.ema_21 > b.ema_50
            and D(str(b.metadata.get("last_close", 0))) >= b.ema_21
            for b in benchmarks
        )
        peers = [b for b in benchmarks if b.symbol != f.symbol and "return_20" in b.metadata]
        relative = (
            D(str(f.metadata.get("return_20", 0)))
            - sum((D(str(b.metadata["return_20"])) for b in peers), D(0)) / len(peers)
            if peers
            else None
        )
        falling = bool(
            close < previous
            and D(context.get("current_volume", "0")) < D(context.get("previous_volume", "0"))
        )
        veto = (
            extended
            or falling
            or any(b.ema_21 and b.ema_50 and b.ema_21 < b.ema_50 for b in benchmarks)
            or (f.spread_bps or 0) > 25
            or assessment.regime in {Regime.BEAR, Regime.LIQUIDITY_STRESS, Regime.UNCERTAIN}
        )
        volume = bool(f.relative_volume and f.relative_volume >= p.relative_volume)
        recovering = bool(close > previous and close > D(context.get("last_open", "0")))
        tests = {
            "A2_CONFIRMED_PULLBACK": bool(
                higher_bull
                and f.ema_9
                and low <= f.ema_9 <= close
                and recovering
                and close > D(context.get("previous_high", "0"))
            ),
            "B2_CONFIRMED_COMPRESSION": bool(
                higher_bull
                and retest > 0
                and D(context.get("prebreak_width", "1")) < p.compression_width
                and previous > retest * (1 + p.breakout_buffer)
                and low >= retest * (1 - p.breakout_buffer)
                and close >= previous
                and D(context.get("breakout_relative_volume", "0")) >= p.relative_volume
            ),
            "C2_LIQUID_RETEST": bool(
                higher_bull
                and retest > 0
                and previous > retest * (1 + p.breakout_buffer)
                and low <= retest * D("1.002")
                and close >= retest
                and recovering
                and close > D(context.get("previous_high", "0"))
                and volume
            ),
            "D2_MOMENTUM_QUALITY": veto,
            "E2_ABSOLUTE_RELATIVE_STRENGTH": bool(
                higher_bull
                and benchmark_safe
                and relative is not None
                and relative > p.relative_return
                and recovering
                and volume
            ),
            "F2_RESTRICTED_RANGE": bool(
                higher_safe
                and f.bollinger_lower
                and close <= f.bollinger_lower * D("1.01")
                and f.rsi is not None
                and f.rsi < 35
                and recovering
            ),
        }
        result = []
        for spec in EXPERIMENTAL_REGISTRY:
            eligible = (
                spec.strategy_id in self.enabled
                and bool(tests[spec.strategy_id])
                and assessment.regime in spec.regimes
            )
            if spec.filter_only:
                eligible = bool(tests[spec.strategy_id])
            evidence: dict[str, Any] = {
                "strategy_version": VERSION,
                "qualified": eligible,
                "entry_eligible": eligible and not spec.filter_only,
                "veto": eligible and spec.filter_only,
                "regime": assessment.regime.value,
                "parameters": p.payload(),
                "holding_bars": spec.holding_bars,
                "timeframe": f.timeframe,
                "experimental_context": context,
                "relative_return": str(relative),
                "unvalidated": True,
                "execution_quality_required": True,
                "as_of": assessment.as_of,
            }
            result.append(
                StrategySignal(
                    new_id("sig"),
                    spec.strategy_id,
                    f.symbol,
                    f.timestamp,
                    D(1) if evidence["entry_eligible"] else D(0),
                    f.data_quality,
                    evidence,
                    [spec.entry],
                    [spec.invalidation],
                    f.spread_bps or D(0),
                    spec.hypothesis,
                )
            )
        return result
