"""Small completed-candle breakout machine; JSON state can survive worker restart."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from autotrader.domain import Candle
from autotrader.research.data import digest

D = Decimal


@dataclass
class BreakoutState:
    stage: str = "WATCHING"
    level: str | None = None
    range_low: str | None = None
    compressed_at: str | None = None
    breakout_at: str | None = None
    breakout_volume: str | None = None
    atr: str | None = None
    retest_age: int = 0
    confirmed_at: str | None = None
    event_id: str | None = None
    last_candle: str | None = None
    reason: str | None = None
    transitions: list[dict[str, str]] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def advance(state: BreakoutState, candle: Candle, prior: list[Candle], *,
            compression_width: Decimal = D(".02"), volume_ratio: Decimal = D("1.3"),
            retest_bars: int = 8, validated_history: bool = False) -> BreakoutState:
    stamp = candle.timestamp.isoformat()
    if state.last_candle is not None and stamp <= state.last_candle:
        return state
    if len(prior) < 20:
        state.last_candle = stamp
        return state
    if not validated_history and any(b.timestamp >= candle.timestamp or b.symbol != candle.symbol for b in prior):
        raise ValueError("pattern_requires_past_same_symbol_candles")
    window = prior[-20:]
    if not validated_history and any(b.timestamp - a.timestamp != timedelta(minutes=5) for a, b in zip(window, [*window[1:], candle])):
        return BreakoutState(last_candle=stamp, reason='missing_contiguous_pattern_history')

    def transition(stage: str, reason: str) -> None:
        state.stage, state.reason = stage, reason
        state.transitions = [*state.transitions[-5:], {"stage": stage, "at": stamp, "reason": reason}]

    if state.stage in {"CONFIRMED", "EXPIRED", "INVALIDATED"}:
        state = BreakoutState(last_candle=state.last_candle)
    if state.stage == "WATCHING":
        high, low = max(c.high for c in window), min(c.low for c in window)
        atr = sum((max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close)) for a, b in zip(prior[-15:-1], prior[-14:])), D(0)) / 14
        if atr > 0 and (high - low) / candle.close <= compression_width:
            state.level, state.range_low, state.atr = str(high), str(low), str(atr)
            state.compressed_at = stamp
            transition("COMPRESSED", "completed_twenty_bar_range")
    if state.stage == "COMPRESSED":
        assert state.level is not None and state.atr is not None
        mean_volume = sum((c.volume for c in window), D(0)) / 20
        if candle.close > D(state.level) + D(state.atr) * D(".1") and mean_volume > 0 and candle.volume / mean_volume >= volume_ratio:
            state.breakout_at, state.breakout_volume = stamp, str(candle.volume / mean_volume)
            state.event_id = digest((candle.symbol + ":" + stamp + ":" + state.level).encode())[:40]
            transition("BREAKOUT_DETECTED", "completed_close_and_volume_confirmation")
            transition("RETEST_PENDING", "wait_for_later_completed_retest")
        elif state.range_low and candle.close < D(state.range_low):
            transition("INVALIDATED", "compression_range_lost")
        elif state.compressed_at and (candle.timestamp - datetime.fromisoformat(state.compressed_at)).total_seconds() > retest_bars * 300:
            transition("EXPIRED", "compression_expired_without_breakout")
    elif state.stage == "RETEST_PENDING":
        assert state.level is not None and state.atr is not None
        state.retest_age += 1
        level, distance = D(state.level), D(state.atr)
        if candle.close < level - distance * D(".75"):
            transition("INVALIDATED", "breakout_invalidation_level_lost")
        elif state.retest_age > retest_bars:
            transition("EXPIRED", "retest_window_expired_no_forced_entry")
        elif candle.low <= level + distance * D(".5") and candle.close >= level and candle.close > candle.open:
            state.confirmed_at = stamp
            transition("CONFIRMED", "delayed_retest_recovered")
    state.last_candle = stamp
    return state


def replay(candles: list[Candle], **parameters: Any) -> BreakoutState:
    state = BreakoutState()
    contiguous = 0
    for index, candle in enumerate(candles):
        if index and (candle.symbol != candles[index-1].symbol or candle.timestamp <= candles[index-1].timestamp):
            raise ValueError('ambiguous_pattern_history')
        contiguous = contiguous + 1 if index and candle.timestamp - candles[index-1].timestamp == timedelta(minutes=5) else 1
        if index >= 20 and contiguous < 21:
            state = BreakoutState(last_candle=candle.timestamp.isoformat(), reason='missing_contiguous_pattern_history')
        else:
            state = advance(state, candle, candles[max(0, index - 20):index], validated_history=True, **parameters)
    return state
