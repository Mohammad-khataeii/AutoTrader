"""Read-only trade attribution; never changes signals, fills or promotion policy.

OHLC extrema are liquidation-price bounds, NOT evidence of an executable fill.
Counterfactuals keep the recorded entry and use one finite-depth close-only IOC;
they are mechanism hypotheses, not a replay of the capital-constrained portfolio.
"""

from __future__ import annotations

import json
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from autotrader.allocation import allocation_advice
from autotrader.clock import at
from autotrader.domain import OrderBook, OrderBookLevel, Side
from autotrader.execution.pricing import exact, quote_execution
from autotrader.indicators import calculate_features, higher_timeframe_context
from autotrader.research.data import TIMEFRAMES, HistoricalBar, canonical, digest, load_dataset
from autotrader.research.strategies import REGISTRY, StrategyParameters, V4StrategyEngine

D = Decimal
ZERO = D(0)
RULE_VERSION = "4.2.0-diagnostics.4"


def classify_trade(row: dict[str, Any]) -> dict[str, str]:
    """Return labels AND their measurable predicates; labels are not causal proof."""
    labels = {
        "INSUFFICIENT_EVIDENCE": "OHLCV proxy: no historical L2, queue, intrabar path or per-position rejected-risk history"
    }
    f, costs = row["entry_features"], row["costs"]
    price, atr = D(row["raw_entry_price"]), D(str(f.get("atr") or 0))
    ema = D(str(f.get("ema_21") or 0))
    if atr > 0 and ema > 0 and (price - ema) / atr > 2:
        labels["ENTRY_TOO_LATE"] = "entry mid exceeds causal EMA21 by more than 2 ATR"
    if f.get("ema_21") and f.get("ema_50") and D(str(f["ema_21"])) < D(str(f["ema_50"])):
        labels["ADVERSE_TREND"] = "causal EMA21 below EMA50"
    if row["regime"] in {"BEAR", "LIQUIDITY_STRESS", "UNCERTAIN"}:
        labels["UNFAVORABLE_REGIME"] = "recorded entry regime is bearish, illiquid or uncertain"
    if row["regime"] == "RANGE" and row["strategy"] != "F_MEAN_REVERSION":
        labels["RANGE_NOISE"] = (
            "directional entry in recorded RANGE regime; not proof of a false signal"
        )
    reasons = {e["reason"] for e in row["exits"]}
    if "FAILED_BREAKOUT" in reasons:
        labels["FALSE_BREAKOUT"] = "recorded failed-breakout exit predicate fired"
    if "TIME_EXIT" in reasons:
        labels["TIMEOUT_EXIT"] = "recorded maximum-holding-time exit"
    if D(costs["spread_bps"]) > 25:
        labels["SPREAD_TOO_WIDE"] = "modeled entry spread exceeds 25 bps"
    if D(row["first_target_net_return"]) <= 0:
        labels["COST_EXCEEDS_EDGE"] = (
            "initial admission bid-target scenario is nonpositive after modeled entry and sell costs"
        )
    elif row["closed"] and D(row["net_pnl"]) < 0 <= D(row["net_pnl"]) + D(costs["total_drag"]):
        labels["COST_EXCEEDS_EDGE"] = (
            "loss changes sign adding modeled costs back at fixed recorded fills; not a no-cost portfolio replay"
        )
    stop_distance = price - D(row["initial_stop"])
    if stop_distance / price <= D(row["round_trip_cost_fraction"]):
        labels["STOP_TOO_TIGHT"] = (
            "initial stop distance no greater than modeled round-trip cost fraction"
        )
    if stop_distance * D(row["entry_quantity"]) > 5:
        labels["STOP_TOO_WIDE"] = "initial mid-to-stop quantity risk exceeds EUR5 (fees separate)"
    if row["assumed_depth_utilization"] is not None and D(row["assumed_depth_utilization"]) >= D(
        ".8"
    ):
        labels["LOW_LIQUIDITY"] = (
            "entry consumed at least 80% of modeled prior-volume depth; historical L2 unknown"
        )
    if (
        row["closed"]
        and D(row["net_pnl"]) < 0
        and D(row["excursions"]["completed_close_net_mfe"]) > 0
    ):
        labels["LATE_EXIT"] = (
            "earlier completed-close liquidation mark positive, final realized loss; alternative fill unproven"
        )
    correlation = row.get("entry_correlation", {}).get("maximum_observed_correlation")
    if correlation is not None and correlation >= 0.75:
        labels["CORRELATION_EXPOSURE"] = (
            "causal 20-return correlation at least .75 with an already-held position; diagnostic context, not proof of loss or a .90 balanced-cap violation"
        )
    later = row.get("counterfactuals", {}).get("one_bar_later")
    if (
        later
        and later.get("full_quantity_net_pnl") is not None
        and row["closed"]
        and D(later["full_quantity_net_pnl"]) > D(row["net_pnl"])
    ):
        labels["PREMATURE_EXIT"] = (
            "one-bar-later matched-entry IOC scenario improves P&L; hypothesis only, ignores intervening protective obligations"
        )
    return labels


