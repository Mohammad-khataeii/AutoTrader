from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import NormalDist
from typing import Any

from autotrader.domain import utc_now
from autotrader.research.artifacts import source_fingerprint
from autotrader.research.data import atomic_write, canonical, digest, load_dataset
from autotrader.research.simulation import Costs, ResearchSimulation
from autotrader.research.strategies import REGISTRY, VERSION, StrategyParameters

GRID = (
    StrategyParameters(relative_volume=Decimal("1.2"), stop_atr=Decimal("1.5"), target_atr=Decimal("1.5")),
    StrategyParameters(relative_volume=Decimal("1.5"), stop_atr=Decimal("2"), target_atr=Decimal("2")),
    StrategyParameters(relative_volume=Decimal("2"), stop_atr=Decimal("2.5"), target_atr=Decimal("3")),
)
STRATEGIES = [s.strategy_id for s in REGISTRY if not s.filter_only]


def compact(report: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key not in {"curve", "fills", "drawdown_curve", "closed_positions"}}


def bootstrap_interval(report: dict[str, Any], comparisons: int, iterations: int = 10000) -> list[float] | None:
    positions = report["closed_positions"]
    if not positions:
        return None
    groups: dict[str, list[float]] = defaultdict(list)
    for position in positions:
        opened = datetime.fromisoformat(position["opened_at"])
        week = (opened.date() - timedelta(days=opened.weekday())).isoformat()
        groups[week].append(float(position["realized_pnl"]))
    rows = [groups[week] for week in sorted(groups)]
    if len(rows) < 4:
        return None
    rng = random.Random(4000)
    outcomes = []
    for _ in range(iterations):
        sampled: list[list[float]] = []
        while len(sampled) < len(rows):
            start = rng.randrange(len(rows))
            sampled.extend(rows[(start + offset) % len(rows)] for offset in range(4))
        trades = [p for group in sampled[:len(rows)] for p in group]
        outcomes.append(sum(trades) / len(trades))
    outcomes.sort()
    alpha = .05 / comparisons
    return [outcomes[int((alpha / 2) * iterations)], outcomes[min(iterations - 1, math.ceil((1 - alpha / 2) * iterations) - 1)]]


def validation_gates(test: dict[str, Any], walk_forward: list[dict[str, Any]],
                     sensitivity: list[dict[str, Any]], training: list[dict[str, Any]],
                     *, comparisons: int, max_drawdown: float = .10,
                     minimum_trades: int = 60) -> dict[str, Any]:
    by_asset: dict[str, list[float]] = defaultdict(list)
    for position in test["closed_positions"]:
        by_asset[position["symbol"]].append(float(position["realized_pnl"]))
    interval = bootstrap_interval(test, comparisons)
    checks = {
        "positive_oos_net_return": test["net_profit"] > 0,
        "positive_oos_expectancy": test["expectancy"] > 0,
        "oos_profit_factor_above_1_2": test["profit_factor"] is not None and test["profit_factor"] > 1.2,
        "adequate_closed_positions": test["trades"] >= minimum_trades,
        "independent_entry_dates": test["effective_independent_entry_dates"] >= 30,
        "drawdown_limit": test["max_drawdown"] <= max_drawdown,
        "asset_diversity": sum(len(rows) >= 10 and sum(rows) > 0 for rows in by_asset.values()) >= 3,
        "regime_diversity": sum(float(pnl) > 0 for pnl in test["per_regime_realized_pnl"].values()) >= 2,
        "stable_walk_forward": len(walk_forward) >= 4 and sum(r["net_profit"] > 0 for r in walk_forward) >= 3,
        "cost_sensitivity": bool(sensitivity) and all(r["net_profit"] > 0 for r in sensitivity),
        "parameter_neighborhood": sum(r["net_profit"] > 0 and r["trades"] >= 10 for r in training) >= 2,
        "multiple_comparison_block_interval_positive": interval is not None and interval[0] > 0,
        "no_missing_position_data": test["rejections"].get("missing_position_market_data", 0) == 0,
    }
    return {"passed": all(checks.values()), "checks": checks,
        "failure_reasons": [name for name, passed in checks.items() if not passed],
        "weekly_four_block_bootstrap_interval": interval, "bootstrap_iterations": 10000,
        "multiple_comparisons": comparisons, "familywise_alpha": .05,
        "normal_familywise_z_reference": NormalDist().inv_cdf(1 - .05 / (2 * comparisons)),
        "minimum_trades": minimum_trades, "max_drawdown": max_drawdown,
        "uncertainty_limit": "Four blocks of active entry weeks approximate serial dependence; omitted no-entry weeks and sparse regimes limit inference. No independent-trade claim."}


