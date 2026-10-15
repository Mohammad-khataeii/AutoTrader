from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from statistics import pstdev

from autotrader.domain import Candle, DataQuality, MarketFeatures


def _ema(values: Sequence[Decimal], period: int) -> Decimal | None:
    if len(values) < period:
        return None
    alpha = Decimal("2") / Decimal(period + 1)
    ema = sum(values[:period]) / Decimal(period)
    for value in values[period:]:
        ema = (value * alpha) + (ema * (Decimal("1") - alpha))
    return ema


def _rsi(closes: Sequence[Decimal], period: int = 14) -> Decimal | None:
    if len(closes) <= period:
        return None
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for prev, current in zip(closes[-period - 1 : -1], closes[-period:], strict=True):
        change = current - prev
        gains.append(max(change, Decimal("0")))
        losses.append(abs(min(change, Decimal("0"))))
    avg_gain = sum(gains) / Decimal(period)
    avg_loss = sum(losses) / Decimal(period)
    if avg_loss == 0:
        return Decimal("100")
    rs = avg_gain / avg_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


def _atr(candles: Sequence[Candle], period: int = 14) -> Decimal | None:
    if len(candles) <= period:
        return None
    ranges: list[Decimal] = []
    window = candles[-period:]
    prev_close = candles[-period - 1].close
    for candle in window:
        ranges.append(max(candle.high - candle.low, abs(candle.high - prev_close), abs(candle.low - prev_close)))
        prev_close = candle.close
    return sum(ranges) / Decimal(period)


def _bollinger(closes: Sequence[Decimal], period: int = 20) -> tuple[Decimal, Decimal, Decimal] | None:
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = sum(window) / Decimal(period)
    std = Decimal(str(pstdev(float(value) for value in window)))
    return mid + Decimal("2") * std, mid, mid - Decimal("2") * std


def _vwap(candles: Sequence[Candle], period: int = 20) -> Decimal | None:
    if len(candles) < period:
        return None
    numerator = Decimal("0")
    denominator = Decimal("0")
    for candle in candles[-period:]:
        typical = (candle.high + candle.low + candle.close) / Decimal("3")
        numerator += typical * candle.volume
        denominator += candle.volume
    return numerator / denominator if denominator > 0 else None


def _adx(candles: Sequence[Candle], period: int = 14) -> Decimal | None:
    if len(candles) <= period:
        return None
    plus_dm: list[Decimal] = []
    minus_dm: list[Decimal] = []
    tr_values: list[Decimal] = []
    for prev, current in zip(candles[-period - 1 : -1], candles[-period:], strict=True):
        up_move = current.high - prev.high
        down_move = prev.low - current.low
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else Decimal("0"))
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else Decimal("0"))
        tr_values.append(max(current.high - current.low, abs(current.high - prev.close), abs(current.low - prev.close)))
    tr_sum = sum(tr_values)
    if tr_sum == 0:
        return Decimal("0")
    plus_di = Decimal("100") * sum(plus_dm) / tr_sum
    minus_di = Decimal("100") * sum(minus_dm) / tr_sum
    denominator = plus_di + minus_di
    return Decimal("0") if denominator == 0 else Decimal("100") * abs(plus_di - minus_di) / denominator


def calculate_features(candles: Sequence[Candle], order_book_imbalance: Decimal | None = None, spread_bps: Decimal | None = None) -> MarketFeatures:
    if not candles:
        raise ValueError("At least one candle is required.")
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    latest = ordered[-1]
    closes = [candle.close for candle in ordered]
    volumes = [candle.volume for candle in ordered]

    bollinger = _bollinger(closes)
    macd_fast = _ema(closes, 12)
    macd_slow = _ema(closes, 26)
    macd = macd_fast - macd_slow if macd_fast is not None and macd_slow is not None else None
    macd_series: list[Decimal] = []
    if len(closes) >= 35:
        for index in range(26, len(closes) + 1):
            fast = _ema(closes[:index], 12)
            slow = _ema(closes[:index], 26)
            if fast is not None and slow is not None:
                macd_series.append(fast - slow)
    support_window = ordered[-20:] if len(ordered) >= 20 else ordered
    avg_volume = sum(volumes[-20:]) / Decimal(min(len(volumes), 20))
    recent_volume = volumes[-1]
    relative_volume = recent_volume / avg_volume if avg_volume > 0 else None
    previous_close = closes[-2] if len(closes) >= 2 else closes[-1]
    momentum = (latest.close - previous_close) / previous_close if previous_close > 0 else None
    volatility = Decimal(str(pstdev(float(value) for value in closes[-20:]))) if len(closes) >= 2 else None
    resistance = max(candle.high for candle in support_window)
    support = min(candle.low for candle in support_window)

    quality = DataQuality.GOOD
    missing = []
    if len(ordered) < 50:
        quality = DataQuality.INSUFFICIENT_HISTORY
        missing.append("long-horizon indicators")

    upper, mid, lower = bollinger if bollinger is not None else (None, None, None)
    breakout_distance = (latest.close - resistance) / resistance if resistance > 0 else None
    volume_acceleration = None
    if len(volumes) >= 6:
        recent = sum(volumes[-3:]) / Decimal("3")
        previous = sum(volumes[-6:-3]) / Decimal("3")
        volume_acceleration = recent / previous if previous > 0 else None

    return MarketFeatures(
        symbol=latest.symbol,
        timestamp=latest.timestamp,
        timeframe=latest.timeframe,
        data_quality=quality,
        metadata={"source": latest.source, "observations": len(ordered), "missing": missing},
        rsi=_rsi(closes),
        macd=macd,
        macd_signal=_ema(macd_series, 9) if macd_series else None,
        ema_9=_ema(closes, 9),
        ema_21=_ema(closes, 21),
        ema_50=_ema(closes, 50),
        ema_200=_ema(closes, 200),
        atr=_atr(ordered),
        bollinger_upper=upper,
        bollinger_mid=mid,
        bollinger_lower=lower,
        vwap=_vwap(ordered),
        adx=_adx(ordered),
        relative_volume=relative_volume,
        momentum=momentum,
        volatility=volatility,
        support=support,
        resistance=resistance,
        order_book_imbalance=order_book_imbalance,
        spread_bps=spread_bps,
        breakout_distance=breakout_distance,
        volume_acceleration=volume_acceleration,
    )

