from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from autotrader.domain import DataQuality, MarketFeatures
from autotrader.indicators import _ema, _ema_series
from autotrader.research.regimes import Regime, classify
from autotrader.research.strategies import REGISTRY, V4StrategyEngine


def features() -> MarketFeatures:
    return MarketFeatures("BTC-EUR", datetime(2025, 1, 1, tzinfo=UTC), "1d", DataQuality.GOOD,
        {"last_close": D(103), "last_low": D(101), "last_high": D(104), "previous_close": D(102),
         "return_20": D(".1"), "retest_level": D(106), "prior_bollinger_width": D(".08")},
        ema_9=D(102), ema_21=D(101), ema_50=D(100), atr=D(2), vwap=D(102),
        relative_volume=D(2), momentum=D(".01"), spread_bps=D(10),
        bollinger_upper=D(110), bollinger_mid=D(100), bollinger_lower=D(90), resistance=D(105))


def test_regime_uses_only_causal_benchmarks_and_quality() -> None:
    f = features()
    assert classify(f).regime is Regime.MODERATE_BULL
    future = replace(f, symbol="ETH-EUR", timestamp=f.timestamp + timedelta(days=1), ema_21=D(90))
    assert classify(f, eth=future).evidence["benchmark_symbols"] == []
    assert classify(replace(f, spread_bps=D(100))).regime is Regime.LIQUIDITY_STRESS
    assert classify(replace(f, ema_21=D(90), ema_50=D(100), metadata={**f.metadata, "last_close": D(95)})).regime is Regime.BEAR
    assert classify(replace(f, data_quality=DataQuality.INVALID)).regime is Regime.UNCERTAIN


def test_explicit_eligibility_independent_configuration_and_risk_off() -> None:
    f = features()
    signals = V4StrategyEngine(enabled={"D_VOLUME_ACCUMULATION"}).generate(f)
    assert len(signals) == 8 and len(REGISTRY) == 8
    assert [s.strategy_id for s in signals if s.evidence["entry_eligible"]] == ["D_VOLUME_ACCUMULATION"]
    bear = replace(f, ema_21=D(90), ema_50=D(100))
    signals = V4StrategyEngine().generate(bear)
    assert not any(s.evidence["entry_eligible"] for s in signals)
    assert next(s for s in signals if s.strategy_id == "H_RISK_OFF_FILTER").evidence["veto"]
    # A continuous score or compression alone is never sufficient to enter.
    quiet = replace(f, relative_volume=D(1), metadata={**f.metadata, "last_low": D(103)})
    assert not any(s.evidence["entry_eligible"] for s in V4StrategyEngine().generate(quiet))


def test_linear_ema_series_matches_every_original_prefix_exactly() -> None:
    values = [D(100) + D(i % 9) / 7 for i in range(240)]
    for period in (9, 12, 21, 26, 50, 200):
        assert _ema_series(values, period) == [_ema(values[:i], period) for i in range(period, len(values) + 1)]