class TradeFailureAnalyzer:
    def __init__(self, bars: list[HistoricalBar]) -> None:
        self.by_symbol: dict[str, list[Any]] = defaultdict(list)
        for bar in bars:
            self.by_symbol[bar.symbol].append(bar.candle())
        for candles in self.by_symbol.values():
            candles.sort(key=lambda c: c.timestamp)
            if len({c.timestamp for c in candles}) != len(candles):
                raise ValueError("duplicate_diagnostic_observations")
        self.times = {s: [c.timestamp for c in cs] for s, cs in self.by_symbol.items()}
        self._features: dict[tuple[str, datetime], Any] = {}

    def feature(self, symbol: str, when: datetime) -> Any:
        key = symbol, when
        if key in self._features:
            return self._features[key]
        cs = self.by_symbol[symbol]
        index = bisect_left(self.times[symbol], when)
        seconds = TIMEFRAMES[cs[0].timeframe]
        history = [
            c
            for c in cs[max(0, index - 240) : index]
            if c.timestamp + timedelta(seconds=seconds) <= when
        ]
        if len(history) < 50:
            raise ValueError("insufficient_causal_feature_history")
        f = calculate_features(history, ZERO, D(10))
        with at(when):
            f.metadata["higher_timeframe_confirmation"] = higher_timeframe_context(
                [
                    type(c)(
                        c.symbol,
                        c.timestamp,
                        c.open,
                        c.high,
                        c.low,
                        c.close,
                        c.volume,
                        timeframe=f"{seconds // 60}m",
                        source=c.source,
                    )
                    for c in history
                ]
            )
        self._features[key] = f
        return f

    def analyze(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        active: dict[str, dict[str, str]] = {}
        contexts: dict[str, dict[str, Any]] = {}
        cash = D(500)
        for fill in result["fills"]:
            identity = fill["position_id"]
            grouped[identity].append(fill)
            quantity = D(fill["quantity"])
            notional = exact(quantity * D(fill["price"]))
            if fill["side"] == "BUY":
                contexts[identity] = {
                    "cash_before_entry": str(cash),
                    "concurrent_positions": [dict(p) for p in active.values()],
                    "position_count_before_entry": len(active),
                    "reservation_model": "historical immediate IOC; no invented asynchronous queue reservation",
                }
                active[identity] = {
                    "position_id": identity,
                    "symbol": fill["symbol"],
                    "quantity": str(quantity),
                }
                cash -= notional + D(fill["fee"])
            else:
                cash += notional - D(fill["fee"])
                if identity not in active:
                    raise ValueError("exit_without_prior_recorded_entry")
                remaining = D(active[identity]["quantity"]) - quantity
                if remaining < 0:
                    raise ValueError("diagnostic_recorded_position_overfill")
                if remaining == 0:
                    del active[identity]
                else:
                    active[identity]["quantity"] = str(remaining)
        rows = [
            self._position(identity, fills, result, contexts[identity])
            for identity, fills in grouped.items()
        ]
        if len(rows) != len(result["closed_positions"]) + len(result["open_positions_at_end"]):
            raise ValueError("diagnostic_position_coverage_mismatch")
        return rows

    def _position(
        self,
        identity: str,
        fills: list[dict[str, Any]],
        result: dict[str, Any],
        entry_context: dict[str, Any],
    ) -> dict[str, Any]:
        buys = [f for f in fills if f["side"] == "BUY"]
        if len(buys) != 1:
            raise ValueError("one_recorded_entry_required")
        entry = buys[0]
        exits = sorted([f for f in fills if f["side"] == "SELL"], key=lambda f: f["timestamp"])
        symbol, opened = entry["symbol"], datetime.fromisoformat(entry["timestamp"])
        seconds = TIMEFRAMES[result["timeframe"]]
        candles, times = self.by_symbol[symbol], self.times[symbol]
        ix = bisect_left(times, opened)
        if ix == len(times) or times[ix] != opened:
            raise ValueError("missing_entry_observation")
        f = self.feature(symbol, opened)
        if (
            f.timestamp.isoformat() != entry["source_feature_start"]
            or datetime.fromisoformat(entry["feature_available_at"]) > opened
        ):
            raise ValueError("entry_feature_provenance_mismatch")
        params = StrategyParameters(**{k: D(v) for k, v in entry["parameters"].items()})
        signals = V4StrategyEngine(params).generate(
            f,
            self.feature("BTC-EUR", opened) if "BTC-EUR" in self.by_symbol else None,
            self.feature("ETH-EUR", opened) if "ETH-EUR" in self.by_symbol else None,
        )
        signal = next(s for s in signals if s.strategy_id == entry["strategy"])
        if not signal.evidence["entry_eligible"]:
            raise ValueError("recorded_signal_does_not_reproduce")
        existing_features = [
            self.feature(p["symbol"], opened) for p in entry_context["concurrent_positions"]
        ]
        advice = allocation_advice(
            {**f.metadata, "_feature_timestamp": f.timestamp.isoformat()},
            [
                {**other.metadata, "_feature_timestamp": other.timestamp.isoformat()}
                for other in existing_features
            ],
        )
        cost = {k: D(v) for k, v in result["costs"].items()}
        half, slip, fee = (
            cost["spread_bps"] / 20000,
            cost["slippage_bps"] / 10000,
            cost["fee_bps"] / 10000,
        )
        qty, price = D(entry["quantity"]), D(entry["price"])
        basis = qty * price + D(entry["fee"])
        raw = candles[ix].open
        atr = f.atr or raw * D(".02")
        stop = raw - atr * params.stop_atr
        targets = [raw + atr * params.target_atr * n for n in (1, 2, 3)]

        def liquidation(mid: Decimal) -> Decimal:
            return mid * (1 - half) * (1 - slip) * (1 - fee) / (basis / qty) - 1

        remaining = qty - sum((D(e["quantity"]) for e in exits), ZERO)
        end = (
            datetime.fromisoformat(exits[-1]["timestamp"])
            if exits and remaining == 0
            else datetime.fromisoformat(result["end_exclusive"])
        )
        known, lower, upper = [liquidation(raw)], [liquidation(raw)], [liquidation(raw)]
        closes, collisions = [], []
        # Exclude bars exited at their OPEN; a stop posted at bar END includes
        # only its known open in the lower bound, never the unknown later high.
        for c in candles[ix : bisect_left(times, end)]:
            close_at = c.timestamp + timedelta(seconds=seconds)
            stop_here = any(
                e["reason"].startswith("STOP_INTRABAR")
                and datetime.fromisoformat(e["timestamp"]) == close_at
                for e in exits
            )
            if stop_here:
                lower.append(liquidation(c.open))
                upper.append(liquidation(c.high))
                known.append(liquidation(c.open))
                if c.high * (1 - half) >= targets[0]:
                    collisions.append(
                        {
                            "bar_start": c.timestamp.isoformat(),
                            "rule": "recorded stop takes priority; high touch is not a fill",
                            "initial_target": str(targets[0]),
                        }
                    )
            else:
                lower.append(liquidation(c.high))
                upper.append(liquidation(c.high))
                known.append(liquidation(c.low))
                closes.append(liquidation(c.close))
        # Recorded executions are known even when an exit occurs at a gap OPEN
        # excluded from the held-candle interval. Never omit that adverse price
        # or charge spread/slippage a second time to an already executed VWAP.
        for exit_fill in exits:
            exit_quantity = D(exit_fill["quantity"])
            net_unit = (D(exit_fill["price"]) * exit_quantity - D(exit_fill["fee"])) / exit_quantity
            observed_return = net_unit / (basis / qty) - 1
            known.append(observed_return)
            lower.append(observed_return)
            upper.append(observed_return)
        realized = sum((D(e["realized_pnl"]) for e in exits), ZERO)
        total_drag = sum(
            (D(v.get(k, "0")) for v in fills for k in ("fee", "spread_cost", "slippage_cost")), ZERO
        )
        volume = D(str(f.metadata.get("last_volume", 0))) * cost["liquidity_fraction"]
        row: dict[str, Any] = {
            "position_id": identity,
            "strategy": entry["strategy"],
            "strategy_version": entry["strategy_version"],
            "asset": symbol,
            "regime": entry["regime"],
            "direction": "LONG",
            "entry_timestamp": entry["timestamp"],
            "entry_price": str(price),
            "raw_entry_price": str(raw),
            "entry_quantity": str(qty),
            "entry_cost_basis": str(basis),
            "entry_features": asdict(f),
            "signal_evidence": signal.evidence,
            "parameters": entry["parameters"],
            "parameter_hash": entry["parameter_hash"],
            "initial_stop": str(stop),
            "initial_targets": [str(t) for t in targets],
            "holding_bars": next(
                s.holding_bars for s in REGISTRY if s.strategy_id == entry["strategy"]
            ),
            "age_seconds": (end - opened).total_seconds(),
            "closed": remaining == 0,
            "remaining_quantity": str(remaining),
            "net_pnl": str(realized),
            "net_return_on_entry_basis": str(realized / basis),
            "exits": exits,
            "entry_financial_context": entry_context,
            "entry_correlation": asdict(advice),
            "risk_restrictions": {
                "entry_passed_original_gate": True,
                "global_equity_halt_observed_while_held": any(
                    c.get("risk_halted") and opened <= datetime.fromisoformat(c["timestamp"]) <= end
                    for c in result.get("curve", [])
                ),
                "per_position_rejected_intentions": "not recorded; aggregate run rejections are not attributed to individual positions",
            },
            "signal_invalidated": any(
                e["reason"] in {"FAILED_BREAKOUT", "REGIME_EXIT"} for e in exits
            ),
            "costs": {
                **result["costs"],
                "fees": str(sum((D(e["fee"]) for e in fills), ZERO)),
                "total_drag": str(total_drag),
                "spread": str(sum((D(e.get("spread_cost", 0)) for e in fills), ZERO)),
                "slippage": str(sum((D(e.get("slippage_cost", 0)) for e in fills), ZERO)),
            },
            "round_trip_cost_fraction": str(
                1 - (1 - half) * (1 - slip) * (1 - fee) / ((1 + half) * (1 + slip) * (1 + fee))
            ),
            "first_target_net_return": str(targets[0] * (1 - slip) * (1 - fee) / (basis / qty) - 1),
            "first_target_midpoint_touch_net_return": str(liquidation(targets[0])),
            "first_target_net_floor_return": str(targets[0] / (basis / qty) - 1),
            "target_semantics": "Admission treats target as bid scenario with sell fee/slippage; realized target orders enforce a net-unit floor. A midpoint touch is a separate hypothetical scenario, not the admission edge.",
            "assumed_depth_utilization": str(qty / volume) if volume else None,
            "excursions": {
                "net_mfe_lower": str(max(lower)),
                "net_mfe_upper": str(max(upper)),
                "net_mae_known": str(min(known)),
                "completed_close_net_mfe": str(max(closes)) if closes else "0",
                "stop_target_collisions": collisions,
                "interpretation": "whole-initial-lot mark bounds; ignores partial-exit cashflows; highs/lows do not prove fills; stop-bar adverse path is censored",
            },
        }
        counterfactuals = {}
        if exits and remaining == 0:
            for label, offset in (("two_bars_earlier", -2), ("one_bar_later", 1)):
                expected_time = end + timedelta(seconds=seconds * offset)
                index = bisect_left(times, expected_time)
                # Require the exact chronological event AND its prior depth bar.
                # Missing candles cannot silently turn one bar into several hours.
                if (
                    index <= ix
                    or index >= len(candles)
                    or times[index] != expected_time
                    or times[index] - times[index - 1] != timedelta(seconds=seconds)
                ):
                    counterfactuals[label] = {
                        "full_quantity_net_pnl": None,
                        "reason": "missing_matched_chronological_observation",
                    }
                    continue
                c = candles[index]
                if c.timestamp >= datetime.fromisoformat(result["end_exclusive"]):
                    counterfactuals[label] = {
                        "full_quantity_net_pnl": None,
                        "reason": "outside_recorded_run",
                    }
                    continue
                available = candles[index - 1].volume * cost["liquidity_fraction"]
                if available <= 0:
                    counterfactuals[label] = {
                        "full_quantity_net_pnl": None,
                        "reason": "no_assumed_liquidity",
                    }
                    continue
                book = OrderBook(
                    symbol,
                    c.timestamp,
                    (OrderBookLevel(c.open * (1 - half), available),),
                    (OrderBookLevel(c.open * (1 + half), available),),
                    "counterfactual-OHLCV-assumption",
                )
                with at(c.timestamp):
                    quote = quote_execution(
                        book,
                        Side.SELL,
                        qty,
                        fee_bps=cost["fee_bps"],
                        slippage_bps=cost["slippage_bps"],
                    )
                counterfactuals[label] = {
                    "timestamp": c.timestamp.isoformat(),
                    "fillable_quantity": str(quote.fillable_quantity),
                    "full_quantity_net_pnl": str(quote.net_cash_change - basis)
                    if quote.fillable_quantity == qty
                    else None,
                    "reason": "matched-entry whole-lot hypothetical IOC, not portfolio replay; ignores intervening protections and existing partial sales",
                }
        row["counterfactuals"] = counterfactuals
        row["classifications"] = classify_trade(row)
        return row


def analyze_run(root: Path, run: Path, output: Path) -> dict[str, Any]:
    from autotrader.research.artifacts import source_fingerprint

    analysis_source = source_fingerprint()[0]
    manifest = json.loads((run / "manifest.json").read_text())
    catalog = json.loads((root / "catalog.json").read_text())
    rows, sources = [], []
    for timeframe in ("5m", "15m"):
        datasets = [m for m in catalog["manifests"] if m["timeframe"] == timeframe]
        expected = {
            m["dataset_version"] for m in manifest["datasets"] if m["timeframe"] == timeframe
        }
        if {m["dataset_version"] for m in datasets} != expected:
            raise ValueError("diagnostics_require_exact_frozen_datasets")
        analyzer = TradeFailureAnalyzer([b for m in datasets for b in load_dataset(root, m)])
        for path in sorted(run.glob(f"{timeframe}-*-test.json")):
            result = json.loads(path.read_text())
            found = analyzer.analyze(result)
            for row in found:
                row["timeframe"] = timeframe
                row["run_id"] = manifest["run_id"]
                row["source_artifact"] = path.name
            rows.extend(found)
            sources.append(
                {"file": path.name, "sha256": digest(path.read_bytes()), "positions": len(found)}
            )
    report = {
        "schema": RULE_VERSION,
        "diagnostic_source_fingerprint": analysis_source,
        "historical_source_fingerprint": manifest["source_fingerprint"],
        "run_id": manifest["run_id"],
        "data_kind": "HISTORICAL_OHLCV_PROXY",
        "sources": sources,
        "positions": json.loads(json.dumps(rows, default=str)),
        "classification_counts": dict(
            Counter(label for row in rows for label in row["classifications"])
        ),
        "coverage": {
            "positions": len(rows),
            "closed": sum(r["closed"] for r in rows),
            "open": sum(not r["closed"] for r in rows),
        },
        "limitations": [
            "previously examined historical periods; no untouched holdout claim",
            "counterfactuals are hypotheses, never promotion evidence",
            "no L2, intrabar path, causal explanation of every loss, or reconstructed risk rejection history",
        ],
    }
    from autotrader.research.data import atomic_write

    if source_fingerprint()[0] != analysis_source:
        raise RuntimeError("diagnostic_source_changed_during_analysis")
    atomic_write(output, canonical(report))
    return report
