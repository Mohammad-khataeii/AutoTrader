from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from autotrader.research.diagnostics import TradeFailureAnalyzer, classify_trade
from autotrader.research.simulation import ResearchSimulation
from test_v4_research import fixture_bars


def diagnostic_fixture():
    bars = fixture_bars()
    sim = ResearchSimulation(bars)
    start = datetime.fromisoformat(bars[210].start)
    result = sim.run(
        start=start, end=datetime.fromisoformat(bars[-1].start), strategy_ids={"A_TREND_PULLBACK"}
    )
    return bars, result


def test_diagnostics_reconstruct_real_signals_costs_and_all_positions():
    bars, result = diagnostic_fixture()
    before = deepcopy(result)
    rows = TradeFailureAnalyzer(bars).analyze(result)
    assert result == before
    assert len(rows) == result["trades"] + len(result["open_positions_at_end"])
    assert sum((D(r["costs"]["fees"]) for r in rows), D(0)) == D(result["fees"])
    assert sum((D(r["net_pnl"]) for r in rows), D(0)) == sum(
        (D(f["realized_pnl"]) for f in result["fills"] if f["side"] == "SELL"), D(0)
    )
    assert all(r["signal_evidence"]["entry_eligible"] for r in rows)
    assert all(
        D(r["excursions"]["net_mfe_lower"]) <= D(r["excursions"]["net_mfe_upper"]) for r in rows
    )
    assert all("INSUFFICIENT_EVIDENCE" in r["classifications"] for r in rows)


def test_entry_features_ignore_future_market_changes_and_reject_wrong_provenance():
    bars, result = diagnostic_fixture()
    row = TradeFailureAnalyzer(bars).analyze(result)[0]
    cutoff = datetime.fromisoformat(row["entry_timestamp"])
    changed = [
        replace(b, high=str(D(b.high) * 10), volume="0")
        if datetime.fromisoformat(b.start) >= cutoff
        else b
        for b in bars
    ]
    analyzer = TradeFailureAnalyzer(changed)
    assert analyzer.feature("BTC-EUR", cutoff) == TradeFailureAnalyzer(bars).feature(
        "BTC-EUR", cutoff
    )
    first = deepcopy(result)
    first["fills"] = [f for f in first["fills"] if f["position_id"] == row["position_id"]]
    first["closed_positions"] = [
        p for p in first["closed_positions"] if p["position_id"] == row["position_id"]
    ]
    first["open_positions_at_end"] = []
    other = analyzer.analyze(first)[0]
    assert row["entry_features"] == other["entry_features"]
    assert row["signal_evidence"] == other["signal_evidence"]
    wrong = deepcopy(result)
    wrong["fills"][0]["feature_available_at"] = (cutoff + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="provenance"):
        TradeFailureAnalyzer(bars).analyze(wrong)


def test_rule_labels_have_exact_predicates_and_do_not_explain_loss_alone():
    bars, result = diagnostic_fixture()
    row = TradeFailureAnalyzer(bars).analyze(result)[0]
    row.update(
        regime="MODERATE_BULL",
        net_pnl="-100",
        first_target_net_return=".1",
        raw_entry_price="100",
        initial_stop="98",
        entry_quantity="1",
        round_trip_cost_fraction=".001",
        assumed_depth_utilization=".1",
        counterfactuals={},
    )
    row["entry_features"].update(ema_21="100", ema_50="99", atr="1")
    row["costs"].update(total_drag="0", spread_bps="10")
    row["excursions"]["completed_close_net_mfe"] = "-.1"
    row["exits"] = []
    assert set(classify_trade(row)) == {"INSUFFICIENT_EVIDENCE"}
    row["raw_entry_price"] = "103"
    row["costs"]["spread_bps"] = "26"
    row["first_target_net_return"] = "-.001"
    row["exits"] = [{"reason": "FAILED_BREAKOUT"}, {"reason": "TIME_EXIT"}]
    row["counterfactuals"] = {"one_bar_later": {"full_quantity_net_pnl": "-99"}}
    assert set(classify_trade(row)) == {
        "INSUFFICIENT_EVIDENCE",
        "ENTRY_TOO_LATE",
        "SPREAD_TOO_WIDE",
        "COST_EXCEEDS_EDGE",
        "FALSE_BREAKOUT",
        "TIMEOUT_EXIT",
        "PREMATURE_EXIT",
    }


