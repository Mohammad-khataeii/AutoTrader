"""Causal, paper-only, next-session EOD entry timing.

The signal remains certified at yesterday's close. The entry quote and all
completed minute candles must be known BEFORE a broker order is submitted.
This is a pricing/entry-timing guard, not a claim to predict the day's low.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_DOWN
import os

from .intraday_market import IntradayData, ObservationError
from .sessions import instant, next_day, session

D = Decimal
CENT = D("0.01")
MINUTES_AFTER_OPEN = 12
MAX_MINUTES_AFTER_OPEN = 55


def _d(value):
    result = D(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError("invalid_entry_price")
    return result


def assess(*, now, opening, certified_close, stock_bars, benchmark_bars, quote):
    """Assess only complete and recent IEX one-minute data and a fresh IEX ask.

    Return an explicit reason on uncertainty instead of using tomorrow's low,
    downloading future bars, or silently falling back to an instant buy.
    """
    if now < opening + timedelta(minutes=MINUTES_AFTER_OPEN):
        return {"status": "WAIT", "reason": "adaptive_observing_open"}
    if now >= opening + timedelta(minutes=MAX_MINUTES_AFTER_OPEN):
        return {"status": "WAIT", "reason": "adaptive_entry_window_ended"}
    try:
        ceiling = (_d(certified_close) * D("1.005")).quantize(CENT, rounding=ROUND_DOWN)
        end = now.replace(second=0, microsecond=0)
        def clean(items):
            cleaned = []
            for item in items:
                stamp = instant(item["t"])
                if not opening <= stamp < end:
                    continue  # Never read a forming bar.
                if end - stamp > timedelta(minutes=8):
                    continue
                cleaned.append((stamp, _d(item["c"]), _d(item["l"]), _d(item["h"])))
            cleaned.sort(key=lambda item: item[0])
            if len(cleaned) < 3 or end - cleaned[-1][0] > timedelta(minutes=3):
                raise ValueError("adaptive_minute_history_stale")
            if len({item[0] for item in cleaned}) != len(cleaned):
                raise ValueError("adaptive_duplicate_minute")
            return cleaned
        stock = clean(stock_bars)
        benchmark = clean(benchmark_bars)
        qtime = instant(quote["t"])
        if qtime > now + timedelta(seconds=2) or now - qtime > timedelta(seconds=90):
            return {"status": "WAIT", "reason": "adaptive_quote_stale"}
        bid, ask = _d(quote["bp"]), _d(quote["ap"])
        if bid > ask or (ask - bid) / bid > D("0.006"):
            return {"status": "WAIT", "reason": "adaptive_quote_spread_or_crossed"}
        if abs(ask / stock[-1][1] - D(1)) > D("0.009"):
            return {"status": "WAIT", "reason": "adaptive_bar_quote_disagreement"}
        if benchmark[-1][1] < benchmark[-3][1] * D("0.9965"):
            return {"status": "WAIT", "reason": "adaptive_market_selling_accelerating"}
        closes = [row[1] for row in stock[-3:]]
        declining = closes[0] > closes[1] > closes[2] and (
            closes[2] < closes[0] * D("0.998")
        )
        if declining:
            return {"status": "WAIT", "reason": "adaptive_stock_still_declining"}
        if closes[-1] < closes[-2] * D("0.9985"):
            return {"status": "WAIT", "reason": "adaptive_rebound_not_confirmed"}
        if ask > ceiling:
            return {"status": "WAIT", "reason": "adaptive_price_above_eod_cap"}
        # Allow a small execution cushion, never more than the original
        # certified daily-price limit. The broker still validates quantity.
        limit = min(ceiling, (ask * D("1.0012")).quantize(CENT, rounding=ROUND_DOWN))
        if limit < ask:
            return {"status": "WAIT", "reason": "adaptive_no_marketability_room"}
        return {
            "status": "READY", "reason": "adaptive_stabilized_iex_entry",
            "limit_price": str(limit), "iex_ask": str(ask),
            "recent_iex_close": str(closes[-1]), "certified_close": str(_d(certified_close)),
            "feed": "iex", "last_bar_at": stock[-1][0].isoformat(),
            "quote_at": qtime.isoformat(),
        }
    except (KeyError, TypeError, ValueError, ArithmeticError, IndexError):
        return {"status": "WAIT", "reason": "adaptive_unverifiable_quote_or_bars"}


def observe(signal, now, *, data_factory=IntradayData):
    """GET-only market observation, never touches the broker's order endpoint."""
    day = signal["day"]
    opening, _ = session(next_day(day))
    if now < opening + timedelta(minutes=MINUTES_AFTER_OPEN):
        return {"status": "WAIT", "reason": "adaptive_observing_open"}
    if now >= opening + timedelta(minutes=MAX_MINUTES_AFTER_OPEN):
        return {"status": "WAIT", "reason": "adaptive_entry_window_ended"}
    end = now.replace(second=0, microsecond=0)
    start = max(opening, end - timedelta(minutes=8))
    symbols = list(dict.fromkeys([signal["symbol"], "SPY"]))
    if signal["symbol"] == "SPY":
        return {"status": "WAIT", "reason": "adaptive_benchmark_not_tradable"}
    try:
        data = data_factory()
        try:
            prices = data.bars(symbols, "iex", start, end)
            quotes = data.snapshots([signal["symbol"]], "iex")
        finally:
            data.close()
        quote = quotes.get(signal["symbol"], {}).get("latestQuote")
        if not isinstance(quote, dict):
            return {"status": "WAIT", "reason": "adaptive_quote_unavailable"}
        return assess(
            now=now, opening=opening, certified_close=signal["features"]["close"],
            stock_bars=prices.get(signal["symbol"], []),
            benchmark_bars=prices.get("SPY", []), quote=quote,
        )
    except (ObservationError, KeyError, ValueError, TypeError):
        return {"status": "WAIT", "reason": "adaptive_market_data_unavailable"}


def mode():
    """Explicit opt-in. Legacy mode is kept for reproducible prior tests."""
    value = os.getenv("STOCKSWATCH_EOD_ENTRY_MODE", "legacy").strip().lower()
    if value not in ("legacy", "adaptive"):
        raise ValueError("invalid_stockswatch_eod_entry_mode")
    return value
