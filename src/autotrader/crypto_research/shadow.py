"""Public-only prospective discovery and chronological challenger evaluation."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from autotrader.domain import Side, quantize_down, utc_now
from autotrader.execution.pricing import book_payload, quote_execution
from autotrader.indicators import calculate_features
from autotrader.market_data.revolut import MarketDataError, RateLimitDeferred
from autotrader.opportunity.discovery import rank_markets
from autotrader.opportunity.engine import SuccessorOpportunityEngine
from autotrader.opportunity.features import enrich
from autotrader.personal_paper.admission import apply, completed_context
from autotrader.personal_paper.policy import fingerprint
from autotrader.personal_paper.selection import reviewed_signal
from autotrader.research.data import canonical, digest

from .audit import candle, timestamp
from .context import PEERS, STEP, VERSION, benchmark_context, cutoff, entry_context, window
from .replay import INSUFFICIENT, estimate, replay

A3 = "A3_COST_AWARE_CONTINUATION"
FEE, SLIP, BUDGET = D(10), D(8), D(700)
VARIANTS = (
    "incumbent_a3_setup",
    "shared_macro",
    "a3_confirmation",
    "combined_continuation",
    "range_reclaim",
    "rejected_by_combined_probe",
)
STRESS = (0, 20, 50)


def recipe_hash() -> str:
    paths = ("__main__.py", "audit.py", "context.py", "replay.py", "shadow.py")
    return digest(
        canonical(
            {
                "incumbent_fingerprint": fingerprint(),
                **{name: digest(Path(__file__).with_name(name).read_bytes()) for name in paths},
            }
        )
    )


def registration(
    start: datetime, development_end: datetime, holdout_end: datetime, shadow_end: datetime
) -> dict:
    now = utc_now()
    if not now <= start < development_end < holdout_end < shadow_end:
        raise ValueError("future_chronological_registration_required")
    return {
        "schema": VERSION,
        "registered_at": now.isoformat(),
        "recipe_sha256": recipe_hash(),
        "start": start.isoformat(),
        "development_end": development_end.isoformat(),
        "holdout_end": holdout_end.isoformat(),
        "shadow_end": shadow_end.isoformat(),
        "budget_eur": str(BUDGET),
        "variants": VARIANTS,
        "candidate": "combined_continuation",
        "comparison": "incumbent_a3_setup",
        "authority": "RESEARCH_ONLY",
    }


def write_record(path: Path, record: dict, *, replace: bool = False) -> None:
    """Publish complete files atomically; historical capture names are write-once."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(
                json.dumps(record, default=str, allow_nan=False, sort_keys=True).encode() + b"\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
            if replace:
                temp.replace(path)
            else:
                os.link(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def _quote(market, stop: D, target: D, horizon: int, observed_at: datetime) -> dict | None:
    pair, book, metrics = market.pair, market.order_book, market.metrics
    bid, ask = metrics.best_bid, metrics.best_ask
    if (
        not 0 < stop < bid < ask < target
        or metrics.spread_bps > 25
        or not timedelta(0) <= observed_at - book.timestamp <= timedelta(seconds=15)
    ):
        return None
    quantity = quantize_down(BUDGET / (ask * (1 + (FEE + SLIP) / 10000)), pair.quantity_step)
    buy = quote_execution(
        book,
        Side.BUY,
        quantity,
        quantity_step=pair.quantity_step,
        fee_bps=FEE,
        slippage_bps=SLIP,
        quote_budget=BUDGET,
        participation=D(".25"),
        limit_price=ask * (1 + SLIP / 10000) * (1 + D(".0025")),
    )
    if buy.fillable_quantity != quantity or buy.gross_notional < pair.min_order_quote:
        return None
    sell = quote_execution(
        book,
        Side.SELL,
        quantity,
        quantity_step=pair.quantity_step,
        fee_bps=FEE,
        slippage_bps=SLIP,
        participation=D(".25"),
        limit_price=bid * D(".9975"),
    )
    if sell.fillable_quantity != quantity:
        return None
    # Today's depth is used only as an adverse cost assumption at the proposed levels.
    exit_factor = (1 - (SLIP + sell.depth_impact_bps + D(20)) / 10000) * (1 - FEE / 10000)
    risk = -buy.net_cash_change - stop * quantity * exit_factor
    reward = target * quantity * exit_factor + buy.net_cash_change
    if not 0 < risk <= 35 or reward < risk:
        return None
    return {
        "entry": str(buy.vwap),
        "quantity": str(quantity),
        "stop": str(stop),
        "target": str(target),
        "horizon": horizon,
        "spread_bps": str(metrics.spread_bps),
        "planned_net_loss_eur": str(risk),
        "conditional_target_net_eur": str(reward),
        "fee_bps": str(FEE),
        "slippage_bps": str(SLIP + sell.depth_impact_bps),
    }


async def capture(market, plan: dict, prior: list[dict], *, detail_limit: int = 2) -> dict:
    started = utc_now()
    reference = cutoff(started)
    if not timestamp(plan["start"]) <= started < timestamp(plan["shadow_end"]):
        raise ValueError("outside_registered_capture_window")
    pairs = {pair.symbol: pair for pair in await market.client.get_pairs()}
    recent = {}
    for row in prior[-288:]:
        for symbol in row["selected"]:
            recent[symbol] = {
                "bucket": int(timestamp(row["reference"]).timestamp()) // 300,
                "data_failed": symbol not in row["markets"],
            }
    ranked, counts = rank_markets(
        list(pairs.values()),
        await market.client.get_tickers(),
        excluded=set(PEERS),
        limit=20,
        recent=recent,
        cycle_bucket=int(reference.timestamp()) // 300,
    )
    # A deterministic revisit queue exposes more eligible liquid names with
    # a fixed request budget. Never use a missing summary to fill the budget.
    ranked.sort(key=lambda x: (recent.get(x.symbol, {}).get("bucket", -1), -x.score, x.symbol))
    selected = [r.symbol for r in ranked[: min(3, max(1, detail_limit))]]
    histories, markets, failures, liquidity = {}, {}, {}, {}
    prior_liquidity = prior[-1].get("macro", {}).get("benchmark_liquidity", {}) if prior else {}
    if prior and timestamp(prior[-1]["reference"]) != reference - STEP:
        prior_liquidity = {}
    for symbol in [*PEERS, *selected]:
        try:
            if symbol not in pairs:
                failures[symbol] = "PAIR_UNAVAILABLE"
                continue
            if symbol in PEERS:
                histories[symbol] = await market.completed_candles(pairs[symbol])
                book = await market.client.get_order_book(symbol, limit=50)
                errors, metrics = market.validate_order_book(book)
                if (
                    not errors
                    and reference <= book.timestamp <= utc_now()
                    and book.source.startswith("revolut-x")
                ):
                    bid = metrics.best_bid
                    near_bid = sum(
                        (x.price * x.quantity for x in book.bids if x.price >= bid * D(".9975")),
                        D(0),
                    )
                    previous = prior_liquidity.get(symbol)
                    liquidity[symbol] = {
                        "observed_at": book.timestamp.isoformat(),
                        "spread_bps": str(metrics.spread_bps),
                        "near_bid_eur": str(near_bid),
                        "deteriorating": bool(
                            metrics.spread_bps > D(previous["spread_bps"])
                            and near_bid < D(previous["near_bid_eur"])
                        )
                        if previous
                        else None,
                    }
            else:
                observed = await market.get_validated_market(pairs[symbol])
                histories[symbol] = observed.candles
                if observed.usable_for_entry:
                    markets[symbol] = observed
                else:
                    failures[symbol] = observed.rejected_reasons
        except MarketDataError as exc:
            failures[symbol] = type(exc).__name__
            if isinstance(exc, RateLimitDeferred):
                break
    # Watch up to two recently qualified symbols without acquiring more books.
    # Rotate by oldest receipt so an entry can be followed after leaving the detail shortlist.
    watch = {}
    last_receipt = {}
    for previous in prior[-48:]:
        seen = timestamp(previous["observed_at"])
        for symbol in previous.get("observed_symbols", []):
            last_receipt[symbol] = seen
        for symbol, row in previous["markets"].items():
            plans = [p for p in (row["entry"], row["range"]) if p]
            if plans:
                until = seen + max(p["horizon"] for p in plans) * STEP
                watch[symbol] = max(until, watch.get(symbol, until))
    due = [
        s
        for s, until in watch.items()
        if s in pairs and s not in histories and started <= until + STEP
    ]
    for symbol in sorted(due, key=lambda s: (last_receipt.get(s, started), s))[:2]:
        try:
            histories[symbol] = await market.completed_candles(pairs[symbol])
        except MarketDataError as exc:
            failures[symbol] = type(exc).__name__
            if isinstance(exc, RateLimitDeferred):
                break

    observed_at = utc_now()
    for symbol, bars in histories.items():
        histories[symbol] = [
            b for b in bars if b.timestamp + STEP <= reference and b.source.startswith("revolut-x")
        ]
    macro = benchmark_context(
        {s: b for s, b in histories.items() if s in (*PEERS, *selected)}, reference
    )
    macro["benchmark_liquidity"] = liquidity
    benchmark_features = {}
    for symbol in PEERS:
        bars = window(histories.get(symbol, []), symbol, reference, 240)
        if bars:
            benchmark_features[symbol] = enrich(calculate_features(bars), bars, reference)
    engine = SuccessorOpportunityEngine(fee_bps=FEE, slippage_bps=SLIP)
    candidates = {}
    for symbol, observed in markets.items():
        bars = window(histories[symbol], symbol, reference, 240)
        book = observed.order_book
        if (
            not bars
            or cutoff(observed_at) != reference
            or book.timestamp < reference
            or not book.source.startswith("revolut-x")
        ):
            failures[symbol] = "UNSYNCHRONIZED_MARKET"
            continue
        f = enrich(
            calculate_features(bars, observed.metrics.imbalance, observed.metrics.spread_bps),
            bars,
            reference,
        )
        f.metadata.update(
            best_bid=book.best_bid,
            best_ask=book.best_ask,
            liquidity_quote=observed.metrics.liquidity_quote,
        )
        signal = engine.evaluate(
            A3,
            f,
            observed.pair,
            book,
            *(benchmark_features.get(s) for s in PEERS),
            bars,
            quote_budget=BUDGET,
        )
        signal = apply(
            reviewed_signal(signal, f), completed_context(bars, histories, reference), reference
        )
        evidence = signal.evidence
        setup = evidence["entry_plan"]
        stop = D(setup["stop"])
        ask = observed.metrics.best_ask
        ctx = entry_context(symbol, histories, reference, ask * (1 + SLIP / 10000), stop, A3, macro)
        market_plan = None
        if evidence["entry_eligible"] and setup["targets"]:
            market_plan = _quote(observed, stop, D(setup["targets"][0]), 36, observed_at)
            if market_plan:
                ctx = entry_context(
                    symbol, histories, reference, D(market_plan["entry"]), stop, A3, macro
                )
        if ctx["structure"] == "RANGE_RECLAIM" and ctx["checks"]["macro"] and f.atr and f.atr > 0:
            resistance = max(b.high for b in bars[-14:-2])
            invalidation = min(bars[-1].low, min(b.low for b in bars[-14:-2])) - f.atr / 2
            range_plan = _quote(observed, invalidation, resistance, 12, observed_at)
        else:
            range_plan = None
        candidates[symbol] = {
            "macro": ctx["checks"]["macro"],
            "a3": ctx["checks"]["a3"],
            "entry": market_plan,
            "range": range_plan,
            "structure": ctx["structure"],
            "relative_return_60m": ctx["relative_return_60m"],
            "reasons": evidence["reasons"],
            "score": str(signal.score),
            "book": book_payload(book),
            "liquidity": {
                "spread_bps": str(observed.metrics.spread_bps),
                "quote_depth_eur": str(observed.metrics.liquidity_quote),
            },
        }
    return {
        "schema": VERSION,
        "registration_hash": digest(canonical(plan)),
        "reference": reference.isoformat(),
        "observed_at": observed_at.isoformat(),
        "observed_symbols": sorted(s for s, bars in histories.items() if bars),
        "discovery": counts,
        "selected": selected,
        "markets": candidates,
        "failures": failures,
        "macro": macro,
        "candles": {s: [asdict(b) for b in bars] for s, bars in histories.items()},
    }


def load_captures(root: Path, plan: dict, *, recent: int | None = None) -> list[dict]:
    rows = []
    if plan.get("schema") != VERSION or plan.get("recipe_sha256") != recipe_hash():
        raise ValueError("registered_recipe_mismatch")
    binding = digest(canonical(plan))
    paths = sorted((root / "captures").glob("*.json"), key=lambda p: int(p.stem))
    for path in paths if recent is None else paths[-recent:]:
        row = json.loads(path.read_bytes())
        reference, observed = map(timestamp, (row["reference"], row["observed_at"]))
        if (
            row["schema"] != VERSION
            or row["registration_hash"] != binding
            or reference != cutoff(reference)
            or reference > observed
            or not timestamp(plan["start"]) <= observed < timestamp(plan["shadow_end"])
            or path.stem != str(int(reference.timestamp()))
        ):
            raise ValueError("capture_identity_or_clock_mismatch")
        # The capture keeps the complete input windows and books for audit.
        # The report needs only the possible on-time tape and modeled plans.
        row["candles"] = {symbol: bars[-4:] for symbol, bars in row["candles"].items()}
        for market in row["markets"].values():
            market.pop("book", None)
        rows.append(row)
    return sorted(rows, key=lambda r: r["observed_at"])


def _variant(row: dict, name: str) -> dict | None:
    if name == "rejected_by_combined_probe":
        return row["entry"] if row["macro"] is False or row["a3"] is False else None
    if name == "range_reclaim":
        return row["range"]
    if name in {"shared_macro", "combined_continuation"} and row["macro"] is not True:
        return None
    if name in {"a3_confirmation", "combined_continuation"} and row["a3"] is not True:
        return None
    return row["entry"]


def report(plan: dict, rows: list[dict], now: datetime) -> dict:
    rows = sorted(
        (r for r in rows if timestamp(r["observed_at"]) <= now), key=lambda r: r["observed_at"]
    )
    # Use first received completed bar only. A delayed backfill is not a
    # prospective observation. Never let revised OHLC overwrite it.
    tape = defaultdict(dict)
    for r in rows:
        seen = timestamp(r["observed_at"])
        for symbol, raw in r["candles"].items():
            for item in raw:
                b = candle(item)
                if (
                    b.symbol == symbol
                    and b.source.startswith("revolut-x")
                    and b.timestamp + STEP <= seen <= b.timestamp + 4 * STEP
                    and b.timestamp + STEP <= timestamp(r["reference"])
                ):
                    tape[symbol].setdefault(b.timestamp, b)
    start, dev, held, end = [
        timestamp(plan[k]) for k in ("start", "development_end", "holdout_end", "shadow_end")
    ]
    periods = {"development": (start, dev), "holdout": (dev, held), "shadow": (held, end)}
    results = {}
    for period, (begin, finish) in periods.items():
        observations = [r for r in rows if begin <= timestamp(r["observed_at"]) < min(finish, now)]
        measurements = {}
        for name in VARIANTS:
            reserved_until = begin
            selected = []
            qualified = 0
            for r in observations:
                at = timestamp(r["observed_at"])
                choices = [(s, p) for s, row in r["markets"].items() if (p := _variant(row, name))]
                qualified += len(choices)
                if not choices or at < reserved_until:
                    continue
                symbol, setup = max(
                    choices,
                    key=lambda x: (
                        D(x[1]["conditional_target_net_eur"]) / D(x[1]["planned_net_loss_eur"]),
                        x[0],
                    ),
                )
                until = at + setup["horizon"] * STEP
                # Purge horizon overlaps at each split and exclude pending windows.
                if until > min(finish, now):
                    continue
                reserved_until = until + 6 * STEP
                selected.append((symbol, at, setup, r["macro"].get("regime", "UNKNOWN")))
            stresses = {}
            for bps in STRESS:
                sample = []
                by_regime = defaultdict(list)
                for symbol, at, setup, regime in selected:
                    inputs = {
                        k: D(setup[k])
                        for k in (
                            "entry",
                            "quantity",
                            "stop",
                            "target",
                            "spread_bps",
                            "fee_bps",
                            "slippage_bps",
                        )
                    }
                    start_bar = cutoff(at)
                    price_path = [
                        tape[symbol][stamp]
                        for i in range(setup["horizon"] + 1)
                        if (stamp := start_bar + i * STEP) in tape[symbol]
                    ]
                    outcome = replay(
                        price_path,
                        at,
                        **inputs,
                        horizon=setup["horizon"],
                        extra_bps=D(bps),
                    )
                    if outcome is not None:
                        sample.append((at, outcome))
                        by_regime[regime].append(outcome)
                equity = peak = D(7000)
                drawdown = D(0)
                for _, outcome in sample:
                    equity += outcome.net
                    peak = max(peak, equity)
                    drawdown = max(drawdown, peak - equity)
                stresses[str(bps)] = {
                    **estimate(sample),
                    "censored": len(selected) - len(sample),
                    "proxy_net_eur": str(equity - 7000),
                    "drawdown_eur": str(drawdown),
                    "fee_eur": str(sum(o.fees for _, o in sample)),
                    "turnover_eur": str(sum(o.turnover for _, o in sample)),
                    "profitable_resolved_proxies": sum(o.net > 0 for _, o in sample),
                    "losing_resolved_proxies": sum(o.net < 0 for _, o in sample),
                    "position_minutes": sum(o.minutes for _, o in sample),
                    "by_regime": {
                        regime: {
                            "observations": len(outcomes),
                            "net_eur": str(sum(o.net for o in outcomes)),
                        }
                        for regime, outcomes in by_regime.items()
                    },
                }
            measurements[name] = {
                "qualified": qualified,
                "selected": len(selected),
                "stress": stresses,
            }
        results[period] = measurements
    checks = {}
    for period in ("holdout", "shadow"):
        base = results[period]["incumbent_a3_setup"]["stress"]
        candidate = results[period]["combined_continuation"]["stress"]
        normal, adverse = candidate["0"], candidate["50"]
        checks[period] = {
            "period_finished": now >= periods[period][1],
            "minimum_observations_each": all(
                x["status"] != INSUFFICIENT for x in (base["0"], normal, adverse)
            ),
            "at_least_90_pct_path_coverage": all(
                x["observations"] > 0 and x["observations"] >= 9 * x["censored"]
                for x in (base["0"], normal, adverse)
            ),
            "positive_lower_confidence_bound": bool(
                normal.get("interval_95_day_bootstrap")
                and normal["interval_95_day_bootstrap"][0] > 0
            ),
            "positive_under_50bps_exit_stress": (adverse.get("net_expectancy_eur") or 0) > 0,
            "net_improves_on_incumbent": D(normal["proxy_net_eur"]) > D(base["0"]["proxy_net_eur"]),
            "drawdown_no_worse_than_incumbent": D(normal["drawdown_eur"])
            <= D(base["0"]["drawdown_eur"]),
        }
    # These proxy results alone cannot qualify for an operator transition.
    # This explicitly stays closed until a separate paired executable dataset exists.
    return {
        "schema": VERSION,
        "as_of": now.isoformat(),
        "registration_sha256": digest(canonical(plan)),
        "recipe_sha256": plan["recipe_sha256"],
        "capture_cycles": len(rows),
        "periods": results,
        "qualification": {
            "status": INSUFFICIENT,
            "automatic_activation": False,
            "proxy_review_checks": checks,
            "missing": ["PAIRED_EXECUTABLE_INCUMBENT_AND_CHALLENGER", "INDEPENDENT_RISK_REVIEW"],
        },
        "evidence_kind": "FORWARD_PUBLIC_CANDLE_PROXY",
        "authority": "RESEARCH_ONLY",
        "latest_macro": rows[-1]["macro"] if rows else None,
        "funnel": {
            "screened": sum(r["discovery"]["screened"] for r in rows),
            "selected": sum(len(r["selected"]) for r in rows),
            "validated": sum(len(r["markets"]) for r in rows),
            "failures": dict(Counter(s for r in rows for s in r["failures"])),
        },
    }
