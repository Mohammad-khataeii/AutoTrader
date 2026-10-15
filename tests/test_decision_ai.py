from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr

from autotrader.ai import MockAIProvider, OpenAIProvider
from autotrader.config import AIProvider, Settings
from autotrader.decision import DecisionEngine
from autotrader.domain import (
    AIAssessment,
    Candle,
    DataQuality,
    DecisionAction,
    StrategySignal,
    TradingDecision,
    TradingPair,
    new_id,
    utc_now,
)
from autotrader.indicators import calculate_features
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.portfolio import Portfolio
from autotrader.risk import RiskEngine, RiskLimits
from autotrader.strategies import BreakoutStrategyEngine


@pytest.mark.asyncio
async def test_ai_never_overrides_risk_limits() -> None:
    pair = TradingPair("BTC-EUR", "BTC", "EUR")
    start = utc_now()
    candles = []
    for index in range(240):
        close = Decimal("100") + Decimal(index)
        candles.append(Candle(pair.symbol, start + timedelta(minutes=index), close - 1, close + 2, close - 2, close, Decimal("100") + index))
    features = calculate_features(candles)
    features.metadata["last_price"] = Decimal("340")
    signals = BreakoutStrategyEngine().generate(features)
    signals.append(
        StrategySignal(
            signal_id=new_id("sig"),
            strategy_id="TEST_FORCE_ENTRY",
            symbol=pair.symbol,
            timestamp=utc_now(),
            score=Decimal("2"),
            data_quality=DataQuality.GOOD,
            evidence={"test": "force risk path"},
            entry_conditions=["test"],
            invalidation_conditions=["test"],
            estimated_cost_bps=Decimal("10"),
            explanation="Synthetic strong signal for risk gating.",
        )
    )
    ai = await MockAIProvider().assess(features, signals)
    engine = DecisionEngine(RiskEngine(RiskLimits(max_position_size=Decimal("10"))), default_quote_amount=Decimal("75"))
    decision = engine.decide(pair, features, signals, Portfolio(Decimal("500")), ai)
    assert decision.action is DecisionAction.WAIT
    assert not decision.accepted
    assert decision.rejected_reason is not None
    assert "position_size" in decision.rejected_reason


@pytest.mark.asyncio
async def test_openai_budget_survives_provider_restart(tmp_path: Any) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'ai.db'}"
    settings_obj = Settings(
        database_url=database_url,
        ai_provider=AIProvider.OPENAI,
        openai_api_key=SecretStr("test-key"),
        ai_monthly_budget_usd=Decimal("10"),
    )
    engine = make_engine(settings_obj)
    await create_schema(engine)
    repo = PersistentTradingRepository(make_session_factory(engine))
    pair = TradingPair("BTC-EUR", "BTC", "EUR")
    features = calculate_features([Candle(pair.symbol, utc_now() + timedelta(minutes=index), Decimal("1"), Decimal("2"), Decimal("1"), Decimal("1"), Decimal("1")) for index in range(60)])
    previous_ai = AIAssessment(
        assessment_id=new_id("ai"),
        symbol=pair.symbol,
        timestamp=utc_now(),
        provider="openai",
        model="test-model",
        suggested_action=DecisionAction.WAIT,
        assessment="already spent",
        supporting_evidence=[],
        contradicting_evidence=[],
        identified_risks=[],
        suggested_entry_conditions=[],
        suggested_invalidation_conditions=[],
        uncertainty="high",
        explanation="fixture",
        estimated_cost_usd=Decimal("10"),
    )
    decision = TradingDecision(
        decision_id=new_id("dec"),
        symbol=pair.symbol,
        timestamp=utc_now(),
        action=DecisionAction.WAIT,
        signal_ids=[],
        ai_assessment_id=previous_ai.assessment_id,
        proposed_quote_amount=Decimal("0"),
        proposed_quantity=Decimal("0"),
        entry_price=None,
        stop_loss=None,
        take_profit_targets=(),
        accepted=False,
        rejected_reason="fixture",
        explanation="fixture",
    )
    await repo.store_analysis([], previous_ai, decision)

    restarted_provider = OpenAIProvider(settings_obj, repo)
    assessment = await restarted_provider.assess(features, [])

    assert assessment.failed
    assert assessment.assessment == "AI monthly budget exhausted."
    await engine.dispose()
