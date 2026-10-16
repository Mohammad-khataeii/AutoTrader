from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from autotrader.domain import Candle
from autotrader.indicators import calculate_features
from autotrader.research.context import completed_context
from autotrader.research.experimental import (
    EXPERIMENTAL_REGISTRY,
    VERSION,
    ExperimentalStrategyEngine,
)
from autotrader.research.strategies import REGISTRY


def candles():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Candle(
            "BTC-EUR",
            start + timedelta(minutes=5 * i),
            D(100) + D(i) / 100,
            D(101) + D(i) / 100,
            D(99) + D(i) / 100,
            D("100.1") + D(i) / 100,
            D(1000),
            timeframe="5m",
        )
        for i in range(720)
    ]


def test_complete_context_is_aligned_causal_and_rejects_missing_groups():
    cs = candles()
    as_of = cs[-1].timestamp + timedelta(minutes=5)
    first = completed_context(cs, as_of)
    assert first["ready"] and first["60m"]["complete_bars"] == 60
    assert first["15m"]["complete_bars"] == 240
    future = replace(cs[-1], timestamp=as_of, close=D(999), high=D(999))
    assert completed_context(cs + [future], as_of) == first
    assert not completed_context(cs[:599], cs[599].timestamp)["ready"]
    missing = completed_context(cs[:100] + cs[101:], as_of)
    assert missing["60m"]["complete_bars"] == 59
    assert not completed_context(cs[:-2], as_of)["15m"]["ready"]


def test_experimental_versions_preserve_originals_and_d2_cannot_enter():
    assert all(s.version == "4.0.0" for s in REGISTRY)
    assert all(s.version == VERSION for s in EXPERIMENTAL_REGISTRY)
    cs = candles()
    f = calculate_features(cs[-240:], D(0), D(10))
    f.metadata["experimental_context"] = completed_context(
        cs, cs[-1].timestamp + timedelta(minutes=5)
    )
    signals = ExperimentalStrategyEngine().generate(f, f, f)
    d2 = next(s for s in signals if s.strategy_id == "D2_MOMENTUM_QUALITY")
    assert d2.score == 0 and not d2.evidence["entry_eligible"]
    f.metadata["experimental_context"] = {}
    assert not any(
        s.evidence["entry_eligible"] for s in ExperimentalStrategyEngine().generate(f, f, f)
    )


def test_momentum_filter_vetoes_extension_even_with_strong_relative_performance():
    cs = candles()
    f = calculate_features(cs[-240:], D(0), D(10))
    f.metadata["experimental_context"] = completed_context(
        cs, cs[-1].timestamp + timedelta(minutes=5)
    )
    f.metadata["last_close"] = f.ema_21 + f.atr * 3
    signals = ExperimentalStrategyEngine().generate(f, f, f)
    assert next(s for s in signals if s.strategy_id == "D2_MOMENTUM_QUALITY").evidence["veto"]
