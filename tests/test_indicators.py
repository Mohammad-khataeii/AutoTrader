from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from autotrader.domain import Candle, DataQuality, utc_now
from autotrader.indicators import calculate_features


def candles(count: int = 240) -> list[Candle]:
    start = utc_now()
    result: list[Candle] = []
    for index in range(count):
        close = Decimal("100") + Decimal(index) / Decimal("10")
        result.append(
            Candle(
                "BTC-EUR",
                start + timedelta(minutes=index),
                close - Decimal("0.5"),
                close + Decimal("1"),
                close - Decimal("1"),
                close,
                Decimal("10") + Decimal(index % 5),
                source="test",
            )
        )
    return result


def test_features_are_ordered_and_complete_for_sufficient_history() -> None:
    features = calculate_features(list(reversed(candles())))
    assert features.data_quality is DataQuality.GOOD
    assert features.ema_200 is not None
    assert features.rsi is not None
    assert features.support is not None
    assert features.resistance is not None


def test_insufficient_history_is_explicit() -> None:
    features = calculate_features(candles(20))
    assert features.data_quality is DataQuality.INSUFFICIENT_HISTORY
    assert "long-horizon indicators" in features.metadata["missing"]

