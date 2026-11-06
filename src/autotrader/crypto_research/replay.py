"""Chronological, cost-stressed candle proxy; never turns prices into broker fills."""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal as D
from statistics import mean

from autotrader.domain import Candle

from .context import STEP, cutoff

INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
POLICIES = (
    "bracket",
    "progress_time",
    "giveback",
    "partial",
    "failed_breakout",
    "regime_exit",
    "consolidation",
)
OUTCOMES = ("TARGET_FIRST", "STOP_FIRST", "TIME", "DISCRETIONARY")


@dataclass(frozen=True)
class Outcome:
    kind: str
    net: D
    fees: D
    turnover: D
    minutes: int
    mfe: D
    mae: D


def replay(
    bars: list[Candle],
    at: datetime,
    *,
    entry: D,
    quantity: D,
    stop: D,
    target: D,
    horizon: int,
    spread_bps: D,
    fee_bps: D,
    slippage_bps: D,
    policy: str = "bracket",
    extra_bps: D = D(0),
    adverse_cutoffs: frozenset[datetime] = frozenset(),
    invalidation: D | None = None,
) -> Outcome | None:
    """Entry is already executable-priced. All exits are bid-haircut OHLC proxies.

    Skip the entry-straddling bar. First missing bar censors the remaining path.
    Stop takes precedence on a dual-touch bar, with adverse opening gaps honored.
    """
    if policy not in POLICIES:
        raise ValueError("unknown_exit_policy")
    if not (
        0 < stop < entry < target
        and quantity > 0
        and horizon > 0
        and min(spread_bps, fee_bps, slippage_bps, extra_bps) >= 0
    ):
        return None
    start = cutoff(at)
    if start < at:
        start += STEP
    end = cutoff(at + horizon * STEP)
    if end <= start:
        return None
    rows = sorted((b for b in bars if start <= b.timestamp < end), key=lambda b: b.timestamp)
    if len({b.timestamp for b in rows}) != len(rows):
        return None
    fee = fee_bps / 10000
    bid_factor = 1 - spread_bps / 20000
    execution_factor = 1 - (slippage_bps + extra_bps) / 10000
    if min(bid_factor, execution_factor, 1 - fee) <= 0:
        return None
    entry_gross = entry * quantity
    gross, remaining = D(0), quantity
    best_close = entry
    mfe = mae = D(0)
    progress = (target - entry) / 2
    first = None
    protective = stop
    closes_below = 0
    exit_next_open = False
    recent_ranges = []

    for i, b in enumerate(rows):
        if (
            b.timestamp != start + i * STEP
            or b.timeframe != "5m"
            or not all(v.is_finite() for v in (b.low, b.high, b.open, b.close))
            or not 0 < b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
        ):
            return None
        opening, high, low, close = (v * bid_factor for v in (b.open, b.high, b.low, b.close))
        # Extrema on the exit bar can occur after a touch. Use whole bars only
        # for positions surviving the bar, and the exit price for a touch.
        reason, price = None, close
        if exit_next_open:
            reason, price = ("STOP_FIRST" if opening <= protective else "DISCRETIONARY"), opening
        elif low <= protective:
            reason, price = "STOP_FIRST", min(opening, protective)
        elif high >= target:
            first = first or "TARGET_FIRST"
            if policy != "partial" or remaining < quantity:
                reason, price = "TARGET_FIRST", target
            else:
                gross += quantity / 2 * target * execution_factor
                remaining -= quantity / 2
        if reason is None:
            mfe, mae = max(mfe, high - entry), min(mae, low - entry)
            best_close = max(best_close, close)
            if policy == "giveback" and best_close >= entry + progress:
                # Applies only from the next bar. A net-cost floor includes fees on both legs.
                break_even = entry * (1 + fee) / ((1 - fee) * execution_factor)
                if close > break_even:
                    protective = max(protective, break_even, entry + (best_close - entry) / 2)
            early = (
                policy == "progress_time"
                and i + 1 >= max(1, horizon // 2)
                and best_close < entry + progress
            )
            if policy == "regime_exit":
                exit_next_open = b.timestamp + STEP in adverse_cutoffs
            if policy == "failed_breakout" and invalidation:
                closes_below = closes_below + 1 if close < invalidation else 0
                exit_next_open = closes_below >= 2
            if policy == "consolidation":
                recent_ranges = [*recent_ranges[-2:], high - low]
                exit_next_open = (
                    len(recent_ranges) == 3
                    and best_close < entry + progress
                    and max(recent_ranges) < (entry - stop) / 2
                )
            if early or b.timestamp + STEP == end:
                reason = "TIME"
        if reason:
            mfe, mae = max(mfe, price - entry), min(mae, price - entry)
            gross += remaining * price * execution_factor
            fees = (entry_gross + gross) * fee
            return Outcome(
                first or reason,
                gross - entry_gross - fees,
                fees,
                entry_gross + gross,
                int((b.timestamp + STEP - at).total_seconds() // 60),
                mfe / entry,
                mae / entry,
            )
    return None


def block_interval(days: dict, *, seed: int = 7000) -> list[float] | None:
    """Resample UTC days, preserving clusters within a day and trade weighting."""
    groups = list(days.values())
    if len(groups) < 3:
        return None
    rng = random.Random(seed)
    draws = []
    for _ in range(2000):
        sample = rng.choices(groups, k=len(groups))
        draws.append(sum(sum(g) for g in sample) / sum(len(g) for g in sample))
    draws.sort()
    return [round(draws[49], 4), round(draws[1949], 4)]


def estimate(
    rows: list[tuple[datetime, Outcome]], *, minimum_days: int = 30, minimum_trades: int = 60
) -> dict:
    days = defaultdict(list)
    for at, row in sorted(rows, key=lambda item: item[0]):
        days[at.date()].append(float(row.net))
    base = {"observations": len(rows), "observed_utc_days": len(days)}
    if len(days) < minimum_days or len(rows) < minimum_trades:
        return {**base, "status": INSUFFICIENT, "net_expectancy_eur": None, "probabilities": None}
    counts = Counter(row.kind for _, row in rows)
    nets = sorted(float(row.net) for _, row in rows)
    time_nets = [float(row.net) for _, row in rows if row.kind == "TIME"]
    return {
        **base,
        "status": "DESCRIPTIVE_ESTIMATE",
        "net_expectancy_eur": mean(nets),
        "interval_95_day_bootstrap": block_interval(days),
        "probabilities": {kind: counts[kind] / len(rows) for kind in OUTCOMES},
        "net_quantiles_eur": {str(p): nets[int((len(nets) - 1) * p)] for p in (0.05, 0.5, 0.95)},
        "time_exit_mean_eur": mean(time_nets) if time_nets else None,
        "time_exit_mean_minutes": mean(row.minutes for _, row in rows if row.kind == "TIME")
        if time_nets
        else None,
        "mean_favorable_excursion": mean(float(row.mfe) for _, row in rows),
        "mean_adverse_excursion": mean(float(row.mae) for _, row in rows),
    }
