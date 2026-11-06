"""Completed, synchronized observations shared by all crypto challengers."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal as D
from itertools import pairwise
from statistics import correlation

from autotrader.domain import Candle
from autotrader.market_data.synchronization import cutoff
from autotrader.raoe.regime import aggregate, atr, dimension

STEP = timedelta(minutes=5)
PEERS = ("BTC-EUR", "ETH-EUR")
VERSION = "crypto-7000-challenger/1"


def window(bars: list[Candle], symbol: str, at: datetime, count: int) -> list[Candle]:
    """Only the exact contiguous suffix, with no stale substitution or duplicate bars."""
    end = cutoff(at)
    start = end - count * STEP
    rows = sorted((b for b in bars if start <= b.timestamp < end), key=lambda b: b.timestamp)
    if len(rows) != count:
        return []
    for index, b in enumerate(rows):
        if (
            b.timestamp != start + index * STEP
            or b.timeframe != "5m"
            or b.symbol != symbol
            or not all(v.is_finite() for v in (b.open, b.high, b.low, b.close, b.volume))
            or not 0 < b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
            or b.volume < 0
        ):
            return []
    return rows


def returns(bars: list[Candle]) -> dict[int, D]:
    return {
        minutes: bars[-1].close / bars[-1 - minutes // 5].close - 1 for minutes in (5, 15, 30, 60)
    }


def _changes(bars: list[Candle]) -> list[float]:
    return [float(b.close / a.close - 1) for a, b in pairwise(bars)]


def benchmark_context(histories: dict[str, list[Candle]], at: datetime) -> dict:
    synchronized = {s: window(bars, s, at, 25) for s, bars in histories.items()}
    synchronized = {s: b for s, b in synchronized.items() if b}
    peer_returns = {s: returns(synchronized[s]) for s in PEERS if s in synchronized}
    peer_volatility = {}
    trends = {}
    for s in peer_returns:
        bars = synchronized[s]
        recent = sum(abs(x) for x in _changes(bars[-4:])) / 3
        prior = sum(abs(x) for x in _changes(bars[:-3])) / 21
        peer_volatility[s] = recent / prior if prior else None
        trends[s] = dimension(aggregate(histories[s], 60, at), 60, at)["trend"]
    matched = [returns(b)[60] for s, b in synchronized.items() if s not in PEERS]
    ready = len(peer_returns) == 2
    declining = ready and all(r[15] < 0 and r[60] < 0 for r in peer_returns.values())
    rising = ready and all(r[15] > 0 and r[60] > 0 for r in peer_returns.values())
    accelerating = declining and all((v or 0) > 1 for v in peer_volatility.values())
    co_movement = None
    if ready:
        btc, eth = (_changes(synchronized[s]) for s in PEERS)
        if len(set(btc)) > 1 and len(set(eth)) > 1:
            co_movement = correlation(btc, eth)
    return {
        "version": VERSION,
        "completed_at": cutoff(at).isoformat(),
        "status": "READY" if ready else "INSUFFICIENT_EVIDENCE",
        "regime": (
            "UNKNOWN"
            if not ready
            else "CORRELATED_SELLOFF"
            if accelerating and (co_movement or 0) > 0
            else "JOINT_DECLINE"
            if declining
            else "JOINT_ADVANCE"
            if rising
            else "MIXED"
        ),
        "returns": {s: {str(k): str(v) for k, v in r.items()} for s, r in peer_returns.items()},
        "hourly_trends": trends,
        "volatility_expansion": peer_volatility,
        "benchmark_return_correlation": co_movement,
        "breadth": {
            "advancing": sum(v > 0 for v in matched),
            "sample": len(matched),
            "scope": "synchronized observed non-benchmark markets",
        },
    }


def entry_context(
    symbol: str,
    histories: dict[str, list[Candle]],
    at: datetime,
    entry: D,
    stop: D,
    strategy: str,
    macro: dict | None = None,
    recorded_trends: tuple[str, str] | None = None,
) -> dict:
    macro = benchmark_context(histories, at) if macro is None else macro
    raw = histories.get(symbol, [])
    bars = window(raw, symbol, at, 25)
    h15 = dimension(aggregate(raw, 15, at), 15, at)["trend"]
    hourly = dimension(aggregate(raw, 60, at), 60, at)["trend"]
    trend_source = "RECONSTRUCTED_COMPLETED_CANDLES"
    if recorded_trends and "UNKNOWN" in {h15, hourly}:
        h15 = recorded_trends[0] if h15 == "UNKNOWN" else h15
        hourly = recorded_trends[1] if hourly == "UNKNOWN" else hourly
        trend_source = "INCLUDES_ORIGINAL_SIGNAL_TIMEFRAMES"
    result = {
        "trend_source": trend_source,
        "macro": macro,
        "hourly": hourly,
        "15m": h15,
        "asset_return_60m": None,
        "relative_return_60m": None,
        "stop_atr": None,
        "entry_chase_atr": None,
        "structure": "UNKNOWN",
        "structure_floor": None,
        "retest_level": None,
        "checks": {"macro": None, "recovery": None, "a3": None},
    }
    if macro["status"] == "READY":
        result["checks"]["macro"] = macro["regime"] not in {"CORRELATED_SELLOFF", "JOINT_DECLINE"}
    if not bars:
        return result
    recent = returns(bars)[60]
    result["asset_return_60m"] = str(recent)
    relative = None
    if macro["status"] == "READY":
        relative = recent - sum(D(macro["returns"][s]["60"]) for s in PEERS) / 2
        result["relative_return_60m"] = str(relative)
    noise = atr(bars[:-1])
    current, previous = bars[-1], bars[-2]
    ceiling = max(b.high for b in bars[-14:-2])
    floor = min(b.low for b in bars[-14:-2])
    if previous.close > ceiling:
        structure = (
            "HELD_RETEST"
            if current.low <= ceiling <= current.close
            else "FAILED_BREAKOUT"
            if current.close < ceiling
            else "BREAKOUT_UNRETESTED"
        )
    elif current.close > ceiling:
        structure = "BREAKOUT_UNRETESTED"
    elif current.close > previous.close > bars[-3].close and current.low > previous.low:
        structure = "PERSISTENT_RECOVERY"
    elif (
        h15 == "RANGING" and hourly == "RANGING" and current.low <= floor and current.close > floor
    ):
        structure = "RANGE_RECLAIM"
    else:
        structure = "UNCONFIRMED"
    if structure in {"HELD_RETEST", "BREAKOUT_UNRETESTED", "FAILED_BREAKOUT"}:
        result["retest_level"] = str(ceiling)
    result["structure"] = structure
    result["structure_floor"] = str(min(b.low for b in bars[-4:]) - noise / 5)
    if noise:
        result["stop_atr"] = str((entry - stop) / noise)
        result["entry_chase_atr"] = str((entry - current.close) / noise)
    if strategy == "RAOE_EARLY_RECOVERY" and "UNKNOWN" not in {h15, hourly}:
        result["checks"]["recovery"] = "BEARISH" not in {h15, hourly} and structure in {
            "PERSISTENT_RECOVERY",
            "HELD_RETEST",
        }
    if strategy.startswith("A3") and relative is not None and noise:
        result["checks"]["a3"] = (
            structure in {"HELD_RETEST", "PERSISTENT_RECOVERY"}
            and relative >= 0
            and (entry - stop) >= noise
            and entry - current.close <= noise / 2
        )
    return result
