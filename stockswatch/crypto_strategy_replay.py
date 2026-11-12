"""Read-only, causally ordered historical replay for AlpacaCrypto entry paths.

Uses existing Alpaca IEX crypto midpoint candles from the StocksWatch SQLite
ledger. This is NOT proof of executable fills, and does not place orders.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import alpaca_crypto as ac
from .storage import DB_PATH, connect_readonly

FEE_PER_SIDE = 0.0015
SLIPPAGE_PER_SIDE = 0.001
MAX_HOLD_HOURS = 36
RISK_FRACTION = 0.0035


def _fmt(trades):
    outcomes = [float(x["r"]) for x in trades]
    wins = sum(x for x in outcomes if x > 0)
    losses = abs(sum(x for x in outcomes if x < 0))
    equity = peak = 1.0
    max_dd = 0.0
    for r in outcomes:
        equity *= max(0.01, 1 + RISK_FRACTION * r)
        peak = max(peak, equity)
        max_dd = max(max_dd, 1 - equity / peak)
    return {
        "trades": len(trades),
        "symbols": len({x["symbol"] for x in trades}),
        "win_rate": round(sum(x > 0 for x in outcomes) / len(outcomes), 4)
                    if outcomes else None,
        "profit_factor": round(wins / losses, 4) if losses else
                         (None if not wins else "no_loss_observed"),
        "expectancy_r": round(sum(outcomes) / len(outcomes), 4)
                        if outcomes else None,
        "sum_r": round(sum(outcomes), 4),
        "drawdown_proxy_pct": round(max_dd * 100, 4),
    }


def _trade(symbol, signal, future, *, fee=FEE_PER_SIDE, slip=SLIPPAGE_PER_SIDE):
    if not future:
        return None, 0
    signal_bar = datetime.fromisoformat(signal["bar_at"])
    first = future[0]
    first_time = datetime.fromisoformat(first["ts"])
    if first_time - signal_bar != timedelta(hours=1):
        return None, 0
    entry = float(first["o"]) * (1 + slip)
    stop = float(signal["stop"])
    target = float(signal["target"])
    if not (stop > 0 and target > entry > stop and
            abs(entry / float(signal["price"]) - 1) <= 0.02):
        return None, 0
    risk = entry - stop
    for j, bar in enumerate(future[:MAX_HOLD_HOURS]):
        at = datetime.fromisoformat(bar["ts"])
        if at - first_time != timedelta(hours=j):
            return None, 0  # Missing data: refuse invented exit.
        low, high = float(bar["l"]), float(bar["h"])
        if low <= stop:
            exit_raw, reason = min(stop, float(bar["o"])), "stop_first"
        elif high >= target:
            exit_raw, reason = target, "target"
        elif j == MAX_HOLD_HOURS - 1:
            exit_raw, reason = float(bar["c"]), "time"
        else:
            continue
        exit_price = exit_raw * (1 - slip)
        net = exit_price * (1 - fee) - entry * (1 + fee)
        return {
            "symbol": symbol, "at": signal["bar_at"],
            "entry_strategy": signal["gates"]["entry_strategy"],
            "r": net / risk, "exit": reason, "exit_bar_at": bar["ts"],
        }, j + 1
    return None, 0


def replay(path=DB_PATH, *, fee=FEE_PER_SIDE, slip=SLIPPAGE_PER_SIDE,
           max_symbols=33, out_of_sample_days=7):
    db_path = Path(path)
    if not db_path.is_file():
        raise RuntimeError("crypto_replay_database_missing")
    if not (0 <= fee <= 0.01 and 0 <= slip <= 0.01):
        raise ValueError("crypto_replay_costs_invalid")
    with connect_readonly(db_path) as conn:
        outcome = {"baseline": [], "candidate": []}
        covered = 0
        latest_by_symbol = {}
        for symbol in ac.EXECUTION_PAIRS[:max_symbols]:
            hour = [dict(x) for x in conn.execute(
                "SELECT ts,o,h,l,c,v FROM ac_bars "
                "WHERE symbol=? AND timeframe='1Hour' ORDER BY ts",
                (symbol,))]
            day = [dict(x) for x in conn.execute(
                "SELECT ts,o,h,l,c,v FROM ac_bars "
                "WHERE symbol=? AND timeframe='1Day' ORDER BY ts",
                (symbol,))]
            if len(hour) < 230 or len(day) < 220:
                continue
            covered += 1
            latest_by_symbol[symbol] = hour[-1]["ts"]
            daily_keys = [x["ts"] for x in day]
            blocked_to = {"baseline": 0, "candidate": 0}
            # 260 is the live model's actual lookback; only prior bars
            # (plus the NEXT bar for entry) can be seen at any evaluation.
            for i in range(219, len(hour) - 1):
                at = datetime.fromisoformat(hour[i]["ts"]) + timedelta(hours=1)
                day_end = ac._floor(at, "1Day").isoformat()
                nd = bisect.bisect_left(daily_keys, day_end)
                if nd < 220:
                    continue
                h_slice = hour[max(0, i-259):i+1]
                d_slice = day[max(0, nd-260):nd]
                observation = ac.evaluate_completed_bars(
                    symbol, h_slice, d_slice, at, allow_continuation=True)
                if observation["action"] != "BUY":
                    continue
                kind = observation["gates"]["entry_strategy"]
                for strategy in ("baseline", "candidate"):
                    if kind == "continuation" and strategy == "baseline":
                        continue
                    if i < blocked_to[strategy]:
                        continue
                    trade, held = _trade(symbol, observation, hour[i+1:],fee=fee,slip=slip)
                    if trade is None or any(bar["v"] <= 0 for bar in hour[i+1:i+1+held]):
                        continue
                    outcome[strategy].append(trade)
                    blocked_to[strategy] = i + 1 + held
        all_latest = max(latest_by_symbol.values(), default=None)
        if not all_latest:
            return {"state": "INSUFFICIENT_HISTORY", "ready_symbols": 0,
                    "total_symbols": len(ac.EXECUTION_PAIRS), "approved": False}
        cutoff = (datetime.fromisoformat(all_latest)
                  - timedelta(days=out_of_sample_days)).isoformat()
        result = {
            "state": "REPLAY_COMPLETE",
            "ready_symbols": covered,
            "total_symbols": len(ac.EXECUTION_PAIRS),
            "last_hour": all_latest,
            "holdout_start": cutoff,
            "fees_per_side": fee,
            "slippage_per_side": slip,
            "fills": "modeled_next_hour_open; gap_aware_stop_first; traded_bars_only; 36h_max",
            "broker_orders_sent": 0,
            "baseline": {},
            "candidate": {},
        }
        for strategy, trades in outcome.items():
            result[strategy] = {
                "all": _fmt(trades),
                "holdout": _fmt([x for x in trades if x["at"] >= cutoff]),
                "holdout_continuations": _fmt([x for x in trades
                    if x["at"] >= cutoff and x["entry_strategy"] == "continuation"]),
            }
        candidate = result["candidate"]["holdout"]
        baseline = result["baseline"]["holdout"]
        # Fail closed: no live strategy activation on sparse or losing replay.
        pf = candidate["profit_factor"]
        result["approved"] = bool(
            covered >= 5 and candidate["trades"] >= 8
            and candidate["symbols"] >= 3
            and isinstance(pf, float) and pf >= 1.10
            and candidate["expectancy_r"] is not None
            and candidate["expectancy_r"] > 0.05
            and candidate["drawdown_proxy_pct"] <= 5.0
            and candidate["sum_r"] > baseline["sum_r"]
        )
        result["approval_note"] = (
            "Eligible for conditional paper activation only; modeled history cannot guarantee profit"
            if result["approved"] else
            "Candidate stays disabled; insufficient or unconvincing out-of-sample performance"
        )
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = replay(args.db)
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0 if result["state"] == "REPLAY_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