def passive_benchmarks(sim: ResearchSimulation, start: datetime, end: datetime, costs: Costs) -> dict[str, Any]:
    result: dict[str, Any] = {"CASH": {"net_profit": 0, "total_return": 0, "max_drawdown": 0}}
    symbols = sorted({c.symbol for t, frame in sim.frames.items() if start <= t < end for c in frame})
    for name, selected in (("BTC_BUY_HOLD", ["BTC-EUR"]), ("ETH_BUY_HOLD", ["ETH-EUR"]), ("EQUAL_WEIGHT_CURRENT_UNIVERSE", symbols)):
        legs = []
        total = 0.0
        equity_by_time: dict[datetime, float] = defaultdict(float)
        for symbol in selected:
            candles = [c for t, frame in sorted(sim.frames.items()) if start <= t < end for c in frame if c.symbol == symbol]
            capital = 500 / len(selected)
            if not candles:
                total += capital
                continue
            opening = float(candles[0].open) * (1 + float(costs.spread_bps) / 20000) * (1 + float(costs.slippage_bps) / 10000)
            quantity = capital / (opening * (1 + float(costs.fee_bps) / 10000))
            for c in candles:
                equity_by_time[c.timestamp] += quantity * float(c.close)
            ending = quantity * float(candles[-1].close) * (1 - float(costs.spread_bps) / 20000) * (1 - float(costs.slippage_bps) / 10000) * (1 - float(costs.fee_bps) / 10000)
            total += ending
            legs.append({"symbol": symbol, "first_bar": candles[0].timestamp.isoformat(), "last_bar": candles[-1].timestamp.isoformat(), "ending_net_liquidation_value": ending})
        peak, dd = 500.0, 0.0
        # A shared timestamp is required for equal-weight drawdown. Missing legs
        # are disclosed; a partial aggregate must never masquerade as a crash.
        common = [t for t, frame in sim.frames.items() if start <= t < end and all(any(c.symbol == s for c in frame) for s in selected)]
        for t in sorted(common):
            value = equity_by_time[t]
            peak = max(peak, value)
            dd = max(dd, (peak - value) / peak)
        result[name] = {"net_profit": total - 500, "total_return": total / 500 - 1, "max_drawdown": dd,
            "legs": legs, "common_mark_observations": len(common),
            "assumption": "Unconstrained passive EUR500 reference; endpoint net liquidation costs estimated, not an executable bot allocation. Candidate remaining positions are separately disclosed as marks."}
    return result


