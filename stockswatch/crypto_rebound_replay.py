"""Read-only shadow replay for earlier, confirmed crypto rebound candidates.

Never alters the StocksWatch SQLite ledger or calls Alpaca. Historical midpoint
bars are NOT executable quotes. Outputs hypotheses for review, not permission
to enable a new strategy in the broker adapter.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from . import alpaca_crypto as ac
from .crypto_data_quality import quarantine_untraded_spikes
from .crypto_rebound_watch import assess
from .crypto_recovery import benchmark_stabilized
from .crypto_strategy_replay import _fmt, _trade
from .storage import DB_PATH


def _hourly(conn, symbol):
    return [dict(x) for x in conn.execute(
        "SELECT ts,o,h,l,c,v FROM ac_bars WHERE symbol=? AND timeframe='1Hour' ORDER BY ts",
        (symbol,))]


def _btc_stable(btc, by_time, ts):
    end = by_time.get(ts)
    if end is None or end < 3:
        return False
    recent = btc[end - 3:end + 1]
    times = [datetime.fromisoformat(x["ts"]) for x in recent]
    if any(times[i] - times[i - 1] != timedelta(hours=1) for i in range(1, 4)):
        return False
    return benchmark_stabilized(recent, ts)


def replay(path=DB_PATH, *, fee=0.0015, slip=0.001, holdout_days=7):
    if not (0 <= fee <= 0.01 and 0 <= slip <= 0.01 and 1 <= holdout_days <= 30):
        raise ValueError("rebound_replay_parameters_invalid")
    db = Path(path)
    if not db.is_file():
        raise RuntimeError("rebound_replay_database_missing")
    # mode=ro is important: this never mutates stock or crypto financial state.
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        btc = _hourly(conn, "BTC/USD")
        btc_index = {b["ts"]: i for i, b in enumerate(btc)}
        trades = []
        counters = Counter()
        latest = []
        ready = 0
        for symbol in ac.EXECUTION_PAIRS:
            hourly = _hourly(conn, symbol)
            if len(hourly) < 222:
                counters["insufficient_hourly_history_symbols"] += 1
                continue
            ready += 1
            latest.append(hourly[-1]["ts"])
            blocked_until = -1
            for i in range(219, len(hourly) - 1):
                if i < blocked_until:
                    continue
                source = hourly[max(0, i - 259):i + 1]
                cleaned, quality = quarantine_untraded_spikes(source)
                if quality["reason"] != "OK":
                    counters["quality_block"] += 1
                    continue
                atr = ac._atr(cleaned)
                rsi = ac._rsi([b["c"] for b in cleaned])
                if atr is None or rsi is None:
                    counters["indicators_unavailable"] += 1
                    continue
                check = assess(cleaned, atr, rsi)
                if not check["passed"]:
                    counters["shadow_rule_not_met"] += 1
                    continue
                counters["rule_candidates"] += 1
                if symbol != "BTC/USD" and not _btc_stable(btc, btc_index, hourly[i]["ts"]):
                    counters["btc_stability_block"] += 1
                    continue
                candidate = {
                    "bar_at": hourly[i]["ts"], "price": hourly[i]["c"],
                    "stop": check["stop"], "target": check["target"],
                    "gates": {"entry_strategy": "shadow_rebound"},
                }
                trade, held = _trade(symbol, candidate, hourly[i+1:], fee=fee, slip=slip)
                if trade is None:
                    counters["no_contiguous_modeled_exit_or_invalid_entry"] += 1
                    continue
                # A profit at a quote-only midpoint is not supported by trade
                # evidence. Reject any trade traversing zero-volume candles.
                if any(float(b["v"]) <= 0 for b in hourly[i+1:i+1+held]):
                    counters["quote_only_modeled_fill_rejected"] += 1
                    continue
                trades.append(trade)
                blocked_until = i + 1 + held
                counters["modeled_trades"] += 1
        newest = max(latest, default=None)
        if newest is None:
            return {"state": "INSUFFICIENT_HISTORY", "ready_symbols": ready,
                    "approved_for_paper": False, "broker_orders_sent": 0}
        cutoff = (datetime.fromisoformat(newest) - timedelta(days=holdout_days)).isoformat()
        holdout = [t for t in trades if t["at"] >= cutoff]
        stats = _fmt(holdout)
        # Positive simulation is not enough for permission to execute: no
        # stored bid/ask/depth snapshots for matching historical fills.
        return {
            "state": "EXPLORATORY_MIDPOINT_REPLAY_COMPLETE",
            "research_only": True,
            "approved_for_paper": False,
            "requires_bid_ask_depth_replay": True,
            "broker_orders_sent": 0,
            "ready_symbols": ready,
            "total_symbols": len(ac.EXECUTION_PAIRS),
            "last_hour": newest,
            "exploratory_holdout_start": cutoff,
            "fees_per_side": fee, "slippage_per_side": slip,
            "model": "next-hour midpoint open; stop-first; 36h max; positive-volume-only",
            "rejections": dict(sorted(counters.items())),
            "all": _fmt(trades),
            "last_days": stats,
            "review_worthy": bool(stats["trades"] >= 8 and stats["symbols"] >= 3
                 and isinstance(stats["profit_factor"], float)
                 and stats["profit_factor"] >= 1.15
                 and stats["expectancy_r"] is not None and stats["expectancy_r"] > 0.05),
            "note": "Research only: further untouched out-of-sample and executable quote replay required. No trading enabled.",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--holdout-days", type=int, default=7)
    args = parser.parse_args()
    result = replay(args.db, holdout_days=args.holdout_days)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["state"] == "EXPLORATORY_MIDPOINT_REPLAY_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
