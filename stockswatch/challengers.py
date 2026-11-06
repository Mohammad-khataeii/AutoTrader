"""Offline portfolio replay on timestamp-aligned, real-provider historical bars.

None of the policies in this module is imported by the paper executor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from math import sqrt
from pathlib import Path

from .market import validate_bars
from .sessions import calendar
from .signals import avg, evaluate, features, returns, sigma

POLICY = "stockswatch-historical-challengers-v2-opening-proxy"
HOLDOUT_START = "2025-11-06"
UNIVERSE = {
    "AAPL": "Technology",
    "MSFT": "Technology",
    "JPM": "Financials",
    "V": "Financials",
    "XOM": "Energy",
    "CVX": "Energy",
    "PG": "Consumer Staples",
    "KO": "Consumer Staples",
    "CAT": "Industrials",
    "UBER": "Industrials",
}
MODES = (
    "baseline",
    "relative_strength",
    "pullback",
    "breakout",
    "mean_reversion",
    "sector_regime",
    "baseline_risk_exit",
    "challenger_ensemble",
)


def panel_at(data, i):
    spy, qqq = data["SPY"][: i + 1], data["QQQ"][: i + 1]
    risk_on = spy[-1]["c"] > avg([b["c"] for b in spy[-200:]])
    risk_on_broad = risk_on and qqq[-1]["c"] > avg([b["c"] for b in qqq[-200:]])
    benchmark_momentum = returns(spy, 63)
    result = {}
    peer_strength = defaultdict(list)
    peer_momentum = defaultdict(list)
    for symbol, sector in UNIVERSE.items():
        bars = data[symbol][: i + 1]
        f = features(bars, spy)
        o, h, low, close = (bars[-1][key] for key in ("o", "h", "l", "c"))
        prior = bars[-2]
        atr = avg(
            [
                max(b["h"] - b["l"], abs(b["h"] - p["c"]), abs(b["l"] - p["c"]))
                for p, b in zip(bars[-15:-1], bars[-14:])
            ]
        )
        strength = avg([bars[-22]["c"] / bars[-window - 1]["c"] - 1 for window in (63, 126, 252)])
        liquid = avg([b["c"] * b["v"] for b in bars[-20:]]) >= 1_000_000
        trend = close > f["sma50"] > f["sma200"]
        rel = f["rel_mom63"] > 0
        recovery = close > prior["h"] and close > o
        upper = max(b["h"] for b in bars[-56:-1])
        baseline = evaluate(bars[-201:], spy[-201:])
        result[symbol] = {
            "bar": bars[-1],
            "eligible": liquid and f["volatility_annual"] < 0.70,
            "baseline": baseline["score"],
            "f": f,
            "atr": atr,
            "strength": strength,
            "momentum": f["mom63"],
            "rel": rel,
            "trend": trend,
            "pullback": (trend and rel and recovery and 0 <= f["sma20"] - low <= 2 * atr),
            "breakout": (
                trend
                and close > upper + 0.15 * atr
                and close >= h - 0.35 * atr
                and f["volume_ratio"] >= 1.35
            ),
            "mean_reversion": (
                close > f["sma200"]
                and f["z20"] < -1.8
                and f["volatility_annual"] < 0.5
                and close > o
                and close > prior["c"]
            ),
            "risk_on": risk_on,
            "risk_on_broad": risk_on_broad,
        }
        peer_strength[sector].append(strength)
        peer_momentum[sector].append(f["mom63"])
    for symbol, f in result.items():
        sector = UNIVERSE[symbol]
        f["rank"] = f["strength"] - avg(peer_strength[sector])
        f["relative_strength"] = f["trend"] and f["rel"] and f["strength"] > 0 and f["rank"] > 0
        f["sector_regime"] = (
            f["trend"]
            and f["rel"]
            and f["risk_on_broad"]
            and (avg(peer_momentum[sector]) > benchmark_momentum)
        )
    return result


def candidate_score(mode, f):
    if not f["eligible"] or not f["risk_on"]:
        return None
    if mode in {"baseline", "baseline_risk_exit"}:
        return f["baseline"] if f["baseline"] >= 2 else None
    if mode == "challenger_ensemble":
        votes = sum(
            f[p]
            for p in (
                "relative_strength",
                "pullback",
                "breakout",
                "mean_reversion",
                "sector_regime",
            )
        )
        return votes + f["rank"] if votes >= 2 else None
    return f["rank"] if f[mode] else None


def play(panel, start, stop, mode, bps):
    friction = bps / 10000
    cash = peak = 10000.0
    positions = {}
    pending = []
    drawdown = turnover = costs = 0.0
    opportunities = gaps = 0
    trades = []
    daily_returns, exposures = [], []
    by_regime = defaultdict(list)
    previous_equity = cash
    for i in range(start, stop):
        signals = panel[i]
        marks = {s: p["bar"]["c"] for s, p in signals.items()}
        opens = {s: p["bar"]["o"] for s, p in signals.items()}
        for side, symbol, reference, signal_atr in pending:
            mark = opens[symbol]
            if abs(mark / reference - 1) > 0.15 or (
                side == "BUY" and mark * (1 + friction) > reference * 1.005
            ):
                gaps += 1
                continue
            if side == "SELL":
                qty, cost, *_ = positions.pop(symbol)
                price = mark * (1 - friction)
                cash += qty * price
                trades.append((price / cost - 1, qty * (price - cost)))
            else:
                exposure = sum(p[0] * opens[s] for s, p in positions.items())
                equity = cash + exposure
                peak = max(peak, equity)
                if equity <= 0.88 * peak or equity <= 0.965 * previous_equity:
                    continue
                sector = UNIVERSE[symbol]
                sector_value = sum(
                    p[0] * opens[s] for s, p in positions.items() if UNIVERSE[s] == sector
                )
                budget = min(
                    cash - equity * 0.40,
                    equity * 0.12,
                    equity * 0.60 - exposure,
                    equity * 0.26 - sector_value,
                )
                price = mark * (1 + friction)
                qty = max(0, int(budget / price / 1.01))
                if not qty:
                    continue
                cash -= qty * price
                positions[symbol] = (qty, price, i, mark, signal_atr)
            costs += qty * abs(price - mark)
            turnover += qty * price
        pending = []
        equity = cash + sum(p[0] * marks[s] for s, p in positions.items())
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
        daily = equity / previous_equity - 1
        daily_returns.append(daily)
        exposures.append((equity - cash) / equity)
        if i > start:
            regime = "risk_on" if panel[i - 1][next(iter(UNIVERSE))]["risk_on"] else "risk_off"
            by_regime[regime].append(daily)
        previous_equity = equity
        if i == stop - 1:
            continue
        for symbol, p in list(positions.items()):
            qty, entry, opened, high, entry_atr = p
            mark, f = marks[symbol], signals[symbol]
            high = max(high, mark)
            positions[symbol] = (qty, entry, opened, high, entry_atr)
            exit_position = mark < entry * 0.92 or mark < f["f"]["sma50"] * 0.96
            if mode == "baseline":
                exit_position |= f["baseline"] < 0.8
            elif mode == "mean_reversion":
                exit_position |= i - opened >= 5 or mark >= f["f"]["sma20"]
            else:
                stop_level = max(entry - 2.5 * entry_atr, high - 3 * f["atr"])
                exit_position |= mark < stop_level or i - opened >= 40
            if exit_position:
                pending.append(("SELL", symbol, mark, f["atr"]))
        candidates = []
        for symbol, f in signals.items():
            if symbol in positions:
                continue
            score = candidate_score(mode, f)
            if score is not None:
                candidates.append((score, symbol))
        opportunities += len(candidates)
        if equity > 0.88 * peak:
            for _, symbol in sorted(candidates, key=lambda x: (-x[0], x[1]))[
                : min(2, 5 - len(positions))
            ]:
                pending.append(("BUY", symbol, marks[symbol], signals[symbol]["atr"]))
    wins = [p for _, p in trades if p > 0]
    losses = [p for _, p in trades if p < 0]
    volatility = sigma(daily_returns)
    return {
        "annualized_sharpe_zero_rate": round(avg(daily_returns) / volatility * sqrt(252), 3)
        if volatility > 0 and len(daily_returns) >= 60
        else None,
        "profit_factor_closed_trades": round(sum(wins) / -sum(losses), 3) if losses else None,
        "closed_win_loss_flat": [len(wins), len(losses), len(trades) - len(wins) - len(losses)],
        "mean_market_exposure_pct": round(avg(exposures) * 100, 3),
        "regime_daily_return_bps": {
            name: {"sessions": len(rs), "mean_bps": round(avg(rs) * 10000, 3)}
            for name, rs in by_regime.items()
        },
        "return_pct": round((equity / 10000 - 1) * 100, 3),
        "max_drawdown_pct": round(drawdown * 100, 3),
        "closed_trades": len(trades),
        "open_positions": len(positions),
        "eligible_opportunities": opportunities,
        "gap_rejections": gaps,
        "closed_trade_mean_net_pct": round(avg([r for r, _ in trades]) * 100, 3)
        if trades
        else None,
        "closed_pnl_per_eligible_opportunity_usd": round(
            sum(p for _, p in trades) / opportunities, 3
        )
        if opportunities
        else None,
        "turnover_times_starting_equity": round(turnover / 10000, 3),
        "modeled_execution_cost_usd": round(costs, 2),
    }


def run(source):
    data = {}
    hashes = {}
    for symbol in sorted((*UNIVERSE, "SPY", "QQQ")):
        raw = (source / (symbol + ".research.json")).read_bytes()
        hashes[symbol] = hashlib.sha256(raw).hexdigest()
        bars = [
            dict(zip(("day", "o", "h", "l", "c", "v"), row, strict=True)) for row in json.loads(raw)
        ]
        clean = validate_bars(bars, bars[-1]["day"])
        if len(clean) != len(bars):
            raise ValueError(f"invalid or duplicate bars for {symbol}")
        data[symbol] = clean
    days = [b["day"] for b in data["SPY"]]
    expected = [str(s.date()) for s in calendar().sessions_in_range(days[0], days[-1])]
    if days != expected or any([b["day"] for b in bars] != days for bars in data.values()):
        raise ValueError("historical market sessions incomplete")
    if len(days) <= 300 or HOLDOUT_START not in days:
        raise ValueError("insufficient comparison history")
    panel = {i: panel_at(data, i) for i in range(252, len(days))}
    holdout = days.index(HOLDOUT_START)
    splits = {"earlier": (252, holdout), "holdout": (holdout, len(days))}
    return {
        "policy": POLICY,
        "mode": "HISTORICAL_REPLAY",
        "promoted": False,
        "source": "Alpaca Market Data historical IEX daily bars (default raw adjustment)",
        "input_sha256": hashes,
        "first_day": days[0],
        "last_day": days[-1],
        "sessions_per_symbol": len(days),
        "universe": UNIVERSE,
        "benchmarks": ["SPY", "QQQ"],
        "event_catalysts": "INSUFFICIENT_SOURCE",
        "limitations": [
            "Single IEX venue and current-ticker sample. No delistings, survivorship correction or historical universe.",
            "Raw prices, no total-return dividends or comprehensive corporate actions. Gap guards do not correct shares.",
            "Existing historical data was fetched in one batch. No original provider publication timestamps or revisions.",
            "Signal-day close with a next-session opening-price proxy, cash allocation marked at that opening, and entry gaps beyond a 0.5% buy limit skipped. No later intraday limit-fill assumption. Portfolios reset per segment and open trades are marked.",
            "Modeled combined spread/slippage 12/30/60 bps per side, zero commission. No measured spread, fees or market impact.",
            "Baseline reimplementation uses the same opening proxy and allocation as the challengers. It omits broker partials, account activity, liquidity during the order window, and the hourly runtime admission gates.",
            "One historical chronological holdout in a small survivor sample. This comparison is retrospective and has no authority to promote an execution policy.",
        ],
        "segments": {
            name: {
                "start_day": days[a],
                "end_day": days[b - 1],
                "spy_return_pct": round(
                    (data["SPY"][b - 1]["c"] / data["SPY"][a]["c"] - 1) * 100, 3
                ),
                "qqq_return_pct": round(
                    (data["QQQ"][b - 1]["c"] / data["QQQ"][a]["c"] - 1) * 100, 3
                ),
                "strategies": {
                    m: {str(cost): play(panel, a, b, m, cost) for cost in (12, 30, 60)}
                    for m in MODES
                },
            }
            for name, (a, b) in splits.items()
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_directory", type=Path)
    print(
        json.dumps(
            run(parser.parse_args().input_directory), indent=2, sort_keys=True, allow_nan=False
        )
    )
