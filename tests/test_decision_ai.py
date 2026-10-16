from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import SecretStr

from autotrader.ai import MockAIProvider, OpenAIProvider
from autotrader.config import AIProvider, Settings
from autotrader.decision import DecisionEngine
from autotrader.domain import (
    Candle,
    DataQuality,
    DecisionAction,
    StrategySignal,
    TradingPair,
    new_id,
    utc_now,
)
from autotrader.indicators import calculate_features
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.portfolio import Portfolio
from autotrader.risk import RiskEngine, RiskLimits
from autotrader.strategies import BreakoutStrategyEngine


@pytest.mark.asyncio
async def test_ai_never_overrides_risk_limits() -> None:
    pair = TradingPair("BTC-EUR", "BTC", "EUR")
    start = utc_now()-timedelta(minutes=240)
    candles = []
    for index in range(240):
        close = Decimal("100") + Decimal(index)
        candles.append(Candle(pair.symbol, start + timedelta(minutes=index), close - Decimal('.1'), close + Decimal('.2'), close - Decimal('.2'), close, Decimal("100") + index))
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
            evidence={"test": "force risk path", "strategy_version":"4.0.0", "entry_eligible":True},
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
async def test_openai_budget_survives_provider_restart(pg_repo: PersistentTradingRepository) -> None:
    settings_obj = Settings(environment="test",ai_provider=AIProvider.OPENAI,openai_api_key=SecretStr("test-no-network"),
        ai_model="gpt-6.1-sol",ai_input_price_per_million=Decimal(2),
        ai_cached_input_price_per_million=Decimal("0.2"),ai_cache_write_price_per_million=Decimal("2.5"),ai_output_price_per_million=Decimal(10))
    await pg_repo.initialize_portfolio(Decimal(500))
    request = await pg_repo.reserve_ai_budget(Decimal(10),settings_obj.ai_model,"BTC-EUR",{})
    assert request is not None
    await pg_repo.finish_ai_request(request,cost=Decimal(10),input_tokens=100,output_tokens=100)
    features = calculate_features([Candle("BTC-EUR",utc_now()-timedelta(minutes=60-index),
        Decimal(1),Decimal(2),Decimal(1),Decimal(1),Decimal(1)) for index in range(60)])
    provider = OpenAIProvider(settings_obj,pg_repo)
    assessment = await provider.assess(features,[])
    assert assessment.failed
    assert assessment.assessment == "AI monthly budget exhausted or reserved."
    assert (await pg_repo.ai_budget_status())["spent_usd"] == "10.00000000"
