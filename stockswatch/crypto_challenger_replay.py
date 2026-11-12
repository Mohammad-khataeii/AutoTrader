"""Compare four long-only crypto setups on the same stored market observations."""
from __future__ import annotations

import argparse
import bisect
import json
from collections import Counter
from datetime import datetime, timedelta

from . import alpaca_crypto as ac
from .crypto_data_quality import quarantine_untraded_spikes
from .crypto_rebound_replay import _btc_stable, _hourly
from .crypto_strategy_replay import FEE_PER_SIDE, SLIPPAGE_PER_SIDE, _fmt, _trade
from .storage import DB_PATH, connect_readonly

HOUR = timedelta(hours=1)
STRATEGIES = ("breakout", "continuation", "recovery", "relative_strength")


def _relative_strength(symbol, hourly, btc_window, *, healthy, btc_stable):
    if symbol == "BTC/USD" or not healthy or not btc_stable or len(btc_window) != 25:
        return False
    window = hourly[-25:]
    if [b["ts"] for b in window] != [b["ts"] for b in btc_window]:
        return False
    if ac._stamp(window[-1]["ts"]) - ac._stamp(window[0]["ts"]) != 24 * HOUR:
        return False
    if any(b["v"] <= 0 for b in (window[0], window[-1], btc_window[0], btc_window[-1])):
        return False
    close = window[-1]["c"]
    return (close / window[0]["c"] - 1 >= 0.01
            and close / window[0]["c"] - btc_window[-1]["c"] / btc_window[0]["c"] >= 0.02
            and close > ac._ema([b["c"] for b in hourly], 20)
            and close > window[-2]["c"])


def _setups(symbol, hourly, daily, btc, btc_index):
    at = ac._stamp(hourly[-1]["ts"]) + HOUR
    signal = ac.evaluate_completed_bars(symbol, hourly, daily, at)
    gates = signal.get("gates", {})
    if "rsi_volatility_healthy" not in gates or hourly[-1]["v"] <= 0:
        return {}
    trending = all(gates[key] for key in (
        "hourly_uptrend", "daily_above_ema200", "rsi_volatility_healthy",
    ))
    ts = hourly[-1]["ts"]
    stable = _btc_stable(btc, btc_index, ts)
    index = btc_index.get(ts, -1)
    cleaned, _ = quarantine_untraded_spikes(hourly)
    rules = {
        "breakout": trending and gates["20_hour_breakout"],
        "continuation": trending and gates["continuation_candidate"],
        "recovery": gates["recovery_candidate"] and (symbol == "BTC/USD" or stable),
        "relative_strength": _relative_strength(
            symbol, cleaned, btc[max(0, index - 24):index + 1],
            healthy=gates["rsi_volatility_healthy"], btc_stable=stable,
        ),
    }
    atr = ac._atr(cleaned)
    price = cleaned[-1]["c"]
    setups = {}
    for strategy, passed in rules.items():
        if passed:
            stop_atr, target_atr = (1.25, 2) if strategy == "recovery" else (2.5, 4.5)
            setups[strategy] = {
                "bar_at": ts, "price": price, "stop": round(price - stop_atr * atr, 8),
                "target": round(price + target_atr * atr, 8),
                "gates": {"entry_strategy": strategy},
            }
    return setups


def replay(path=DB_PATH, *, holdout_days=7, fee=FEE_PER_SIDE, slip=SLIPPAGE_PER_SIDE):
    if not (1 <= holdout_days <= 30 and 0 <= fee <= 0.01 and 0 <= slip <= 0.01):
        raise ValueError("invalid challenger replay parameters")
    trades = {kind: [] for kind in STRATEGIES}
    setups_seen = Counter()
    rejections = {kind: Counter() for kind in STRATEGIES}
    ready = {}
    compared_hours = 0
    with connect_readonly(path) as db:
        btc = _hourly(db, "BTC/USD")
        btc_index = {bar["ts"]: i for i, bar in enumerate(btc)}
        for symbol in ac.EXECUTION_PAIRS:
            hourly = _hourly(db, symbol)
            daily = [dict(r) for r in db.execute(
                "SELECT ts,o,h,l,c,v FROM ac_bars WHERE symbol=? AND timeframe='1Day' ORDER BY ts",
                (symbol,),
            )]
            days = [bar["ts"] for bar in daily]
            blocked_until = dict.fromkeys(STRATEGIES, 0)
            for i in range(219, len(hourly) - 1):
                ts = hourly[i]["ts"]
                at = ac._stamp(ts) + HOUR
                n = bisect.bisect_left(days, ac._floor(at, "1Day").isoformat())
                if n < 220:
                    continue
                ready[symbol] = ts
                compared_hours += 1
                candidates = _setups(symbol, hourly[max(0, i - 259):i + 1],
                                     daily[max(0, n - 260):n], btc, btc_index)
                for strategy, signal in candidates.items():
                    setups_seen[strategy] += 1
                    if i < blocked_until[strategy]:
                        rejections[strategy]["position_already_open"] += 1
                        continue
                    future = hourly[i + 1:i + 37]
                    trade, held = _trade(symbol, signal, future, fee=fee, slip=slip)
                    if trade is None:
                        rejections[strategy]["unmodeled_entry_or_exit"] += 1
                    elif any(b["v"] <= 0 for b in future[:held]):
                        rejections[strategy]["quote_only_fill_path"] += 1
                    else:
                        trades[strategy].append(trade)
                        blocked_until[strategy] = i + held
    last = max(ready.values(), default=None)
    cutoff = (ac._stamp(last) - timedelta(days=holdout_days)).isoformat() if last else None
    result = {}
    for kind, observations in trades.items():
        ordered = sorted(observations, key=lambda t: (t["exit_bar_at"], t["symbol"]))
        result[kind] = {
            "setups": setups_seen[kind], "rejections": dict(rejections[kind]),
            "all": _fmt(ordered),
            "last_days": _fmt([t for t in ordered if cutoff and t["at"] >= cutoff]),
        }
    return {
        "state": "REPLAY_COMPLETE" if ready else "INSUFFICIENT_HISTORY",
        "research_only": True, "approved_for_paper": False, "broker_orders_sent": 0,
        "ready_symbols": len(ready), "total_symbols": len(ac.EXECUTION_PAIRS),
        "last_evaluated_by_symbol": ready, "compared_symbol_hours": compared_hours,
        "trailing_period_start": cutoff, "fees_per_side": fee, "slippage_per_side": slip,
        "model": "next-hour midpoint open, traded bars only, gap-aware stop first, 36-hour maximum",
        "portfolio_model": "independent positions per symbol and strategy; no historical quote, depth or capital proof",
        "strategies": result,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--holdout-days", type=int, default=7)
    args = parser.parse_args()
    result = replay(args.db, holdout_days=args.holdout_days)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["state"] == "REPLAY_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
