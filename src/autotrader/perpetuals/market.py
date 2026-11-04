"""Public, read-only Bybit linear BTCUSDT data. Timestamps are UTC milliseconds."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from time import time

import httpx

MINUTE = 60_000
FUNDING_INTERVAL = 480 * MINUTE
SYMBOL = "BTCUSDT"


def clock_ms() -> int:
    return int(time() * 1000)


@dataclass(frozen=True)
class Bar:
    start: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None


@dataclass(frozen=True)
class Instrument:
    step: Decimal
    min_qty: Decimal
    min_notional: Decimal


def number(value: str, *, positive: bool = True) -> Decimal:
    result = Decimal(value)
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError("Invalid perpetuals market value")
    return result


class PublicMarket:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def _get(self, endpoint: str, **params):
        response = await self.client.get(
            f"https://api.bybit.com/v5/market/{endpoint}",
            params={"category": "linear", "symbol": SYMBOL, **params},
        )
        response.raise_for_status()
        body = response.json()
        if body["retCode"] != 0:
            raise ValueError("Perpetuals public market request rejected")
        return body["result"]

    async def instrument(self) -> Instrument:
        rows = (await self._get("instruments-info"))["list"]
        if len(rows) != 1:
            raise ValueError("Perpetuals instrument missing or ambiguous")
        row = rows[0]
        if (
            row["symbol"] != SYMBOL
            or row["contractType"] != "LinearPerpetual"
            or row["settleCoin"] != "USDT"
            or row["status"] != "Trading"
            or int(row["fundingInterval"]) != FUNDING_INTERVAL // MINUTE
        ):
            raise ValueError("Perpetuals contract changed; review simulator policy")
        lot = row["lotSizeFilter"]
        return Instrument(*(number(lot[key]) for key in ("qtyStep", "minOrderQty", "minNotionalValue")))

    async def bars(self, start: int, end: int, *, mark: bool, include_volume: bool = False) -> dict[int, Bar]:
        result = await self._get(
            "mark-price-kline" if mark else "kline",
            interval="1", start=start, end=end + MINUTE - 1,
            limit=(end - start) // MINUTE + 1,
        )
        if result["symbol"] != SYMBOL or result["category"] != "linear":
            raise ValueError("Perpetuals candle identity mismatch")
        bars: dict[int, Bar] = {}
        for row in result["list"]:
            t = int(row[0])
            if not start <= t <= end or t % MINUTE or t in bars:
                raise ValueError("Invalid perpetuals candle timestamp")
            volume = number(row[5], positive=False) if include_volume and not mark and len(row) > 5 else None
            if volume is not None and volume < 0:
                raise ValueError("Invalid perpetuals candle volume")
            bar = Bar(t, *(number(value) for value in row[1:5]), volume=volume)
            if not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
                raise ValueError("Invalid perpetuals candle range")
            bars[t] = bar
        return bars

    async def funding(self, start: int, end: int) -> dict[int, Decimal]:
        first = ((start + FUNDING_INTERVAL - 1) // FUNDING_INTERVAL) * FUNDING_INTERVAL
        expected = set(range(first, end + 1, FUNDING_INTERVAL))
        if not expected:
            return {}
        result = await self._get("funding/history", startTime=start - 1, endTime=end + MINUTE - 1, limit=10)
        rates = {}
        for row in result["list"]:
            timestamp = int(row["fundingRateTimestamp"])
            # The API may include the lower bound, which is outside this batch.
            if timestamp < start:
                continue
            if row["symbol"] != SYMBOL or timestamp not in expected or timestamp in rates:
                raise ValueError("Unexpected perpetuals funding event")
            rates[timestamp] = number(row["fundingRate"], positive=False)
        if set(rates) != expected:
            raise ValueError("Perpetuals funding data incomplete")
        return rates
