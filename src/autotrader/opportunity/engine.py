"""Technical qualification, execution economics and uncertainty are separate stages."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from statistics import pstdev
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
from autotrader.opportunity.economics import CostAssumptions, CostAwareOpportunityEngine
from autotrader.opportunity.patterns import replay
from autotrader.opportunity.regime import assess_regime, number
from autotrader.opportunity.sizing import quote_for_plan
from autotrader.opportunity.status import qualification
from autotrader.research.data import digest
from autotrader.research.strategies import BULL, StrategySpec

D = Decimal
VERSION = "4.6.0-experimental.2"
SUCCESSOR_REGISTRY = tuple(StrategySpec(identity, hypothesis, ("completed 5m/15m/1h", "finite depth", "cost economics"),
    "independent technical setup followed by net economic feasibility", "structure invalidation and unchanged portfolio risk", "partial targets, trailing protection and time expiry", 36, BULL, version=VERSION)
    for identity, hypothesis in (
        ("A3_COST_AWARE_CONTINUATION", "Controlled pullback in completed higher trend with economically plausible upside"),
        ("B3_STATEFUL_BREAKOUT", "Completed compression, breakout and delayed retest without repeated event admission"),
        ("E3_ADAPTIVE_RELATIVE_STRENGTH", "Volatility-normalized persistent excess return with independent trend and cost checks")))


@dataclass(frozen=True)
class SuccessorParameters:
    entry_reference: str = "MIDPOINT"
    entry_mode: str = "EARLY_RECLAIM"
    breakout_hold_bars: int = 2
    stop_basis: str = "STRUCTURE"
    relative_model: str = "RESIDUAL_VOLATILITY"
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
            or not 0 <= self.breakout_hold_bars <= 6 or self.entry_mode not in {"RECOVERY", "EARLY_RECLAIM"}
            or self.entry_reference not in {"ASK", "MIDPOINT"}
            or self.stop_basis not in {"ATR_CAP", "STRUCTURE"} or self.relative_model not in {"INDEPENDENT_VARIANCE", "RESIDUAL_VOLATILITY"}
            or not 1 <= self.holding_bars <= 144 or self.target_basis not in {"5m", "15m", "STRUCTURE"}):
            raise ValueError("invalid_successor_research_parameters")

    def payload(self) -> dict[str, str]:
        return {k: str(v) for k, v in asdict(self).items()}

    @classmethod
    def from_payload(cls, raw: dict[str, str]) -> SuccessorParameters:
        converted: dict[str, Any] = {k: v if k in {"target_basis", "entry_mode", "entry_reference", "stop_basis", "relative_model"} else int(v) if k in {"retest_bars", "holding_bars", "breakout_hold_bars"} else D(v) for k, v in raw.items()}
        return cls(**converted)


def relative_strength(f: MarketFeatures, btc: MarketFeatures | None, eth: MarketFeatures | None, *, residual: bool = False) -> dict[str, Any]:
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
    normalization = "excess return / sqrt(asset variance + peer mean variance) / sqrt(20); not a calibrated z probability"
    if residual:
        sequences = [f.metadata.get('recent_returns') or [], *[p.metadata.get('recent_returns') or [] for p in peers]]
        if any(not isinstance(seq, list) or len(seq)!=20 or any(number(v) is None for v in seq) for seq in sequences):
            return {'ready': False, 'normalized_excess': None, 'reason': 'missing_synchronized_residual_return_history'}
        excess = [D(str(sequences[0][i]))-sum((D(str(seq[i])) for seq in sequences[1:]),D(0))/len(peers) for i in range(20)]
        denominator = max(pstdev(excess), vol/D(4))*D(20).sqrt()
        normalization = 'excess return / max(5-minute residual return volatility, asset volatility / 4) / sqrt(20); not a calibrated probability'
    longer = number(f.metadata.get("return_60"))
    peer_longer = [number(p.metadata.get("return_60")) for p in peers]
    persistent = longer is not None and all(v is not None for v in peer_longer) and longer > sum((v for v in peer_longer if v is not None), D(0)) / len(peers)
    return {"ready": True, "normalized_excess": str((r - benchmark_return) / denominator),
        "excess_return_20": str(r - benchmark_return), "persistent_60": persistent,
        "benchmarks": [p.symbol for p in peers], "as_of": f.timestamp.isoformat(),
        "normalization": normalization}


class SuccessorOpportunityEngine:
    def __init__(self, parameters: SuccessorParameters | None = None, fee_bps: Decimal = Decimal(10), slippage_bps: Decimal = Decimal(8)):
        self.parameters = parameters or SuccessorParameters()
        self.costs = CostAwareOpportunityEngine(CostAssumptions(fee_bps, fee_bps, slippage_bps, self.parameters.minimum_net_reward_risk))

    def evaluate(self, identity: str, f: MarketFeatures, pair: TradingPair, book: OrderBook,
                 btc: MarketFeatures | None = None, eth: MarketFeatures | None = None,
                 candles: list[Candle] | None = None, *, quote_budget: Decimal = D(75),
                 sizing_scope: str = "RESEARCH_ASSUMPTION", sizing_context: dict[str, Any] | None = None) -> StrategySignal:
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
        if f.metadata.get('completed_context_delayed'):
            data_errors.append('latest_completed_candle_missing')
        ready = f.timeframe == '5m' and not data_errors and f.data_quality is DataQuality.GOOD and not assessment.missing and f.metadata.get("history_contiguous", True) and bool(h15.get("ready"))
        recovering = close is not None and previous is not None and opening is not None and close > previous and close > opening
        extension = (close - f.ema_21) / atr if close and f.ema_21 and atr and atr > 0 else None
        common = {"completed_data": ready, "valid_precision": pair.price_step > 0 and pair.quantity_step > 0,
                  "not_extended": extension is not None and extension <= 2,
                  "nonbearish_trend": assessment.trend in {"STRONG_BULLISH", "MODERATE_BULLISH", "NEUTRAL"}}
        state: dict[str, Any] | None = None
        relative: dict[str, Any] | None = None
        if identity.startswith("A3"):
            reclaim = bool(f.metadata.get('previous_ema9_reclaim')) and close is not None and opening is not None and close > opening
            conditions = {**common, "higher_15m_bullish": bool(h15.get("bull")), "recovering": recovering or (p.entry_mode=='EARLY_RECLAIM' and reclaim),
                "pullback_invalidation": bool(low and close and f.ema_21 and f.ema_9 and low <= f.ema_9 and close >= f.ema_9 and low >= f.ema_21 - (atr or D(0)))}
        elif identity.startswith("B3"):
            pattern_key = ':'.join((str(p.compression_width), str(p.breakout_volume), str(p.retest_bars), str(p.breakout_hold_bars)))
            state = replay(candles[-120:], compression_width=p.compression_width,
                volume_ratio=p.breakout_volume, retest_bars=p.retest_bars, hold_bars=p.breakout_hold_bars).payload() if candles else f.metadata.get('successor_patterns', {}).get(pattern_key, {'stage': 'WATCHING', 'confirmed_at': None})
            conditions = {**common, "confirmed_delayed_retest": state["stage"] == "CONFIRMED" and state["confirmed_at"] == f.timestamp.isoformat()}
        else:
            relative = relative_strength(f, btc, eth, residual=p.relative_model=="RESIDUAL_VOLATILITY")
            z = number(relative.get("normalized_excess"))
            conditions = {**common, "synchronized_relative_strength": relative["ready"], "normalized_outperformance": z is not None and z >= p.relative_z,
                "persistent_outperformance": relative.get("persistent_60") is True, "recovering": recovering,
                "relative_demand": f.relative_volume is not None and f.relative_volume >= p.relative_volume,
                "benchmarks_not_adverse": assessment.benchmark in {"SUPPORTIVE", "MIXED"},
                "positive_local_trend": bool(f.ema_21 and close and close > f.ema_21),
                "recent_positive_returns": sum(number(v) is not None and D(str(v))>0 for v in f.metadata.get("recent_returns", [])[-5:]) >= 3}
        reference = (book.best_ask+book.best_bid)/2 if p.entry_reference=='MIDPOINT' and book.best_ask and book.best_bid else book.best_ask
        conditions['entry_not_chased'] = bool(close and atr and reference and reference-close <= atr*D('.5'))
        technical = all(conditions.values())
        entry = book.best_ask
        horizon_atr = number(h15.get("atr")) if p.target_basis in {'15m', 'STRUCTURE'} else atr
        stop = quantize_down(max((low or D(0)) - (atr or D(0)) * D(".2"), (entry or D(0)) - (atr or D(0)) * p.stop_atr), pair.price_step) if pair.price_step > 0 else D(0)
        if p.stop_basis == 'STRUCTURE' and pair.price_step>0:
            invalidation = (D(state['level'])-D(state['atr'])*D('.75')) if state and state.get('level') and state.get('atr') else number(f.metadata.get('swing_low_5')) or low
            if invalidation is not None and atr:
                stop = quantize_down(invalidation-atr*D('.2'), pair.price_step)
        target_distance = horizon_atr * p.target_atr if horizon_atr else None
        if p.target_basis == 'STRUCTURE':
            resistance = number(h15.get('resistance'))
            target_distance = resistance - entry if resistance is not None and entry and resistance > entry else None
        targets = tuple(quantize_down(entry + target_distance * i, pair.price_step) for i in (D(1), D("1.5"), D(2))) if entry and target_distance and pair.price_step > 0 else ()
        plausible = entry + horizon_atr * D(4) if entry and horizon_atr else None
        sizing = {"quote_budget_eur": str(quote_budget), "scope": sizing_scope, "actual_account_admission": False}
        if sizing_context is not None:
            quote_budget, sizing = quote_for_plan(pair, book, stop, preferred=quote_budget,
                fee_bps=self.costs.assumptions.entry_fee_bps, slippage_bps=self.costs.assumptions.slippage_bps, **sizing_context)
            sizing['scope'] = sizing_scope
        economics = self.costs.evaluate(pair, book, quote_budget=quote_budget, stop=stop, targets=targets,
            atr=atr or D(0), plausible_target=plausible, holding_bars=p.holding_bars, exit_fractions=(D('.3'),D('.4'),D('.3'))) if technical else None
        if economics is not None and sizing_context is not None:
            limit = sizing_context.get('limits')
            max_loss = limit.max_planned_loss_per_trade if limit else D(5)
            for _ in range(8):
                loss = number(economics.measurements.get('expected_net_stop_loss_eur'))
                if loss is None or loss <= max_loss or quote_budget<=0:
                    break
                quote_budget *= max_loss/loss*D('.9999')
                economics = self.costs.evaluate(pair, book, quote_budget=quote_budget, stop=stop, targets=targets,
                    atr=atr or D(0), plausible_target=plausible, holding_bars=p.holding_bars, exit_fractions=(D('.3'),D('.4'),D('.3')))
                sizing.update(quote_budget_eur=str(quote_budget), binding_constraint='observed_depth_and_stop_loss_budget')
            measured_loss = number(economics.measurements.get('expected_net_stop_loss_eur'))
            if measured_loss is not None and measured_loss > max_loss:
                from dataclasses import replace
                economics = replace(economics, feasible=False, reasons=(*economics.reasons,'modeled_stop_loss_exceeds_account_budget'))
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
            "sizing": sizing,
            "data_errors": data_errors, "qualified": viable, "veto": False, "unvalidated": True, "regime": assessment.trend,
            "regime_assessment": assessment.payload(), "parameters": p.payload(), "holding_bars": p.holding_bars, "timeframe": f.timeframe,
            "conditions": conditions, "pattern_state": state, "relative_strength": relative,
            "economics": economics.payload() if economics else None, "pipeline": stages, "reasons": reasons,
            "entry_plan": {"stop": str(stop), "targets": [str(t) for t in targets]},
            "expected_value": {"status": "NOT_ESTIMATED", "probability": None, "confidence": "UNVALIDATED"},
            "score_components": {k: str(v) for k, v in components.items()},
            "score_interpretation": "Transparent ranking, not a calibrated probability or independent predictive edge",
            "as_of": stamp, "execution_quality_required": True}
        evidence['qualification_state'] = qualification(evidence)
        return StrategySignal("sig_" + digest((identity + f.symbol + stamp).encode())[:40], identity, f.symbol, f.timestamp,
            score, f.data_quality, evidence, [explanation], ["Observed structure invalidation or protective stop"],
            f.spread_bps or D(0), explanation)
