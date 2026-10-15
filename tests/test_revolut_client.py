from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from autotrader.market_data.revolut import (
    MarketDataError,
    RevolutXPublicClient,
    _retry_after_seconds,
)

DOC_TS_MS = 1785313433816


@pytest.mark.asyncio
async def test_v2_public_order_book_parses_documented_shape() -> None:
    client = RevolutXPublicClient(region="EEA")

    async def fake_request(_path: str, _params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "data": {
                "asks": [{"price": "4005.00", "quantity": "1.7000", "count": 3}],
                "bids": [{"price": "4000.00", "quantity": "0.25", "count": 1}],
            },
            "metadata": {"region": "EEA", "timestamp": DOC_TS_MS},
        }

    client._request = fake_request  # type: ignore[method-assign]
    try:
        book = await client.get_order_book("ETH-EUR")
    finally:
        await client.close()

    assert book.best_bid == Decimal("4000.00")
    assert book.best_ask == Decimal("4005.00")
    assert book.timestamp == datetime.fromtimestamp(DOC_TS_MS / 1000, tz=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        {"asks": [], "bids": [{"price": "4000.00", "quantity": "0.25"}]},
        {"asks": [{"price": "4005.00", "quantity": "1"}], "bids": [{"price": "-1", "quantity": "0.25"}]},
        {"asks": [{"price": "4005.00"}], "bids": [{"price": "4000.00", "quantity": "0.25"}]},
        {"asks": [{"price": "3995.00", "quantity": "1"}], "bids": [{"price": "4000.00", "quantity": "0.25"}]},
    ],
)
async def test_v2_public_order_book_rejects_unusable_books(data: dict[str, Any]) -> None:
    client = RevolutXPublicClient(region="EEA")

    async def fake_request(_path: str, _params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"data": data, "metadata": {"region": "EEA", "timestamp": DOC_TS_MS}}

    client._request = fake_request  # type: ignore[method-assign]
    try:
        with pytest.raises(MarketDataError):
            await client.get_order_book("ETH-EUR")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_historical_candles_use_start_epoch_milliseconds() -> None:
    client = RevolutXPublicClient(region="EEA")
    start = datetime.now(tz=UTC).replace(second=0, microsecond=0) - timedelta(minutes=20)
    start_ms = int(start.timestamp() * 1000)

    async def fake_request(_path: str, _params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "data": [
                {"start": start_ms, "open": "119800.00", "high": "120100.00", "low": "119700.00", "close": "120000.00", "volume": "0.25"},
                {
                    "start": start_ms + 300_000,
                    "open": "120000.00",
                    "high": "120250.00",
                    "low": "119950.00",
                    "close": "120150.00",
                    "volume": "0.18",
                },
            ],
            "metadata": {"region": "EEA", "timestamp": DOC_TS_MS},
        }

    client._request = fake_request  # type: ignore[method-assign]
    try:
        candles = await client.get_candles("BTC-EUR", 5, start_ms, start_ms + 600_000)
    finally:
        await client.close()

    assert candles[0].timestamp == start
    assert candles[1].close == Decimal("120150.00")


@pytest.mark.asyncio
async def test_candles_reject_missing_interval_and_forming_records() -> None:
    client = RevolutXPublicClient(region="EEA")
    start = datetime.now(tz=UTC).replace(second=0, microsecond=0) - timedelta(minutes=10)
    start_ms = int(start.timestamp() * 1000)

    async def fake_request(_path: str, _params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "data": [
                {"start": start_ms, "open": "1", "high": "2", "low": "1", "close": "2", "volume": "1"},
                {"start": start_ms + 600_000, "open": "2", "high": "3", "low": "2", "close": "3", "volume": "1"},
            ],
            "metadata": {"region": "EEA", "timestamp": DOC_TS_MS},
        }

    client._request = fake_request  # type: ignore[method-assign]
    try:
        with pytest.raises(MarketDataError, match="Missing candle interval"):
            await client.get_candles("BTC-EUR", 5, start_ms, start_ms + 600_000)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_public_pair_configuration_uses_documented_fields_and_skips_disabled() -> None:
    client = RevolutXPublicClient(region="EEA")

    async def fake_request(_path: str, _params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "BTC/EUR": {
                "base": "BTC",
                "quote": "EUR",
                "base_step": "0.0000001",
                "quote_step": "0.01",
                "min_order_size": "0.0000001",
                "max_order_size": "1000",
                "min_order_size_quote": "0.01",
                "status": "active",
            },
            "ETH/EUR": {
                "base": "ETH",
                "quote": "EUR",
                "base_step": "0.0000001",
                "quote_step": "0.01",
                "min_order_size": "0.00001",
                "max_order_size": "9000",
                "min_order_size_quote": "0.01",
                "status": "disabled",
            },
        }

    client._request = fake_request  # type: ignore[method-assign]
    try:
        pairs = await client.get_pairs()
    finally:
        await client.close()

    assert [pair.symbol for pair in pairs] == ["BTC-EUR"]
    assert pairs[0].price_step == Decimal("0.01")
    assert pairs[0].quantity_step == Decimal("0.0000001")
    assert pairs[0].min_order_quote == Decimal("0.01")


def test_retry_after_header_is_documented_as_milliseconds() -> None:
    assert _retry_after_seconds("1500") == Decimal("1.5")
