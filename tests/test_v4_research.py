from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from autotrader.domain import DataQuality
from autotrader.execution.postings import closing_posting
from autotrader.research.data import HistoricalBar
from autotrader.research.simulation import ResearchSimulation
from autotrader.research.workflow import validation_gates


def fixture_bars() -> list[HistoricalBar]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    result = []
    for i in range(270):
        p = D(100) + D(i) / 100
        result.append(HistoricalBar("unit-causal-fixture", "BTC-EUR", "BTC", "EUR",
            (start + timedelta(days=i)).isoformat(), "1d", str(p), str(p + D(".2")), str(p - D(".2")),
            str(p + D(".01")), "1000", start.isoformat(), ()))
    return result


def test_shared_posting_proportional_release_and_final_dust() -> None:
    first = closing_posting(D(3), D("100.01"), D(1), D(40), D(".04"))
    final = closing_posting(first.remaining_quantity, first.remaining_basis, D(2), D(82), D(".082"))
    assert first.released_basis + final.released_basis == D("100.01")
    assert first.realized_pnl + final.realized_pnl == D("21.868")
    assert final.remaining_quantity == 0 and final.remaining_basis == 0


def test_research_is_deterministic_causal_and_can_hold_cash() -> None:
    bars = fixture_bars()
    sim = ResearchSimulation(bars)
    start = datetime.fromisoformat(bars[210].start)
    end = datetime.fromisoformat(bars[-1].start) + timedelta(days=1)
    cash = sim.run(start=start, end=end, strategy_ids=set())
    assert cash["net_profit"] == 0 and cash["fills"] == []
    assert all(row["cash"] == "500" for row in cash["curve"])
    first = sim.run(start=start, end=end, strategy_ids={"A_TREND_PULLBACK"})
    repeated = sim.run(start=start, end=end, strategy_ids={"A_TREND_PULLBACK"})
    assert first == repeated and first["fills_count"] > 0
    for fill in first["fills"]:
        if fill["side"] == "BUY":
            assert datetime.fromisoformat(fill["feature_available_at"]) <= datetime.fromisoformat(fill["timestamp"])
            assert datetime.fromisoformat(fill["source_feature_start"]) < datetime.fromisoformat(fill["timestamp"])
    assert all(row["open_positions"] <= 3 and D(row["cash"]) >= 150 for row in first["curve"])
    prefix = ResearchSimulation(bars[:240])
    cutoff = datetime.fromisoformat(bars[240].start)
    assert sim.run(start=start, end=cutoff, strategy_ids={"A_TREND_PULLBACK"}) == prefix.run(start=start, end=cutoff, strategy_ids={"A_TREND_PULLBACK"})


def test_no_trade_or_tiny_sample_cannot_pass_validation() -> None:
    sim = ResearchSimulation(fixture_bars())
    result = sim.run(start=sim.times[210], end=sim.times[-1], strategy_ids=set())
    gates = validation_gates(result, [], [], [], comparisons=180)
    assert not gates["passed"]
    assert "adequate_closed_positions" in gates["failure_reasons"]
    assert "multiple_comparison_block_interval_positive" in gates["failure_reasons"]


def test_full_candle_quality_cannot_remove_an_entry_before_the_range_is_known() -> None:
    bars = fixture_bars()
    bars[210] = replace(bars[210], high="200", low="50", quality_flags=("SUSPICIOUS_RANGE",))
    sim = ResearchSimulation(bars)
    start = datetime.fromisoformat(bars[210].start)
    result = sim.run(start=start, end=start+timedelta(days=1), strategy_ids={"A_TREND_PULLBACK"})
    assert any(fill["side"] == "BUY" and fill["timestamp"] == start.isoformat() for fill in result["fills"])
    assert result["net_profit"] < 0
    assert sim.features[start+timedelta(days=1)]["BTC-EUR"].data_quality is DataQuality.INVALID


def test_legacy_comparison_obeys_the_same_known_data_quality_gate() -> None:
    bars = fixture_bars()
    bars[210] = replace(bars[210], high="200", low="50", quality_flags=("SUSPICIOUS_RANGE",))
    sim = ResearchSimulation(bars)
    start = datetime.fromisoformat(bars[211].start)
    result = sim.run(start=start, end=start+timedelta(days=1), strategy_ids=set(), legacy=True)
    assert result["fills"] == []
    assert result["rejections"]["data_quality_or_history"] == 1


def test_entry_liquidity_does_not_see_future_bar_volume() -> None:
    bars = fixture_bars()
    changed = list(bars)
    changed[210] = replace(changed[210], volume='0')
    start = datetime.fromisoformat(bars[210].start)
    left = ResearchSimulation(bars).run(start=start,end=start+timedelta(days=1),strategy_ids={'A_TREND_PULLBACK'})
    right = ResearchSimulation(changed).run(start=start,end=start+timedelta(days=1),strategy_ids={'A_TREND_PULLBACK'})
    assert [f for f in left['fills'] if f['side']=='BUY'] == [f for f in right['fills'] if f['side']=='BUY']
    assert any(f['side']=='BUY' for f in left['fills'])


def test_ensemble_uses_exact_frozen_parameters_and_refuses_missing_members() -> None:
    import pytest

    from autotrader.research.strategies import StrategyParameters
    sim = ResearchSimulation(fixture_bars())
    start, end = sim.times[210], sim.times[-1]
    p = StrategyParameters(stop_atr=D('2.5'),target_atr=D('3'))
    individual = sim.run(start=start,end=end,strategy_ids={'A_TREND_PULLBACK'},parameters=p)
    ensemble = sim.run(start=start,end=end,strategy_ids={'A_TREND_PULLBACK'},member_parameters={'A_TREND_PULLBACK':p})
    assert individual['fills']==ensemble['fills']
    assert individual['curve']==ensemble['curve']
    assert all(f['parameters']==p.payload() for f in ensemble['fills'] if f['side']=='BUY')
    with pytest.raises(ValueError,match='every_member'):
        sim.run(start=start,end=end,strategy_ids={'A_TREND_PULLBACK'},member_parameters={})


def test_unfinished_higher_timeframe_candles_cannot_change_historical_confirmation() -> None:
    from autotrader.clock import at
    from autotrader.indicators import higher_timeframe_context
    candles = [b.candle() for b in fixture_bars()]
    # Same four-bar aggregation used at runtime, with normalized primary duration.
    candles = [replace(c,timeframe='1440m') for c in candles]
    cutoff = candles[240].timestamp
    with at(cutoff):
        known = higher_timeframe_context(candles[:240])
        assert known['available']
        mutated = [replace(c,close=D('999999'),high=D('999999')) if c.timestamp>=cutoff else c for c in candles]
        assert higher_timeframe_context(mutated)==known
        assert higher_timeframe_context(candles)==known


def test_five_minute_decisions_do_not_change_when_future_candles_change() -> None:
    start=datetime(2024,1,1,tzinfo=UTC)
    bars=[replace(b,timeframe='5m',start=(start+timedelta(minutes=5*i)).isoformat()) for i,b in enumerate(fixture_bars())]
    cutoff=start+timedelta(minutes=5*240)
    future=[replace(b,close='999999',high='999999',volume='999999') if datetime.fromisoformat(b.start)>=cutoff else b for b in bars]
    original=ResearchSimulation(bars).run(start=start+timedelta(minutes=5*210),end=cutoff,strategy_ids={'A_TREND_PULLBACK'})
    changed=ResearchSimulation(future).run(start=start+timedelta(minutes=5*210),end=cutoff,strategy_ids={'A_TREND_PULLBACK'})
    assert original==changed and original['timeframe']=='5m'
