import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest

from autotrader.clock import at
from autotrader.domain import Candle
from autotrader.market_data.revolut import MarketDataError, RateLimitDeferred, RevolutXPublicClient
from autotrader.market_data.scheduling import PriorityGate, protective_priority
from autotrader.market_data.service import MarketDataService
from test_v4_execution import PAIR, book

BASE = datetime(2026, 1, 1, tzinfo=UTC)


class Feed:
    def __init__(self):
        self.requests = []
        self.books = 0
        self.bars = [
            Candle(
                PAIR.symbol,
                BASE + timedelta(minutes=5 * i),
                D(100),
                D(101),
                D(99),
                D(100),
                D(1000),
                timeframe="5m",
            )
            for i in range(-300, 20)
        ]

    async def get_candles(self, symbol, interval, since, until):
        self.requests.append((since, until))
        await asyncio.sleep(0)
        return [
            c
            for c in self.bars
            if since <= c.timestamp.timestamp() * 1000
            and c.timestamp.timestamp() + 300 <= until / 1000
        ]

    async def get_order_book(self, symbol, limit):
        self.books += 1
        return book("100", "100.01")


async def test_completed_cache_measures_polling_reduction_and_persists_across_clients(pg_repo):
    await pg_repo.initialize_portfolio(D(500))
    feed = Feed()
    service = MarketDataService(feed, state_store=pg_repo, cache_enabled=True)
    observations = []
    for minute in range(10):
        with at(BASE + timedelta(minutes=minute)):
            market = await service.get_validated_market(PAIR)
            assert market.usable_for_entry
            observations.append(market)
    assert len(feed.requests) == 2  # Old service: 10 full-window calls.
    assert feed.requests[1][0] == int((BASE - timedelta(minutes=10)).timestamp() * 1000)
    assert len(observations[0].candles) == 240
    other = MarketDataService(feed, state_store=pg_repo, cache_enabled=True)
    with at(BASE + timedelta(minutes=9)):
        assert (await other.get_validated_market(PAIR)).candles == observations[-1].candles
    assert len(feed.requests) == 2
    health = await pg_repo.market_data_health()
    assert health["candle_refresh"] == 2 and health["candle_cache_hit"] == 9
    assert health["candles_downloaded"] == 243
    assert health["caches"][0]["observations"] == 240


async def test_protection_reuses_same_observation_and_never_relabels_timestamp():
    feed = Feed()
    service = MarketDataService(feed, cache_enabled=True)
    with at(BASE):
        async with service.protective_cycle():
            first = await service.get_position_book(PAIR)
            second = await service.get_position_book(PAIR)
            assert first is second and feed.books == 1
            with at(BASE + timedelta(seconds=91)), pytest.raises(MarketDataError, match="stale"):
                await service.get_position_book(PAIR)
        await service.get_position_book(PAIR)
        assert feed.books == 2


async def test_shared_cooldown_and_protection_priority_are_authoritative(pg_repo):
    await pg_repo.initialize_portfolio(D(500))
    with at(BASE):
        assert await pg_repo.reserve_public_request("books") == 0
        assert await pg_repo.reserve_public_request("books", priority=0) == 1
        assert await pg_repo.reserve_public_request("books") == 2
        await pg_repo.defer_public_requests("books", 5)
        assert await pg_repo.reserve_public_request("books") == 5
        assert await pg_repo.reserve_public_request("candles") == 0
    with at(BASE + timedelta(seconds=5)):
        assert await pg_repo.reserve_public_request("books", priority=0) == 0


async def test_429_milliseconds_backoff_retry_bound_and_breaker(monkeypatch):
    client = RevolutXPublicClient()
    events = []
    cooldowns = []
    waits = []
    responses = [429, 429, 429, 429]

    async def boundary(path, params):
        return httpx.Response(
            responses.pop(0),
            headers={"Retry-After": "1500"},
            request=httpx.Request("GET", "https://example.test" + path),
        )

    async def event(key, value):
        events.append((key, value))

    async def cooldown(family, seconds):
        cooldowns.append(seconds)

    async def sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(client, "_paced_get", boundary)
    monkeypatch.setattr(client, "event_recorder", event)
    monkeypatch.setattr(client, "cooldown_publisher", cooldown)
    monkeypatch.setattr("autotrader.market_data.revolut.asyncio.sleep", sleep)
    monkeypatch.setattr("autotrader.market_data.revolut.random.uniform", lambda a, b: 0)
    try:
        with pytest.raises(RateLimitDeferred, match="bounded"):
            await client._request("/1.0/public/candles")
        assert client._breaker.failures == 4 and not responses
        assert cooldowns == [1.5, 1.5, 1.5, 2.0] and waits == [1.5, 1.5, 1.5]
        assert sum(key == "request_429" for key, _ in events) == 4
        client._breaker.failure()
        with pytest.raises(MarketDataError, match="breaker"):
            await client._request("/1.0/public/candles")
    finally:
        await client.close()


async def test_priority_gate_dispatches_protection_before_queued_discovery():
    gate = PriorityGate()
    entered = asyncio.Event()
    release = asyncio.Event()
    order = []

    async def first():
        async with gate.slot():
            entered.set()
            await release.wait()

    async def next_one(name):
        async with gate.slot():
            order.append(name)

    task = asyncio.create_task(first())
    await entered.wait()
    ordinary = asyncio.create_task(next_one("discovery"))
    await asyncio.sleep(0)
    async with protective_priority():
        protective = asyncio.create_task(next_one("protection"))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(task, ordinary, protective)
    assert order == ["protection", "discovery"]


async def test_discovery_breaker_cannot_block_an_independent_protective_book_family(monkeypatch):
    client = RevolutXPublicClient()

    async def response(path, params):
        return httpx.Response(
            200, json={"data": {}}, request=httpx.Request("GET", "https://example.test" + path)
        )

    monkeypatch.setattr(client, "_paced_get", response)
    for _ in range(5):
        client._breaker.failure()
    try:
        with pytest.raises(MarketDataError, match="breaker"):
            await client._request("/1.0/public/candles")
        assert await client._request("/2.0/public/order-book/BTC-EUR") == {"data": {}}
        assert not client._breaker.allow()
    finally:
        await client.close()