def run_full(root: Path, catalog: dict[str, Any], *, timeframes: tuple[str, ...] = ("1d", "4h"),
             strategy_ids: tuple[str, ...] | None = None, grid: tuple[StrategyParameters, ...] = GRID,
             assets: tuple[str, ...] | None = None, experimental: bool = False) -> dict[str, Any]:
    from autotrader.research.experimental import EXPERIMENTAL_REGISTRY
    from autotrader.research.experimental import VERSION as EXPERIMENTAL_VERSION
    allowed = [s.strategy_id for s in EXPERIMENTAL_REGISTRY if not s.filter_only] if experimental else STRATEGIES
    algorithm_version = EXPERIMENTAL_VERSION if experimental else VERSION
    strategies = list(dict.fromkeys(strategy_ids if strategy_ids is not None else allowed))
    timeframes = tuple(dict.fromkeys(timeframes))
    grid = tuple({digest(canonical(p.payload())):p for p in grid}.values())
    if not strategies or any(s not in allowed for s in strategies) or not grid:
        raise ValueError("invalid_research_search_space")
    run_id = "research-" + utc_now().strftime("%Y%m%dT%H%M%S")
    output = root / "runs" / run_id
    output.mkdir(parents=True, exist_ok=False)
    source_hash, source_files = source_fingerprint()
    manifests = [m for m in catalog["manifests"] if m["timeframe"] in timeframes and (assets is None or m["base"] in assets)]
    manifest: dict[str, Any] = {"run_id": run_id, "created_at": utc_now().isoformat(), "datasets": manifests,
        "dataset_catalog_hash": digest(canonical(catalog)), "parameter_grid": [p.payload() for p in grid],
        "optimization": "training only; no validation/test retuning; failed candidates remain failed",
        "source_fingerprint": source_hash, "source_files": source_files,
        "purge_bars": 12, "embargo_bars": 1, "fixed_split_fractions": [.6, .2, .2],
        "comparisons": max(300,len(strategies) * len(grid) * len(timeframes) * 5) if experimental else len(strategies) * len(grid) * len(timeframes) * 5,
        "strategy_version":algorithm_version,"experimental":experimental,
        "costs": {"fee_bps": "10", "slippage_bps": "8", "spread_bps": "10", "volume_participation": ".01"}}
    manifest["holdout_disclosure"] = "Historical intervals can overlap V4 engineering studies. No untouched prospective holdout is claimed; frozen future pilot is separate."
    atomic_write(output / "manifest.json", canonical(manifest))
    summary: dict[str, Any] = {"run_id": run_id, "source_fingerprint": source_hash, "timeframes": {}, "passed_strategies": [], "failures": []}
    frozen_all = {}
    try:
        for timeframe in timeframes:
            bars = [bar for m in manifests if m["timeframe"] == timeframe for bar in load_dataset(root, m)]
            sim = ResearchSimulation(bars,experimental=experimental)
            times = sim.times
            if len(times) < 300:
                raise ValueError("insufficient_chronological_research_observations:" + timeframe)
            split1, split2 = int(len(times) * .6), int(len(times) * .8)
            train_end, val_start = times[split1 - 12], times[split1 + 1]
            val_end, test_start = times[split2 - 12], times[split2 + 1]
            end = times[-1] + timedelta(seconds=sim.seconds)
            trained = {}
            selected = {}
            for strategy in strategies:
                reports = [sim.run(start=times[0], end=train_end, strategy_ids={strategy}, parameters=p) for p in grid]
                best = max(range(len(grid)), key=lambda i: (reports[i]["net_profit"] - reports[i]["max_drawdown"] * 500) if reports[i]["trades"] >= 10 else -1e9)
                trained[strategy] = [compact(r) for r in reports]
                selected[strategy] = best
                print(f"TRAIN {timeframe} {strategy}: frozen grid index {best}", flush=True)
            frozen = {"timeframe": timeframe, "selected_grid_index": selected, "training_end": train_end.isoformat(),
                "validation_start": val_start.isoformat(), "validation_end_exclusive": val_end.isoformat(),
                "test_start": test_start.isoformat(), "test_end_exclusive": end.isoformat(), "grid": [p.payload() for p in grid]}
            frozen_all[timeframe] = frozen
            atomic_write(output / f"frozen-{timeframe}.json", canonical(frozen))
            frozen_hash = digest(canonical(frozen))
            results: dict[str, Any] = {}
            for strategy in strategies:
                params = grid[selected[strategy]]
                validation = sim.run(start=val_start, end=val_end, strategy_ids={strategy}, parameters=params)
                test = sim.run(start=test_start, end=end, strategy_ids={strategy}, parameters=params)
                sensitivity = [sim.run(start=test_start, end=end, strategy_ids={strategy}, parameters=params, costs=c)
                    for c in (replace(Costs(), fee_bps=Decimal(20)), replace(Costs(), slippage_bps=Decimal(20), spread_bps=Decimal(25)))]
                wf = []
                width = max(1, (len(times) - split2 - 1) // 4)
                for window in range(4):
                    test_index = split2 + 1 + width * window
                    next_index = split2 + 1 + width * (window + 1)
                    window_end = times[min(next_index, len(times) - 1)] if window < 3 else end
                    window_train_start = times[max(0, test_index - 1 - max(250, len(times) // 3))]
                    window_train_end = times[test_index - 13]
                    training = [sim.run(start=window_train_start, end=window_train_end, strategy_ids={strategy}, parameters=p) for p in grid]
                    frozen_index = max(range(len(grid)), key=lambda i: training[i]["net_profit"] - training[i]["max_drawdown"] * 500 if training[i]["trades"] >= 10 else -1e9)
                    report = sim.run(start=times[test_index], end=window_end, strategy_ids={strategy}, parameters=grid[frozen_index])
                    wf.append({**compact(report), "training_start": window_train_start.isoformat(),
                        "training_end_exclusive": window_train_end.isoformat(), "frozen_grid_index": frozen_index})
                gates = validation_gates(test, wf, sensitivity, trained[strategy], comparisons=manifest["comparisons"])
                gates["checks"]["positive_validation_net_profit"] = validation["net_profit"] > 0
                gates["checks"]["multiple_timeframe_validation"] = len(timeframes) >= 2
                gates["failure_reasons"] = [key for key, passed in gates["checks"].items() if not passed]
                gates["passed"] = not gates["failure_reasons"]
                result: dict[str, Any] = {"validation": compact(validation), "out_of_sample": compact(test), "walk_forward": wf,
                    "sensitivity": [compact(r) for r in sensitivity], "training_grid": trained[strategy],
                    "gates": gates, "frozen_parameters_sha256": frozen_hash}
                identity: dict[str, Any] = {"strategy_id": strategy, "strategy_version": algorithm_version,
                    "frozen_parameters": params.payload(), "parameter_hash": digest(canonical(params.payload())),
                    "source_fingerprint": source_hash, "dataset_fingerprint": digest(canonical([m["dataset_version"] for m in manifests if m["timeframe"] == timeframe])),
                    "research_run_id": run_id, "research_timeframe": timeframe,
                    "execution_assumptions_hash": digest(canonical(manifest["costs"])),
                    "validation_status": "RESEARCH_PASSED" if gates["passed"] else "RESEARCH_REJECTED"}
                result["candidate"] = {**identity, "candidate_id": digest(canonical(identity)),
                    "promotion_decision": "AWAITING_APPROVAL" if gates["passed"] else "RESEARCH_REJECTED",
                    "approved_at": None, "approving_authority": None}
                results[strategy] = result
                atomic_write(output / f"{timeframe}-{strategy}-test.json", canonical(test))
                atomic_write(output / f"{timeframe}-{strategy}-validation.json", canonical(validation))
                print(f"OOS {timeframe} {strategy}: PnL {test['net_profit']:.4f}, closed positions {test['trades']}, passed={gates['passed']}", flush=True)
            legacy = sim.run(start=test_start, end=end, strategy_ids=set(), legacy=True)
            passed = {s for s, r in results.items() if r["gates"]["passed"]}
            frozen_members = {s: grid[selected[s]] for s in strategies}
            ensemble = sim.run(start=test_start, end=end, strategy_ids=passed,
                member_parameters={s: frozen_members[s] for s in passed})
            ai_compare = sim.run(start=test_start, end=end, strategy_ids=set(strategies), member_parameters=frozen_members, ai_mode="RULE_PLUS_AI_MOCK")
            rules_compare = sim.run(start=test_start, end=end, strategy_ids=set(strategies), member_parameters=frozen_members)
            default_compare = sim.run(start=test_start, end=end, strategy_ids=set(strategies))
            atomic_write(output / f"{timeframe}-legacy-common-execution.json", canonical(legacy))
            atomic_write(output / f"{timeframe}-validated-ensemble.json", canonical(ensemble))
            atomic_write(output / f"{timeframe}-rules-comparison.json", canonical(rules_compare))
            atomic_write(output / f"{timeframe}-mock-ai-comparison.json", canonical(ai_compare))
            summary["timeframes"][timeframe] = {"frozen_parameters": frozen, "strategies": results,
                "benchmarks": {**passive_benchmarks(sim, test_start, end, Costs()),
                    "V3_4_SIGNALS_COMMON_EXECUTION": compact(legacy), "VALIDATED_ENSEMBLE": compact(ensemble),
                    ("EXPERIMENTAL_COMMON_PARAMETERS" if experimental else "V4_RUNTIME_DEFAULT_PARAMETERS"): compact(default_compare), ("EXPERIMENTAL_INDEPENDENTLY_FROZEN_PARAMETERS" if experimental else "V4_1_INDEPENDENTLY_FROZEN_PARAMETERS"): compact(rules_compare)},
                "mock_ai_comparison": {"RULE_ONLY": compact(rules_compare), "RULE_PLUS_AI_MOCK": compact(ai_compare),
                    "conclusion": "Matched deterministic mock integration only; no predictive AI edge is established"}}
        common_passed = set.intersection(*[{s for s, r in result["strategies"].items() if r["gates"]["passed"]} for result in summary["timeframes"].values()])
        summary["passed_strategies"] = sorted(common_passed)
        # Global promotion requires the intersection, not a strategy that passed
        # only one timeframe. Replace any per-timeframe provisional ensemble.
        for timeframe, result in summary["timeframes"].items():
            local_passed = {s for s, r in result["strategies"].items() if r["gates"]["passed"]}
            if local_passed != common_passed:
                bars = [bar for m in manifests if m["timeframe"] == timeframe for bar in load_dataset(root, m)]
                sim = ResearchSimulation(bars,experimental=experimental)
                frozen = result["frozen_parameters"]
                ensemble = sim.run(start=datetime.fromisoformat(frozen["test_start"]),
                    end=datetime.fromisoformat(frozen["test_end_exclusive"]), strategy_ids=common_passed,
                    member_parameters={s: StrategyParameters(**{k: Decimal(v) for k, v in frozen["grid"][frozen["selected_grid_index"][s]].items()}) for s in common_passed})
                result["benchmarks"]["VALIDATED_ENSEMBLE"] = compact(ensemble)
                atomic_write(output / f"{timeframe}-validated-ensemble.json", canonical(ensemble))
        summary["verdict"] = "VALIDATED_CANDIDATES_REQUIRE_REVIEW" if common_passed else "NO STRATEGY PASSED VALIDATION"
    except Exception as exc:
        summary["failures"].append({"type": type(exc).__name__, "error": str(exc)})
        summary["verdict"] = "RESEARCH_FAILED"
        atomic_write(output / "summary.json", canonical(summary))
        raise
    if source_fingerprint()[0] != source_hash:
        summary["verdict"] = "RESEARCH_SOURCE_CHANGED"
        summary["failures"].append({"type":"SourceChanged","error":"Source changed during study; no pointer published"})
        atomic_write(output / "summary.json", canonical(summary))
        raise RuntimeError("research_source_changed_during_study")
    atomic_write(output / "summary.json", canonical(summary))
    atomic_write(root / ("latest-experimental-run.json" if experimental else "latest-run.json"), canonical({"run_id": run_id, "summary": (output / "summary.json").relative_to(root).as_posix(),
        "summary_sha256": digest(canonical(summary)), "verdict": summary["verdict"]}))
    return summary
