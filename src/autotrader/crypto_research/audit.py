"""Read and analyze the original primary-paper forensic export."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from statistics import mean

from autotrader.domain import Candle

from .context import PEERS, STEP, benchmark_context, cutoff, entry_context
from .replay import INSUFFICIENT, POLICIES, block_interval, estimate, replay

ACCOUNT = "PERSONAL_PLAN_PAPER_7000"
HISTORICAL_SPLIT = datetime(2026, 11, 2, tzinfo=UTC)
FILTERS = ("baseline", "shared_macro", "early_recovery", "a3_confirmation", "cluster", "combined")


def timestamp(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("timestamp_requires_offset")
    return stamp.astimezone(UTC)


def candle(row: dict) -> Candle:
    return Candle(
        row["symbol"],
        timestamp(row["timestamp"]),
        *(D(str(row[k])) for k in ("open", "high", "low", "close", "volume")),
        row["timeframe"],
        row["source"],
    )


def read_audit(path: Path) -> tuple[dict, dict]:
    rows = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line, parse_float=D)
            rows[item["section"]].append(item.get("data", item))
    if len(rows["meta"]) != 1 or len(rows["counts"]) != 1:
        raise ValueError("expected_one_header_and_footer")
    meta, counts = rows.pop("meta")[0], rows.pop("counts")[0]
    if (
        meta["account"] != ACCOUNT
        or meta["read_only"] is not True
        or meta["source"] != "read_only_postgres_snapshot"
    ):
        raise ValueError("unexpected_audit_scope")
    actual = {name: len(items) for name, items in rows.items()}
    if actual != counts["rows"]:
        raise ValueError("archive_counts_mismatch")
    for section, key in {
        "positions": "position_id",
        "orders": "order_id",
        "fills": "fill_id",
        "exit_plans": "exit_plan_id",
        "exit_intents": "exit_intent_id",
        "exit_targets": "target_id",
        "financial_journal": "ledger_event_id",
        "trading_decisions": "decision_id",
        "strategy_signals": "signal_id",
    }.items():
        if len({r[key] for r in rows[section]}) != len(rows[section]):
            raise ValueError("duplicate_audit_id:" + section)
    if any(r["account_id"] != ACCOUNT for s in ("positions", "equity_snapshots") for r in rows[s]):
        raise ValueError("unexpected_account_record")
    with path.open("rb") as stream:
        sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    return dict(rows), {"sha256": sha256, "captured_at": meta["captured_at_utc"], **counts}


def _spread(book: dict) -> D:
    bid, ask = (D(book[k][0][0]) for k in ("bids", "asks"))
    return (ask - bid) * 20000 / (ask + bid)


def _sum(rows: list[dict], key: str) -> D:
    return sum((D(str(r[key])) for r in rows), D(0))


def trade_evidence(rows: dict) -> tuple[list[dict], dict]:
    histories = defaultdict(list)
    for raw in rows["market_candles"]:
        bar = candle(raw)
        histories[bar.symbol].append(bar)
    for bars in histories.values():
        bars.sort(key=lambda b: b.timestamp)
    orders = {o["order_id"]: o for o in rows["orders"]}
    plans = {p["position_id"]: p for p in rows["exit_plans"]}
    trades = []
    for p in sorted(rows["positions"], key=lambda p: p["opened_at"]):
        pid, symbol = p["position_id"], p["symbol"]
        fills = [f for f in rows["fills"] if f["position_id"] == pid]
        buys = [f for f in fills if f["side"] == "BUY"]
        sells = [f for f in fills if f["side"] == "SELL"]
        if len({f["order_id"] for f in buys}) != 1 or not sells or p["state"] != "CLOSED":
            raise ValueError("unsupported_trade_fill_lineage")
        buy = orders[buys[0]["order_id"]]
        sell = orders[sells[-1]["order_id"]]
        journal = [j for j in rows["financial_journal"] if j["position_id"] == pid]
        pnl = D(str(p["realized_pnl"]))
        if (
            any(orders[f["order_id"]]["position_id"] != pid or f["symbol"] != symbol for f in fills)
            or abs(_sum(journal, "realized_pnl_delta") - pnl) > D(".000001")
            or abs(_sum(journal, "cash_delta") - pnl) > D(".000001")
            or _sum(buys, "quantity") != _sum(sells, "quantity")
        ):
            raise ValueError("trade_reconciliation_failed:" + pid)
        order_created, opened, closed = map(
            timestamp, (buy["created_at"], p["opened_at"], p["closed_at"])
        )
        payload, exit_payload = (json.loads(o["execution_json"]) for o in (buy, sell))
        evidence = payload["strategy_evidence"]
        signal_complete = timestamp(evidence["as_of"]) + STEP
        strategy = plans[pid]["strategy_id"]
        book, exit_book = payload["book"], exit_payload["book"]
        # The position event precedes the order row's database timestamp.
        # Use the earlier execution event as the upper bound for entry features.
        submitted = min(order_created, opened)
        if not signal_complete <= submitted <= opened <= closed:
            raise ValueError("invalid_trade_time_lineage")
        entry, stop, target = (
            D(str(p[k])) for k in ("average_entry_price", "initial_stop", "target_1")
        )
        metrics = (evidence.get("economics") or {}).get("measurements", {})
        regime = evidence.get("raoe_regime") or evidence.get("regime_assessment") or {}
        recorded = regime.get("timeframes", {})
        original_trends = tuple(recorded.get(k, {}).get("trend", "UNKNOWN") for k in ("15", "60"))
        context = entry_context(
            symbol,
            histories,
            signal_complete,
            entry,
            stop,
            strategy,
            recorded_trends=original_trends,
        )
        dispatch = benchmark_context(histories, submitted)
        intent = next(i for i in rows["exit_intents"] if i["position_id"] == pid)
        observed_bid = D(exit_book["bids"][0][0])
        sell_qty = _sum(sells, "quantity")
        exit_price = sum(D(str(f["price"])) * D(str(f["quantity"])) for f in sells) / sell_qty
        plan_loss = metrics.get("expected_net_stop_loss_eur")
        horizon = payload.get("holding_seconds") or json.loads(plans[pid]["settings_json"]).get(
            "holding_seconds"
        )
        path_start = cutoff(opened) + STEP if cutoff(opened) < opened else opened
        path = [
            b
            for b in histories[symbol]
            if path_start <= b.timestamp and b.timestamp + STEP <= closed
        ]
        path_complete = bool(
            path
            and [b.timestamp for b in path]
            == [path_start + i * STEP for i in range(int((cutoff(closed) - path_start) / STEP))]
        )
        trades.append(
            {
                "position_id": pid,
                "symbol": symbol,
                "strategy": strategy,
                "profile": evidence.get("execution_profile"),
                "strategy_version": evidence.get("strategy_version"),
                "release": evidence.get("backend_release"),
                "manifest": evidence.get("paper_manifest"),
                "admission_version": (evidence.get("primary_admission") or {}).get("version"),
                "recorded_admission_peer_trends": {
                    s: v.get("trend")
                    for s, v in (evidence.get("primary_admission") or {})
                    .get("inputs", {})
                    .get("peers", {})
                    .items()
                },
                "recorded_stop_atr": (evidence.get("quality_policy") or {}).get(
                    "stop_distance_atr"
                ),
                "original_regime": regime.get("benchmark"),
                "original_timeframes": regime.get("timeframes"),
                "entry_conditions": evidence.get("conditions"),
                "recorded_admission_gates": (evidence.get("primary_admission") or {}).get("gates"),
                "recorded_quality_gates": (evidence.get("quality_policy") or {}).get("gates"),
                "signal_complete": signal_complete,
                "submitted": submitted,
                "order_created": order_created,
                "entry_book_at": timestamp(book["timestamp"]),
                "exit_book_at": timestamp(exit_book["timestamp"]),
                "opened": opened,
                "closed": closed,
                "pnl": pnl,
                "fees": _sum(fills, "fee"),
                "entry": entry,
                "stop": stop,
                "target": target,
                "exit_price": exit_price,
                "exit_bid": observed_bid,
                "qty": sell_qty,
                "fee_bps": D(payload["fee_bps"]),
                "slippage_bps": D(payload["slippage_bps"]),
                "spread_bps": _spread(book),
                "exit_spread_bps": _spread(exit_book),
                "entry_ask": D(book["asks"][0][0]),
                "stop_gap_eur": (D(str(p["protective_stop"])) - observed_bid) * sell_qty
                if intent["reason"] == "STOP"
                else None,
                "exit_impact_and_slippage_eur": (observed_bid - exit_price) * sell_qty,
                "exit_depth_impact_bps": (exit_payload.get("execution_quality") or {}).get(
                    "depth_impact_bps"
                ),
                "planned_loss_eur": D(plan_loss) if plan_loss is not None else None,
                "locked_planned_loss_eur": (payload.get("dispatch_buy_admission") or {}).get(
                    "planned_loss_eur"
                ),
                "horizon": horizon // 300 if horizon else None,
                "exit_reason": intent["reason"],
                "intent_to_fill_seconds": (
                    timestamp(sells[-1]["created_at"]) - timestamp(intent["created_at"])
                ).total_seconds(),
                "path_bars": len(path),
                "path_contiguous": path_complete,
                "mfe_completed_ohlc": max(b.high / entry - 1 for b in path)
                if path_complete
                else None,
                "mae_completed_ohlc": min(b.low / entry - 1 for b in path)
                if path_complete
                else None,
                "context": context,
                "dispatch_macro": dispatch,
            }
        )
    return trades, histories


def _filter(name: str, trade: dict, prior: list[dict]) -> bool | None:
    checks = trade["context"]["checks"]
    if name == "baseline":
        return True
    if name == "cluster":
        # Existing €2,100 cap can hold three €700 trades. Test one fresh crypto
        # thesis per 30 minutes and a 30-minute pause following a realized loss.
        at = trade["submitted"]
        return not any(
            t["opened"] <= at < t["opened"] + timedelta(minutes=30)
            or t["closed"] <= at < t["closed"] + timedelta(minutes=30)
            and t["pnl"] < 0
            for t in prior
        )
    if name == "shared_macro":
        dispatch = trade["dispatch_macro"]
        if dispatch["status"] != "READY" or checks["macro"] is None:
            return None
        return checks["macro"] and dispatch["regime"] not in {"CORRELATED_SELLOFF", "JOINT_DECLINE"}
    if name == "early_recovery":
        return checks["recovery"] if trade["strategy"] == "RAOE_EARLY_RECOVERY" else True
    if name == "a3_confirmation":
        return checks["a3"] if trade["strategy"].startswith("A3") else True
    components = [_filter(n, trade, prior) for n in FILTERS[1:-1]]
    return False if False in components else None if None in components else True


def _summary(kept: list[dict], blocked: list[dict], unknown: list[dict]) -> dict:
    days = defaultdict(list)
    for t in kept:
        days[t["opened"].date()].append(float(t["pnl"]))
    balance = peak = D(7000)
    drawdown = D(0)
    for t in sorted(kept, key=lambda t: t["closed"]):
        balance += t["pnl"]
        peak = max(balance, peak)
        drawdown = max(drawdown, peak - balance)
    active_seconds = 0.0
    active_until = None
    for trade in sorted(kept, key=lambda t: t["opened"]):
        begin = max(trade["opened"], active_until) if active_until else trade["opened"]
        if trade["closed"] > begin:
            active_seconds += (trade["closed"] - begin).total_seconds()
            active_until = trade["closed"]
    return {
        "time_with_exposure_minutes": active_seconds / 60,
        "trades": len(kept),
        "blocked": len(blocked),
        "unknown": len(unknown),
        "net_eur": _sum(kept, "pnl"),
        "mean_net_eur": mean(t["pnl"] for t in kept) if kept else None,
        "descriptive_day_bootstrap_95": block_interval(days),
        "observed_losses_avoided": sum(t["pnl"] < 0 for t in blocked),
        "observed_winners_missed": sum(t["pnl"] > 0 for t in blocked),
        "fees_eur": _sum(kept, "fees"),
        "turnover_eur": sum(t["qty"] * (t["entry"] + t["exit_price"]) for t in kept),
        "position_minutes": sum((t["closed"] - t["opened"]).total_seconds() / 60 for t in kept),
        "capital_minutes_eur": sum(
            t["entry"] * t["qty"] * D(str((t["closed"] - t["opened"]).total_seconds() / 60))
            for t in kept
        ),
        "closed_trade_drawdown_eur": drawdown,
        "trade_regimes": dict(Counter(t["context"]["macro"]["regime"] for t in kept)),
    }


def compare(trades: list[dict], histories: dict) -> dict:
    result = {}
    for name in FILTERS:
        buckets = {"development": [[], [], []], "later_already_inspected": [[], [], []]}
        kept = []
        for trade in trades:
            period = (
                "development" if trade["opened"] < HISTORICAL_SPLIT else "later_already_inspected"
            )
            allowed = _filter(name, trade, kept)
            buckets[period][0 if allowed is True else 1 if allowed is False else 2].append(trade)
            if allowed:
                kept.append(trade)
        result[name] = {k: _summary(*groups) for k, groups in buckets.items()}
    proxies = {}
    peer_histories = {s: histories[s] for s in PEERS}
    endpoints = {b.timestamp + STEP for s in PEERS for b in histories[s]}
    adverse = frozenset(
        at
        for at in endpoints
        if benchmark_context(peer_histories, at)["regime"] == "CORRELATED_SELLOFF"
    )
    variants = (*POLICIES, "structural", "delayed_confirmation")
    for policy in variants:
        proxies[policy] = {}
        for stress in (0, 20, 50):
            samples = []
            no_entry = 0
            for t in trades:
                if not t["horizon"]:
                    continue
                bars = histories[t["symbol"]]
                entry, quantity, stop, at = t["entry"], t["qty"], t["stop"], t["opened"]
                if policy == "structural":
                    floor = t["context"]["structure_floor"]
                    if not floor or not 0 < D(floor) < entry:
                        continue
                    stop = D(floor)
                    fee = t["fee_bps"] / 10000
                    exit_factor = (1 - (t["slippage_bps"] + D(20)) / 10000) * (1 - fee)
                    original_risk = quantity * (entry * (1 + fee) - t["stop"] * exit_factor)
                    quantity = min(
                        quantity,
                        min(D(35), original_risk) / (entry * (1 + fee) - stop * exit_factor),
                    )
                if policy == "delayed_confirmation":
                    # Observe one additional completed bar; enter only on a
                    # higher close. The next open is a price proxy without depth.
                    confirm_at = cutoff(t["submitted"])
                    bar = next((b for b in bars if b.timestamp == confirm_at), None)
                    following = next((b for b in bars if b.timestamp == confirm_at + STEP), None)
                    if bar is None or following is None:
                        continue
                    if bar.close <= bar.open or bar.low <= stop:
                        no_entry += 1
                        continue
                    at = following.timestamp
                    entry = following.open * (
                        1 + (t["spread_bps"] / 2 + t["slippage_bps"] + D(stress)) / 10000
                    )
                    if not stop < entry < t["target"]:
                        no_entry += 1
                        continue
                    quantity = min(quantity, quantity * t["entry"] / entry)
                outcome = replay(
                    bars,
                    at,
                    entry=entry,
                    quantity=quantity,
                    stop=stop,
                    target=t["target"],
                    horizon=t["horizon"],
                    spread_bps=t["spread_bps"],
                    fee_bps=t["fee_bps"],
                    slippage_bps=t["slippage_bps"],
                    policy=policy if policy in POLICIES else "bracket",
                    extra_bps=D(stress),
                    adverse_cutoffs=adverse,
                    invalidation=D(t["context"]["retest_level"])
                    if t["context"]["retest_level"]
                    else None,
                )
                if outcome is not None:
                    samples.append((t["opened"], outcome))
            proxies[policy][stress] = {
                "proxy_eur": sum(x.net for _, x in samples),
                "no_entry": no_entry,
                "censored": len(trades) - len(samples) - no_entry,
                **estimate(samples),
            }
    return {
        "historical_filter_only": result,
        "exit_ohlc_proxy": proxies,
        "expanded_discovery": INSUFFICIENT,
        "holdout": INSUFFICIENT,
    }


def analyze(path: Path) -> dict:
    rows, info = read_audit(path)
    trades, histories = trade_evidence(rows)
    scan = json.loads(
        next(r for r in rows["system_state"] if r["key"] == "paper_scan")["payload_json"]
    )
    decisions = rows["trading_decisions"]
    signals = {r["signal_id"] for r in rows["strategy_signals"]}
    linked = sum(
        bool(signals.intersection(json.loads(r["payload_json"]).get("signal_ids", [])))
        for r in decisions
    )
    return {
        "archive": info,
        "trades": trades,
        "comparison": compare(trades, histories),
        "strategy": {
            s: _summary([t for t in trades if t["strategy"] == s], [], [])
            for s in sorted({t["strategy"] for t in trades})
        },
        "net_eur": _sum(trades, "pnl"),
        "fees_eur": _sum(trades, "fees"),
        "latest_equity": max(rows["equity_snapshots"], key=lambda r: r["timestamp"])["equity"],
        "funnel": {
            "actions": dict(Counter(d["action"] for d in decisions)),
            "decision_to_signal_matches": linked,
            "decision_range": [
                min(d["created_at"] for d in decisions),
                max(d["created_at"] for d in decisions),
            ],
            "market_count": len({d["symbol"] for d in decisions}),
            "rejections": dict(
                Counter(
                    k for d in decisions for k in (d["rejected_reason"] or "").split(",") if k
                ).most_common(12)
            ),
            "last_scan_markets": scan["markets"],
            "missed_executable_opportunities": None,
        },
    }