def test_stop_target_collision_keeps_price_opportunity_censored():
    bars = fixture_bars()
    # The completed signal is unchanged. The entry bar touches both levels.
    bars[210] = replace(bars[210], high="150", low="50")
    sim = ResearchSimulation(bars)
    start = datetime.fromisoformat(bars[210].start)
    result = sim.run(start=start, end=start + timedelta(days=2), strategy_ids={"A_TREND_PULLBACK"})
    row = TradeFailureAnalyzer(bars).analyze(result)[0]
    assert row["exits"][0]["reason"] == "STOP_INTRABAR_CONSERVATIVE"
    assert row["excursions"]["stop_target_collisions"]
    assert D(row["excursions"]["net_mfe_lower"]) < 0
    assert D(row["excursions"]["net_mfe_upper"]) > 0
    assert not any(e["reason"] == "TAKE_PROFIT_CLOSE_IOC" for e in row["exits"])


def test_admission_target_is_bid_scenario_and_not_charged_a_second_spread():
    bars, result = diagnostic_fixture()
    rows = TradeFailureAnalyzer(bars).analyze(result)
    for row in rows:
        basis = D(row["entry_cost_basis"])
        quantity = D(row["entry_quantity"])
        target = D(row["initial_targets"][0])
        sell_factor = (1 - D(result["costs"]["fee_bps"]) / 10000) * (
            1 - D(result["costs"]["slippage_bps"]) / 10000
        )
        assert D(row["first_target_net_return"]) == target * sell_factor / (basis / quantity) - 1
        assert D(row["first_target_midpoint_touch_net_return"]) < D(row["first_target_net_return"])
        assert D(row["first_target_net_return"]) > 0  # Real admission already passed.


def test_net_excursion_includes_recorded_adverse_gap_execution():
    bars = fixture_bars()
    bars[213] = replace(bars[213], open="50", high="50.2", low="49.8", close="50.01")
    start = datetime.fromisoformat(bars[210].start)
    result = ResearchSimulation(bars).run(
        start=start, end=start + timedelta(days=5), strategy_ids={"A_TREND_PULLBACK"}
    )
    row = TradeFailureAnalyzer(bars).analyze(result)[0]
    exit_fill = row["exits"][-1]
    assert exit_fill["reason"] == "STOP_GAP"
    net_unit = D(exit_fill["price"]) - D(exit_fill["fee"]) / D(exit_fill["quantity"])
    actual_return = net_unit / (D(row["entry_cost_basis"]) / D(row["entry_quantity"])) - 1
    assert D(row["excursions"]["net_mae_known"]) <= actual_return
    assert D(row["excursions"]["net_mae_known"]) < D("-.5")


def test_counterfactual_cannot_replace_a_missing_bar_with_a_later_observation():
    bars, result = diagnostic_fixture()
    row = TradeFailureAnalyzer(bars).analyze(result)[0]
    end = datetime.fromisoformat(row["exits"][-1]["timestamp"])
    expected = end + timedelta(days=1)
    missing = [b for b in bars if datetime.fromisoformat(b.start) != expected]
    only = deepcopy(result)
    only["fills"] = [f for f in result["fills"] if f["position_id"] == row["position_id"]]
    only["closed_positions"] = [
        p for p in result["closed_positions"] if p["position_id"] == row["position_id"]
    ]
    only["open_positions_at_end"] = []
    alternative = TradeFailureAnalyzer(missing).analyze(only)[0]["counterfactuals"]["one_bar_later"]
    assert alternative["full_quantity_net_pnl"] is None
    assert alternative["reason"] == "missing_matched_chronological_observation"


def test_entry_cash_and_correlation_context_are_reconstructed_from_prior_events():
    bars, result = diagnostic_fixture()
    rows = TradeFailureAnalyzer(bars).analyze(result)
    curve = {r["timestamp"]: r for r in result["curve"]}
    for row in rows:
        prior = curve.get(row["entry_timestamp"])
        expected = prior["cash"] if prior else "500"
        assert D(row["entry_financial_context"]["cash_before_entry"]) == D(expected)
        assert row["entry_financial_context"]["position_count_before_entry"] == 0
        assert row["entry_correlation"]["maximum_observed_correlation"] is None
        assert row["entry_correlation"]["accepted"]
    sample = deepcopy(rows[0])
    sample["entry_correlation"]["maximum_observed_correlation"] = 0.8
    assert "CORRELATION_EXPOSURE" in classify_trade(sample)
