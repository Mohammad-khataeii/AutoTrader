from __future__ import annotations

from decimal import Decimal

from autotrader.domain import MarketFeatures, StrategySignal, new_id


def _score(value: Decimal | None, low: Decimal, high: Decimal) -> Decimal:
    if value is None or high <= low:
        return Decimal("0")
    clipped = min(max(value, low), high)
    return (clipped - low) / (high - low)


class BreakoutStrategyEngine:
    """Produces structured evidence from independent research hypotheses."""

    def generate(self, features: MarketFeatures, btc_features: MarketFeatures | None = None, eth_features: MarketFeatures | None = None) -> list[StrategySignal]:
        signals = [
            self._volume_accumulation(features),
            self._volatility_compression(features),
            self._resistance_breakout(features),
            self._momentum_acceleration(features),
            self._failed_breakout(features),
            self._risk_off(features),
            self._relative_strength(features, btc_features, eth_features),
            self._liquidity_order_book(features),
        ]
        return signals

    def _build(self, features: MarketFeatures, strategy_id: str, score: Decimal, evidence: dict[str, object], entry: list[str], invalidation: list[str], explanation: str) -> StrategySignal:
        return StrategySignal(
            signal_id=new_id("sig"),
            strategy_id=strategy_id,
            symbol=features.symbol,
            timestamp=features.timestamp,
            score=score.quantize(Decimal("0.0001")),
            data_quality=features.data_quality,
            evidence={**evidence,"strategy_version":"3.4.0","qualified":score>0 or bool(evidence.get("veto"))},
            entry_conditions=entry,
            invalidation_conditions=invalidation,
            estimated_cost_bps=features.spread_bps or Decimal("25"),
            explanation=explanation,
        )

    def _volume_accumulation(self, features: MarketFeatures) -> StrategySignal:
        score = min(_score(features.relative_volume, Decimal("1.2"), Decimal("3.5")) + _score(features.volume_acceleration, Decimal("1.1"), Decimal("2.5")), Decimal("1"))
        return self._build(features, "A_VOLUME_ACCUMULATION", score, {"relative_volume": features.relative_volume, "volume_acceleration": features.volume_acceleration}, ["relative volume remains elevated", "price holds above VWAP"], ["relative volume falls below baseline", "close below support"], "Abnormal volume is appearing before a confirmed extension.")

    def _volatility_compression(self, features: MarketFeatures) -> StrategySignal:
        if features.bollinger_upper is None or features.bollinger_lower is None or features.bollinger_mid in (None, Decimal("0")):
            width = None
        else:
            width = (features.bollinger_upper - features.bollinger_lower) / features.bollinger_mid
        score = Decimal("1") - _score(width, Decimal("0.02"), Decimal("0.12")) if width is not None else Decimal("0")
        return self._build(features, "B_VOLATILITY_COMPRESSION", max(score, Decimal("0")), {"bollinger_width": width, "atr": features.atr}, ["range compression persists", "break above compression high with volume"], ["close below compression low"], "Volatility appears compressed, which can precede expansion.")

    def _resistance_breakout(self, features: MarketFeatures) -> StrategySignal:
        level = features.metadata.get("retest_level")
        previous = features.metadata.get("previous_close")
        low, close = features.metadata.get("last_low"), features.metadata.get("last_close")
        retest = bool(level and previous and low and close and previous>level and low<=level*Decimal("1.002") and close>=level)
        score=Decimal("0.8") if retest else Decimal(0)
        return self._build(features,"C_BREAKOUT_RETEST",score,{"resistance":level,"retest_confirmed":retest},["previous completed close above resistance","completed retest holds"],["close back below resistance"],"Completed-candle breakout and retest evidence.")

    def _momentum_acceleration(self, features: MarketFeatures) -> StrategySignal:
        trend_ok = features.ema_9 is not None and features.ema_21 is not None and features.ema_9 > features.ema_21
        score = _score(features.momentum, Decimal("0.001"), Decimal("0.025")) + (Decimal("0.25") if trend_ok else Decimal("0"))
        return self._build(features, "D_MOMENTUM_ACCELERATION", min(score, Decimal("1")), {"momentum": features.momentum, "ema_9": features.ema_9, "ema_21": features.ema_21}, ["momentum stays positive", "short EMA remains above medium EMA"], ["momentum turns negative"], "Momentum is strengthening without being treated as a calibrated probability.")

    def _failed_breakout(self, features: MarketFeatures) -> StrategySignal:
        high,close=features.metadata.get("last_high"),features.metadata.get("last_close")
        resistance=features.resistance
        failed=bool(high and close and resistance and high>resistance*Decimal("1.001") and close<resistance)
        return self._build(features,"E_FAILED_BREAKOUT_REJECTION",Decimal(0),{"veto":failed,"resistance":resistance,"high":high,"close":close},[],["failed resistance breakout"],"Resistance rejection veto; never opens a short position.")

    def _risk_off(self, features: MarketFeatures) -> StrategySignal:
        risk_off=bool(features.ema_21 and features.ema_50 and features.momentum is not None and features.ema_21<features.ema_50 and features.momentum<Decimal("-0.01"))
        higher=features.metadata.get('higher_timeframe_confirmation',{})
        confirmation_veto=bool(higher.get('veto'))
        return self._build(features,"F_MARKET_REGIME_RISK_OFF",Decimal(0),{"veto":risk_off or confirmation_veto,"higher_timeframe":higher,"regime":"RISK_OFF" if risk_off else "TREND" if features.ema_21 and features.ema_50 and features.ema_21>features.ema_50 else "RANGE"},[],["market regime risk off","higher timeframe confirmation unavailable or risk off"],"Market-regime entry veto and protective invalidation evidence.")


    def _relative_strength(self, features: MarketFeatures, btc_features: MarketFeatures | None, eth_features: MarketFeatures | None) -> StrategySignal:
        benchmark = [item.momentum for item in (btc_features, eth_features) if item and item.symbol!=features.symbol and item.momentum is not None]
        relative = None
        if features.momentum is not None and benchmark:
            relative = features.momentum - (sum(benchmark) / Decimal(len(benchmark)))
        score = _score(relative, Decimal("0.001"), Decimal("0.02"))
        return self._build(features, "G_RELATIVE_STRENGTH", score, {"relative_momentum": relative}, ["outperformance continues versus BTC/ETH"], ["relative momentum turns negative"], "Asset is outperforming the configured benchmark set.")

    def _liquidity_order_book(self, features: MarketFeatures) -> StrategySignal:
        imbalance_score = _score(features.order_book_imbalance, Decimal("0.05"), Decimal("0.45"))
        spread_penalty = _score(features.spread_bps, Decimal("10"), Decimal("150")) if features.spread_bps is not None else Decimal("0.5")
        score = max(imbalance_score - (spread_penalty / Decimal("2")), Decimal("0"))
        return self._build(features, "H_LIQUIDITY_ORDER_BOOK", score, {"imbalance": features.order_book_imbalance, "spread_bps": features.spread_bps}, ["bid pressure remains constructive", "spread remains acceptable"], ["spread widens", "book imbalance reverses"], "Order-book pressure is constructive after spread adjustment.")

