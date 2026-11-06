"""Chronological price-proxy comparisons. No broker client or execution authority."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, pstdev

from .universe import BENCHMARKS

MODES = (
    "long_only",
    "short_only",
    "combined",
    "intraday_momentum",
    "short_patient_cover",
    "short_reversal_exit",
)


def metrics(trades):
    if not trades:
        return {"trades": 0, "status": "INSUFFICIENT_DATA"}
    returns = [x["net"] for x in trades]
    equity = peak = 1.0
    drawdown = 0.0
    for net in returns:
        equity *= max(0, 1 + net)
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
    wins = [v for v in returns if v > 0]
    losses = [v for v in returns if v < 0]
    return {
        "trades": len(returns),
        "status": "PRICE_PROXY",
        "return": equity - 1,
        "max_drawdown": drawdown,
        "mean_net": mean(returns),
        "trade_volatility": pstdev(returns),
        "tail_05": sorted(returns)[int(0.05 * (len(returns) - 1))],
        "win_fraction": len(wins) / len(returns),
        "profit_factor": sum(wins) / -sum(losses) if losses else None,
        "round_trip_turnover": 2 * len(returns),
        "exposure_minutes": sum(t["minutes"] for t in trades),
        "net_per_exposure_hour": sum(returns) * 60 / sum(t["minutes"] for t in trades),
        "by_regime": {
            regime: mean(t["net"] for t in trades if t["regime"] == regime)
            for regime in sorted({t["regime"] for t in trades})
        },
        "overnight_gap_squeeze_worst": min(t["squeeze"] for t in trades),
    }


def replay(series):
    """Prefix-calibrated 5-session development, then disjoint 2-session evaluation blocks."""
    days = sorted({day for _, day in series})
    windows = []
    for idx in range(5, len(days), 2):
        training = set(days[idx - 5 : idx])
        holdout = set(days[idx : idx + 2])
        moves = []
        for (s, day), bars in series.items():
            if day in training and s not in BENCHMARKS:
                for i in range(5, len(bars), 10):
                    if bars[i][0] - bars[i - 5][0] == timedelta(minutes=5):
                        moves.append(abs(bars[i][3] / bars[i - 5][3] - 1))
        if not moves:
            continue
        threshold = max(0.0015, sorted(moves)[int(0.65 * (len(moves) - 1))])
        results = {}
        for variant in MODES:
            selected = []
            missed = 0
            for day in sorted(holdout):
                benchmark = {
                    s: {r[0]: i for i, r in enumerate(series.get((s, day), []))} for s in BENCHMARKS
                }
                candidates = []
                for (symbol, d), bars in series.items():
                    if d != day or symbol in BENCHMARKS:
                        continue
                    for i in range(5, len(bars) - 2, 10):
                        stamp = bars[i][0]
                        if stamp - bars[i - 5][0] != timedelta(minutes=5) or bars[i + 1][
                            0
                        ] - stamp != timedelta(minutes=1):
                            continue
                        momentum = bars[i][3] / bars[i - 5][3] - 1
                        peer = []
                        for s, index in benchmark.items():
                            p = index.get(stamp)
                            peer_bars = series.get((s, day), [])
                            if (
                                p is not None
                                and p >= 5
                                and stamp - peer_bars[p - 5][0] == timedelta(minutes=5)
                            ):
                                peer.append(peer_bars[p][3] / peer_bars[p - 5][3] - 1)
                        if len(peer) != 2 or abs(momentum) < threshold:
                            continue
                        context = mean(peer)
                        side = 1 if momentum > 0 else -1
                        if variant in {"long_only", "intraday_momentum"} and side < 0:
                            continue
                        if variant.startswith("short") and side > 0:
                            continue
                        if (
                            variant != "intraday_momentum"
                            and (momentum - context) * side < threshold / 2
                        ):
                            continue
                        if side < 0 and (
                            context > 0.001 or bars[i][3] >= min(x[3] for x in bars[i - 5 : i])
                        ):
                            continue
                        hold = 40 if variant == "short_patient_cover" else 20
                        end = i + 1 + hold
                        if end >= len(bars) or bars[end][0] - stamp != timedelta(minutes=hold + 1):
                            continue
                        entry = bars[i + 1][1]
                        exit_at = end
                        if variant == "short_reversal_exit":
                            for j in range(i + 2, end):
                                if bars[j][3] > entry * 1.008:
                                    exit_at = j + 1
                                    break
                        gross = (bars[exit_at][1] / entry - 1) * side
                        # One risk slot, take the highest absolute impulse available at that event time.
                        candidates.append(
                            (
                                stamp,
                                abs(momentum),
                                symbol,
                                {
                                    "net": gross - 0.003 - (0.001 if side < 0 else 0),
                                    "stress": gross - 0.007 - (0.005 if side < 0 else 0),
                                    "squeeze": gross - (0.10 if side < 0 else 0.04),
                                    "minutes": exit_at - i - 1,
                                    "regime": "DOWN" if context < 0 else "UP_OR_FLAT",
                                    "direction": "LONG" if side > 0 else "SHORT",
                                },
                            )
                        )
                available = None
                for stamp, _, _, trade in sorted(candidates, key=lambda x: (x[0], -x[1], x[2])):
                    if available and stamp <= available:
                        missed += trade["net"] > 0
                        continue
                    selected.append(trade)
                    available = stamp + timedelta(minutes=trade["minutes"] + 1)
            results[variant] = {
                **metrics(selected),
                "stressed": metrics([{**r, "net": r["stress"]} for r in selected]),
                "positive_overlapping_price_proxies": missed,
                "long_count": sum(r["direction"] == "LONG" for r in selected),
            }
        windows.append(
            {
                "development": sorted(training),
                "test": sorted(holdout),
                "entry_threshold": threshold,
                "variants": results,
            }
        )
    return {
        "status": "CANDLE_PROXY" if windows else "INSUFFICIENT_DATA",
        "windows": windows,
        "current_eod_reference": "Use existing StocksWatch ensemble historical report for the independent EOD baseline",
        "limitations": [
            "Current-universe survivorship bias",
            "No historical ETB or order books",
            "Next-open price proxy, spread/slippage/borrow scenarios only",
            "Adverse squeeze/overnight haircut is a scenario, not an observed gap",
        ],
    }


def run(db, feed):
    series = defaultdict(list)
    with sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True) as c:
        for symbol, day, stamp, o, h, l, close in c.execute(
            """SELECT symbol,trade_date,at,o,h,l,c
            FROM sw_historical_bars WHERE timeframe='1Min' AND phase='CORE' AND adjustment='raw'
            AND feed=? ORDER BY symbol,trade_date,at""",
            (feed,),
        ):
            nums = tuple(map(float, (o, h, l, close)))
            if all(v > 0 and math.isfinite(v) for v in nums):
                series[(symbol, day)].append(
                    (datetime.fromisoformat(stamp), nums[0], nums[2], nums[3])
                )
        has_eod = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_runs'"
        ).fetchone()
        eod = (
            c.execute(
                "SELECT report_json FROM research_runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if has_eod
            else None
        )
    result = replay(series)
    if eod:
        result["current_eod_reference"] = json.loads(eod[0]).get("by_strategy", {}).get("ensemble")
    return {"feed": feed, **result}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", required=True, type=Path)
    p.add_argument("--feed", choices=("iex", "sip"), default="sip")
    args = p.parse_args()
    print(json.dumps(run(args.db, args.feed), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
