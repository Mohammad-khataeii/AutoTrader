from __future__ import annotations

from decimal import Decimal

from autotrader.domain import (
    AIAssessment,
    DecisionAction,
    MarketFeatures,
    StrategySignal,
    TradingDecision,
    TradingPair,
    new_id,
    quantize_down,
    utc_now,
)
from autotrader.portfolio import Portfolio
from autotrader.risk import RiskEngine


class DecisionEngine:
    def __init__(self, risk_engine: RiskEngine, default_quote_amount: Decimal = Decimal("75")) -> None:
        self.risk_engine = risk_engine
        self.default_quote_amount = default_quote_amount

    def decide(
        self,
        pair: TradingPair,
        features: MarketFeatures,
        signals: list[StrategySignal],
        portfolio: Portfolio,
        ai_assessment: AIAssessment | None,
        entries_today: int = 0,
    ) -> TradingDecision:
        total_score = sum((signal.score for signal in signals), Decimal("0"))
        price = features.metadata.get("best_ask", features.metadata.get("last_price"))
        entry_price = Decimal(str(price)) if price is not None else features.vwap or features.ema_9
        if entry_price is None or entry_price <= 0:
            return self._reject(pair.symbol, signals, ai_assessment, "No valid entry price.", DecisionAction.WAIT)

        atr = features.atr or (entry_price * Decimal("0.02"))
        v4_signals = [signal for signal in signals if signal.evidence.get("strategy_version") in {"4.0.0", "4.2.0-experimental.1", "4.6.0-experimental.1", "4.6.0-experimental.2", "4.8.0-raoe.1"}]
        eligible_v4 = [s for s in v4_signals if s.evidence.get('entry_eligible')]
        primary = min(eligible_v4,key=lambda s:(-s.score,s.strategy_id)) if eligible_v4 else (v4_signals[0] if v4_signals else None)
        parameters = primary.evidence.get("parameters", {}) if primary else {}
        stop_atr = Decimal(parameters.get("stop_atr", "1.5"))
        target_atr = Decimal(parameters.get("target_atr", "1"))
        stop_loss = quantize_down(max(entry_price - (atr * stop_atr), Decimal("0")), pair.price_step)
        successor_plan = primary.evidence.get('entry_plan') if primary and primary.evidence.get('strategy_version') in {'4.6.0-experimental.1', '4.6.0-experimental.2', '4.8.0-raoe.1'} else None
        if successor_plan:
            stop_loss = Decimal(successor_plan['stop'])
        quote_amount = min(self.default_quote_amount, Decimal("100"))
        if v4_signals and 0 < stop_loss < entry_price:
            quote_amount = min(quote_amount, Decimal(5) / ((entry_price - stop_loss) / entry_price + Decimal(".005")))
        if primary and primary.evidence.get('strategy_version') in {'4.6.0-experimental.2','4.8.0-raoe.1'}:
            proposed = primary.evidence.get('sizing', {}).get('quote_budget_eur')
            if proposed is not None:
                quote_amount = min(Decimal(100), Decimal(proposed), Decimal(5)/((entry_price-stop_loss)/entry_price+Decimal('.005'))) if 0<stop_loss<entry_price else Decimal(0)
        # Size with a conservative execution-cost cushion so market orders do not rely on
        # spending more than the capital reserved by the risk engine.
        execution_buffer = Decimal("1.005")
        quantity = quantize_down(quote_amount / (entry_price * execution_buffer), pair.quantity_step)

        action = DecisionAction.WAIT
        reasons = [f"aggregate_signal_score={total_score}"]
        eligible = [s.strategy_id for s in v4_signals if s.evidence.get("entry_eligible")]
        if (v4_signals and eligible) or (not v4_signals and total_score >= Decimal("1.2")):
            action = DecisionAction.BUY
        reasons.append(f"explicit_eligible_strategies={eligible}")
        if ai_assessment and ai_assessment.failed:
            reasons.append("AI failed; deterministic path used.")
        elif ai_assessment and ai_assessment.provider != "off" and ai_assessment.suggested_action in {DecisionAction.WAIT, DecisionAction.HOLD} and action is DecisionAction.BUY:
            action = DecisionAction.WAIT
            reasons.append("AI contradicted entry; waiting.")
        if features.data_quality.value != "GOOD":
            action = DecisionAction.WAIT
            reasons.append(f"data_quality={features.data_quality}")
        if any(signal.evidence.get("veto") for signal in signals):
            action=DecisionAction.WAIT
            reasons.append("strategy_regime_or_failed_breakout_veto")

        accepted = False
        rejected_reason = None
        if action is DecisionAction.BUY:
            risk = self.risk_engine.evaluate_entry(portfolio, pair, quote_amount, entry_price, stop_loss, entries_today)
            accepted = risk.accepted
            if not accepted:
                rejected_reason = ", ".join(risk.reasons)
                action = DecisionAction.WAIT
            reasons.extend([f"risk_{name}={passed}" for name, passed in risk.checks.items()])
        else:
            rejected_reason = "Entry conditions not met."

        targets = (
            quantize_down(entry_price + atr * target_atr, pair.price_step),
            quantize_down(entry_price + (atr * target_atr * Decimal("2")), pair.price_step),
            quantize_down(entry_price + (atr * target_atr * Decimal("3")), pair.price_step),
        )
        if successor_plan and len(successor_plan['targets']) == 3:
            targets = tuple(Decimal(v) for v in successor_plan['targets'])  # type: ignore[assignment]
        return TradingDecision(
            decision_id=new_id("dec"),
            symbol=pair.symbol,
            timestamp=utc_now(),
            action=action,
            signal_ids=[signal.signal_id for signal in signals],
            ai_assessment_id=ai_assessment.assessment_id if ai_assessment else None,
            proposed_quote_amount=quote_amount,
            proposed_quantity=quantity,
            entry_price=quantize_down(entry_price, pair.price_step),
            stop_loss=stop_loss,
            take_profit_targets=targets,
            accepted=accepted,
            rejected_reason=rejected_reason,
            explanation="; ".join(reasons),
        )

    def _reject(self, symbol: str, signals: list[StrategySignal], ai_assessment: AIAssessment | None, reason: str, action: DecisionAction) -> TradingDecision:
        return TradingDecision(
            decision_id=new_id("dec"),
            symbol=symbol,
            timestamp=utc_now(),
            action=action,
            signal_ids=[signal.signal_id for signal in signals],
            ai_assessment_id=ai_assessment.assessment_id if ai_assessment else None,
            proposed_quote_amount=Decimal("0"),
            proposed_quantity=Decimal("0"),
            entry_price=None,
            stop_loss=None,
            take_profit_targets=(),
            accepted=False,
            rejected_reason=reason,
            explanation=reason,
        )
