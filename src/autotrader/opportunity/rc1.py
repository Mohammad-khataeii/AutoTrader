"""Technical qualification, execution economics and uncertainty are separate stages."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from autotrader.domain import (
    Candle,
    DataQuality,
    MarketFeatures,
    OrderBook,
    StrategySignal,
    TradingPair,
    quantize_down,
)
from autotrader.market_data.service import MarketDataService
from autotrader.opportunity.patterns import replay
from autotrader.opportunity.rc1_economics import CostAssumptions, CostAwareOpportunityEngine
from autotrader.opportunity.regime import assess_regime, number
from autotrader.research.data import digest
from autotrader.research.strategies import BULL, StrategySpec

D = Decimal
VERSION = "4.6.0-experimental.1"
SUCCESSOR_REGISTRY = tuple(StrategySpec(identity, hypothesis, ("completed 5m/15m/1h", "finite depth", "cost economics"),
    "independent technical setup followed by net economic feasibility", "structure invalidation and unchanged portfolio risk", "partial targets, trailing protection and time expiry", 36, BULL, version=VERSION)
    for identity, hypothesis in (
        ("A3_COST_AWARE_CONTINUATION", "Controlled pullback in completed higher trend with economically plausible upside"),
        ("B3_STATEFUL_BREAKOUT", "Completed compression, breakout and delayed retest without repeated event admission"),
        ("E3_ADAPTIVE_RELATIVE_STRENGTH", "Volatility-normalized persistent excess return with independent trend and cost checks")))


@dataclass(frozen=True)
class SuccessorParameters:
    target_atr: Decimal = Decimal(2)
    stop_atr: Decimal = Decimal(2)
    relative_z: Decimal = Decimal(".75")
    relative_volume: Decimal = Decimal("1.2")
    compression_width: Decimal = Decimal(".02")
    breakout_volume: Decimal = Decimal("1.3")
    retest_bars: int = 8
    holding_bars: int = 36
    target_basis: str = "15m"
    minimum_net_reward_risk: Decimal = Decimal("1.2")

    def __post_init__(self) -> None:
        values = (self.target_atr, self.stop_atr, self.relative_z, self.relative_volume,
                  self.compression_width, self.breakout_volume, self.minimum_net_reward_risk)
        if (not all(v.is_finite() and v > 0 for v in values) or not 1 <= self.retest_bars <= 24
            or not 1 <= self.holding_bars <= 144 or self.target_basis not in {"5m", "15m", "STRUCTURE"}):
            raise ValueError("invalid_successor_research_parameters")

    def payload(self) -> dict[str, str]:
        return {k: str(v) for k, v in asdict(self).items()}

    @classmethod
    def from_payload(cls, raw: dict[str, str]) -> SuccessorParameters:
        converted: dict[str, Any] = {k: v if k == "target_basis" else int(v) if k in {"retest_bars", "holding_bars"} else D(v) for k, v in raw.items()}
        return cls(**converted)


def relative_strength(f: MarketFeatures, btc: MarketFeatures | None, eth: MarketFeatures | None) -> dict[str, Any]:
    peers = [p for p in (btc, eth) if p is not None and p.symbol != f.symbol and p.timestamp == f.timestamp and p.data_quality is DataQuality.GOOD and p.metadata.get('history_contiguous', True)]
    r = number(f.metadata.get("return_20"))
    vol = number(f.metadata.get("return_volatility_20"))
    available = bool(peers) and r is not None and vol is not None and vol > 0 and all(number(p.metadata.get("return_20")) is not None and number(p.metadata.get("return_volatility_20")) is not None for p in peers)
    if not available:
        return {"ready": False, "reason": "missing_synchronized_return_volatility_or_benchmarks", "normalized_excess": None}
    assert r is not None and vol is not None
    benchmark_return = sum((D(str(p.metadata["return_20"])) for p in peers), D(0)) / len(peers)
    benchmark_vol = sum((D(str(p.metadata["return_volatility_20"])) for p in peers), D(0)) / len(peers)
    denominator = (vol * vol + benchmark_vol * benchmark_vol).sqrt() * D(20).sqrt()
    longer = number(f.metadata.get("return_60"))
    peer_longer = [number(p.metadata.get("return_60")) for p in peers]
    persistent = longer is not None and all(v is not None for v in peer_longer) and longer > sum((v for v in peer_longer if v is not None), D(0)) / len(peers)
    return {"ready": True, "normalized_excess": str((r - benchmark_return) / denominator),
        "excess_return_20": str(r - benchmark_return), "persistent_60": persistent,
        "benchmarks": [p.symbol for p in peers], "as_of": f.timestamp.isoformat(),
        "normalization": "excess return / sqrt(asset variance + peer mean variance) / sqrt(20); not a calibrated z probability"}


class SuccessorOpportunityEngine:
    def __init__(self, parameters: SuccessorParameters | None = None, fee_bps: Decimal = Decimal(10), slippage_bps: Decimal = Decimal(8)):
        self.parameters = parameters or SuccessorParameters()
        self.costs = CostAwareOpportunityEngine(CostAssumptions(fee_bps, fee_bps, slippage_bps, self.parameters.minimum_net_reward_risk))

    def evaluate(self, identity: str, f: MarketFeatures, pair: TradingPair, book: OrderBook,
                 btc: MarketFeatures | None = None, eth: MarketFeatures | None = None,
                 candles: list[Candle] | None = None) -> StrategySignal:
        if identity not in {s.strategy_id for s in SUCCESSOR_REGISTRY}:
            raise ValueError("unknown_successor_strategy")
        p = self.parameters
        assessment = assess_regime(f, btc, eth)
        close, previous, low, opening = (number(f.metadata.get(k)) for k in ("last_close", "previous_close", "last_low", "last_open"))
        atr = number(f.atr)
        higher = f.metadata.get("successor_context", {})
        h15 = higher.get("15m", {})
        validator = MarketDataService(None)  # type: ignore[arg-type]
        data_errors, _ = validator.validate_order_book(book)
        data_errors.extend(validator.validate_pair(pair))
        ready = f.timeframe == '5m' and not data_errors and f.data_quality is DataQuality.GOOD and not assessment.missing and f.metadata.get("history_contiguous", True) and bool(h15.get("ready"))
        recovering = close is not None and previous is not None and opening is not None and close > previous and close > opening
        extension = (close - f.ema_21) / atr if close and f.ema_21 and atr and atr > 0 else None
        common = {"completed_data": ready, "valid_precision": pair.price_step > 0 and pair.quantity_step > 0,
                  "not_extended": extension is not None and extension <= 2,
                  "nonbearish_trend": assessment.trend in {"STRONG_BULLISH", "MODERATE_BULLISH", "NEUTRAL"}}
        state: dict[str, Any] | None = None
        relative: dict[str, Any] | None = None
        if identity.startswith("A3"):
            conditions = {**common, "higher_15m_bullish": bool(h15.get("bull")), "recovering": recovering,
                "pullback_invalidation": bool(low and close and f.ema_21 and f.ema_9 and low <= f.ema_9 and close >= f.ema_9 and low >= f.ema_21 - (atr or D(0)))}
        elif identity.startswith("B3"):
            pattern_key = ':'.join((str(p.compression_width), str(p.breakout_volume), str(p.retest_bars)))
            state = replay(candles[-120:], compression_width=p.compression_width,
                volume_ratio=p.breakout_volume, retest_bars=p.retest_bars).payload() if candles else f.metadata.get('successor_patterns', {}).get(pattern_key, {'stage': 'WATCHING', 'confirmed_at': None})
            conditions = {**common, "confirmed_delayed_retest": state["stage"] == "CONFIRMED" and state["confirmed_at"] == f.timestamp.isoformat()}
        else:
            relative = relative_strength(f, btc, eth)
            z = number(relative.get("normalized_excess"))
            conditions = {**common, "synchronized_relative_strength": relative["ready"], "normalized_outperformance": z is not None and z >= p.relative_z,
                "persistent_outperformance": relative.get("persistent_60") is True, "recovering": recovering,
                "relative_demand": f.relative_volume is not None and f.relative_volume >= p.relative_volume,
                "benchmarks_not_adverse": assessment.benchmark in {"SUPPORTIVE", "MIXED"}}
        technical = all(conditions.values())
        entry = book.best_ask
        horizon_atr = number(h15.get("atr")) if p.target_basis in {'15m', 'STRUCTURE'} else atr
        stop = quantize_down(max((low or D(0)) - (atr or D(0)) * D(".2"), (entry or D(0)) - (atr or D(0)) * p.stop_atr), pair.price_step) if pair.price_step > 0 else D(0)
        target_distance = horizon_atr * p.target_atr if horizon_atr else None
        if p.target_basis == 'STRUCTURE':
            resistance = number(h15.get('resistance'))
            target_distance = resistance - entry if resistance is not None and entry and resistance > entry else None
        targets = tuple(quantize_down(entry + target_distance * i, pair.price_step) for i in (D(1), D("1.5"), D(2))) if entry and target_distance and pair.price_step > 0 else ()
        plausible = entry + horizon_atr * D(4) if entry and horizon_atr else None
        economics = self.costs.evaluate(pair, book, quote_budget=D(75), stop=stop, targets=targets,
            atr=atr or D(0), plausible_target=plausible, holding_bars=p.holding_bars) if technical else None
        viable = technical and economics is not None and economics.feasible
        reasons = [*data_errors, *[k for k, v in conditions.items() if not v]] if not technical else list(economics.reasons) if economics else ["missing_economics"]
        strength = D(sum(conditions.values())) / len(conditions)
        trend_strength = min(D(1), max(D(0), (number(assessment.evidence['ema_separation_atr']) or D(0)) / 2))
        liquidity_strength = max(D(0), 1 - (f.spread_bps or D(25)) / 25) if assessment.liquidity == 'HEALTHY' else D(0)
        rr = number(economics.measurements.get('net_reward_risk')) if economics else None
        economic_strength = min(D(1), max(D(0), (rr or D(0)) / 3))
        components = {'technical': D('.35')*strength, 'trend': D('.25')*trend_strength,
                      'liquidity': D('.20')*liquidity_strength, 'economics': D('.20')*economic_strength}
        score = sum(components.values(), D(0))
        stages = [{"stage": "DATA_VALIDATION", "reached": True, "passed": ready, "reason": "completed_context_available" if ready else ','.join(data_errors) or "missing_or_invalid_completed_context"},
            {"stage": "REGIME", "reached": ready, "passed": ready and assessment.trend != "UNKNOWN", "reason": assessment.trend},
            {"stage": "TECHNICAL_SETUP", "reached": ready, "passed": technical if ready else None, "reason": ",".join(reasons) if not technical else "technical_setup_qualified"},
            {"stage": "COST_FEASIBILITY", "reached": technical, "passed": economics.feasible if economics else None, "reason": ",".join(economics.reasons) if economics else "NOT_REACHED"},
            {"stage": "EXPECTED_VALUE", "reached": viable, "passed": None, "reason": "UNCALIBRATED_RESEARCH_PAPER_ONLY"},
            {"stage": "PORTFOLIO_RISK", "reached": False, "passed": None, "reason": "NOT_REACHED"},
            {"stage": "PAPER_EXECUTION", "reached": False, "passed": None, "reason": "NOT_REACHED"}]
        stamp = f.timestamp.isoformat()
        explanation = "Technical setup qualified; net economics feasible, predictive edge unvalidated." if viable else "Valid technical setup, but expected exit proceeds do not cover estimated costs or net risk requirements." if technical else "Missing technical evidence: " + ", ".join(reasons)
        evidence = {"strategy_version": VERSION, "entry_eligible": viable, "technical_eligible": technical, "economic_eligible": viable,
            "qualified": viable, "veto": False, "unvalidated": True, "regime": assessment.trend,
            "regime_assessment": assessment.payload(), "parameters": p.payload(), "holding_bars": p.holding_bars, "timeframe": f.timeframe,
            "conditions": conditions, "pattern_state": state, "relative_strength": relative,
            "economics": economics.payload() if economics else None, "pipeline": stages, "reasons": reasons,
            "entry_plan": {"stop": str(stop), "targets": [str(t) for t in targets]},
            "expected_value": {"status": "NOT_ESTIMATED", "probability": None, "confidence": "UNVALIDATED"},
            "score_components": {k: str(v) for k, v in components.items()},
            "score_interpretation": "Transparent ranking, not a calibrated probability or independent predictive edge",
            "as_of": stamp, "execution_quality_required": True}
        return StrategySignal("sig_" + digest((identity + f.symbol + stamp).encode())[:40], identity, f.symbol, f.timestamp,
            score, f.data_quality, evidence, [explanation], ["Observed structure invalidation or protective stop"],
            f.spread_bps or D(0), explanation)
