from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import httpx

from autotrader.domain import Candle, OrderBook, OrderBookLevel, TradingPair, utc_now
from autotrader.market_data.scheduling import PriorityGate


class MarketDataError(RuntimeError):
    pass


class RateLimitDeferred(MarketDataError):
    pass


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_seconds: int = 30) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.failures = 0
        self.opened_at: datetime | None = None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        return (datetime.now(tz=UTC) - self.opened_at).total_seconds() >= self.recovery_seconds

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = datetime.now(tz=UTC)


class TokenBucket:
    def __init__(self, rate_per_second: Decimal, burst: Decimal) -> None:
        self.rate_per_second = rate_per_second
        self.capacity = burst
        self.tokens = burst
        self.updated_at = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if self.updated_at == 0.0:
                self.updated_at = now
            elapsed = Decimal(str(now - self.updated_at))
            self.tokens = min(self.capacity, self.tokens + (elapsed * self.rate_per_second))
            self.updated_at = now
            if self.tokens >= 1:
                self.tokens -= 1
                return
            missing = Decimal("1") - self.tokens
            await asyncio.sleep(float(missing / self.rate_per_second))
            self.tokens = Decimal("0")
            self.updated_at = loop.time()


class RevolutXPublicClient:
    """Read-only Revolut X adapter for documented public endpoints."""

    def __init__(
        self,
        base_url: str = "https://revx.revolut.com/api",
        region: str = "EEA",
        timeout: float = 8.0,
        rate_reserver:Callable[[str],Awaitable[float]]|None=None,
        cooldown_publisher:Callable[[str,float],Awaitable[None]]|None=None,
        event_recorder:Callable[[str,float],Awaitable[None]]|None=None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.region = region
        self.rate_reserver=rate_reserver
        self.cooldown_publisher=cooldown_publisher
        self.event_recorder=event_recorder
        self._gate=PriorityGate()
        self._cooldowns:dict[str,float]={}
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)
        self._limiters: dict[str, TokenBucket] = {
            "/1.0/public/configuration/pairs": TokenBucket(Decimal("1"), Decimal("1")),
            "/1.0/public/tickers": TokenBucket(Decimal("1"), Decimal("1")),
            "/1.0/public/candles": TokenBucket(Decimal("1"), Decimal("1")),
            "/2.0/public/order-book": TokenBucket(Decimal("1"), Decimal("1")),
        }
        self._breakers = {family:CircuitBreaker() for family in self._limiters}
        # Retain the private candles handle for existing diagnostics/tests.
        self._breaker = self._breakers['/1.0/public/candles']
        self._pairs_cache: tuple[datetime, list[TradingPair]] | None = None
        self._ticker_cache: tuple[datetime, list[dict[str, Any]]] | None = None
        self._ticker_lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    def _family(self,path:str)->str:
        return next((prefix for prefix in self._limiters if path.startswith(prefix)),path)

    async def _event(self,event:str,value:float=1)->None:
        if self.event_recorder:
            await self.event_recorder(event,value)

    async def _paced_get(self,path:str,params:dict[str,Any])->httpx.Response:
        family=self._family(path)
        while True:
            local_delay=self._cooldowns.get(family,0)-time.monotonic()
            if local_delay>30:
                raise RateLimitDeferred("Shared provider cooldown is not ready; defer this cycle.")
            if local_delay>0:
                await asyncio.sleep(min(local_delay,1))
                continue
            async with self._gate.slot():
                await self._limiter_for(path).acquire()
                delay=await self.rate_reserver(family) if self.rate_reserver else 0
                if delay<=0:
                    return await self._client.get(path,params=params)
            # Release the gate during shared cooldown so protection on another
            # endpoint family can run. Recheck ownership before every request.
            if delay>30:
                raise RateLimitDeferred("Shared provider cooldown is not ready; defer this cycle.")
            await asyncio.sleep(min(delay,1))

    async def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not path.startswith(('/1.0/public/','/2.0/public/')):
            raise MarketDataError('Only public read-only exchange paths are allowed.')
        params = {"region": self.region, **(params or {})}
        breaker=self._breakers.setdefault(self._family(path),CircuitBreaker())
        for attempt in range(4):
            if not breaker.allow():
                raise MarketDataError("Revolut X circuit breaker is open.")
            try:
                started=time.perf_counter()
                try:
                    response=await self._paced_get(path,params)
                finally:
                    await self._event('request_latency_ms',(time.perf_counter()-started)*1000)
                if response.status_code == 429:
                    breaker.failure()
                    await self._event('request_429')
                    await self._event('request_429:' + self._family(path).rsplit('/',1)[-1] + ':' + path.rsplit('/',1)[-1])
                    retry_after=float(_retry_after_seconds(response.headers.get("Retry-After")))
                    delay=max(retry_after,0.25*(2**attempt)+random.uniform(0,.1))
                    family=self._family(path)
                    self._cooldowns[family]=max(self._cooldowns.get(family,0),time.monotonic()+delay)
                    if self.cooldown_publisher:
                        await self.cooldown_publisher(family,delay)
                    if delay>30 or attempt==3:
                        raise RateLimitDeferred("Provider cooldown recorded; bounded 429 retries exhausted or deferred.")
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                payload=cast(dict[str,Any],response.json())
                if not isinstance(payload,dict):
                    raise MarketDataError("Expected JSON object from provider.")
                breaker.success()
                await self._event('request_success')
                return payload
            except RateLimitDeferred:
                raise
            except (httpx.HTTPError,ValueError,MarketDataError) as exc:
                breaker.failure()
                await self._event('request_failure')
                if attempt==3:
                    raise MarketDataError(str(exc)) from exc
                await asyncio.sleep(.25*(2**attempt)+random.uniform(0,.1))
        raise RateLimitDeferred("Bounded public request retries exhausted.")

    def _limiter_for(self, path: str) -> TokenBucket:
        for prefix, limiter in self._limiters.items():
            if path.startswith(prefix):
                return limiter
        return TokenBucket(Decimal("1"), Decimal("1"))

    async def get_pairs(self) -> list[TradingPair]:
        if self._pairs_cache and (datetime.now(tz=UTC) - self._pairs_cache[0]).total_seconds() < 300:
            return self._pairs_cache[1]
        payload = await self._request("/1.0/public/configuration/pairs")
        raw_pairs = payload.get("data", payload)
        pairs: list[TradingPair] = []
        for symbol, raw in raw_pairs.items():
            if not isinstance(raw, dict):
                raise MarketDataError(f"Invalid pair configuration for {symbol}.")
            if str(raw.get("status", "active")).lower() != "active":
                continue
            base = str(raw.get("base") or _split_symbol(symbol)[0])
            quote = str(raw.get("quote") or _split_symbol(symbol)[1])
            base_step = _required_decimal(raw, "base_step", context=f"{symbol} pair configuration")
            quote_step = _required_decimal(raw, "quote_step", context=f"{symbol} pair configuration")
            min_order_base = _required_decimal(raw, "min_order_size", context=f"{symbol} pair configuration")
            min_order_quote = _required_decimal(raw, "min_order_size_quote", context=f"{symbol} pair configuration")
            max_order_base = _optional_decimal(raw, "max_order_size", context=f"{symbol} pair configuration")
            if base_step <= 0 or quote_step <= 0 or min_order_base < 0 or min_order_quote < 0:
                raise MarketDataError(f"Invalid precision/minimum values for {symbol}.")
            pairs.append(
                TradingPair(
                    symbol=symbol.replace("/", "-"),
                    base_asset=base,
                    quote_asset=quote,
                    price_step=quote_step,
                    quantity_step=base_step,
                    min_order_quote=min_order_quote,
                    min_order_base=min_order_base,
                    max_order_base=max_order_base,
                    status=str(raw.get("status", "active")),
                )
            )
        self._pairs_cache = (datetime.now(tz=UTC), pairs)
        return pairs

    async def get_tickers(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        async with self._ticker_lock:
            if symbols is None and self._ticker_cache and (utc_now() - self._ticker_cache[0]).total_seconds() < 60:
                return [dict(row) for row in self._ticker_cache[1]]
            params: dict[str, Any] = {"symbols": ",".join(symbols)} if symbols else {}
            payload = await self._request("/1.0/public/tickers", params)
            stamp = _timestamp_ms(payload.get('metadata', {}).get('timestamp'), context='ticker metadata.timestamp')
            if not -5 <= (utc_now() - stamp).total_seconds() <= 90 or not isinstance(payload.get('data'), list):
                raise MarketDataError('stale_or_invalid_ticker_summary')
            rows = list(payload['data'])
            if not all(isinstance(row, dict) for row in rows):
                raise MarketDataError('invalid_ticker_summary_row')
            if symbols is None:
                self._ticker_cache = (stamp, rows)
            return [dict(row) for row in rows]

    async def get_order_book(self, symbol: str, limit: int = 50) -> OrderBook:
        payload = await self._request(f"/2.0/public/order-book/{symbol}", {"limit": limit})
        data = _required_mapping(payload, "data", context="order book response")
        metadata = payload.get("metadata", {})
        _validate_region(metadata, self.region)
        timestamp = _timestamp_ms(metadata.get("timestamp"), context="order book metadata.timestamp")
        bids = _levels(data.get("bids"), side="bid")
        asks = _levels(data.get("asks"), side="ask")
        if not bids or not asks:
            raise MarketDataError("Order book has no usable liquidity.")
        if bids[0].price >= asks[0].price:
            raise MarketDataError("Order book is crossed or locked.")
        return OrderBook(symbol=symbol, timestamp=timestamp, bids=bids, asks=asks, source="revolut-x")

    async def get_candles(self, symbol: str, interval_minutes: int, since_ms: int, until_ms: int) -> list[Candle]:
        payload = await self._request(
            f"/1.0/public/candles/{symbol}",
            {"interval": interval_minutes, "since": since_ms, "until": until_ms},
        )
        _validate_region(payload.get("metadata", {}), self.region)
        raw_candles = payload.get("data")
        if not isinstance(raw_candles, list):
            raise MarketDataError("Invalid candles response: missing data array.")
        candles: list[Candle] = []
        for raw in raw_candles:
            if not isinstance(raw, dict):
                raise MarketDataError("Invalid candle record.")
            start = _timestamp_ms(raw.get("start"), context="candle.start")
            open_price = _required_decimal(raw, "open", context="candle")
            high = _required_decimal(raw, "high", context="candle")
            low = _required_decimal(raw, "low", context="candle")
            close = _required_decimal(raw, "close", context="candle")
            volume = _required_decimal(raw, "volume", context="candle")
            _validate_ohlcv(open_price, high, low, close, volume)
            candles.append(
                Candle(
                    symbol=symbol,
                    timestamp=start,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    timeframe=f"{interval_minutes}m",
                    source="revolut-x",
                )
            )
        _validate_candle_sequence(candles, interval_minutes, allow_forming=True)
        # The provider includes the candle at the inclusive until boundary. It is
        # deliberately excluded from closed-candle strategies, never fabricated.
        end = min(utc_now(), datetime.fromtimestamp(until_ms/1000,tz=UTC))
        return [c for c in candles if c.timestamp+timedelta(minutes=interval_minutes)<=end]


def _split_symbol(symbol: str) -> tuple[str, str]:
    normalized = symbol.replace("-", "/")
    if "/" not in normalized:
        return normalized, ""
    base, quote = normalized.split("/", 1)
    return base, quote


def _timestamp_ms(value: Any, *, context: str) -> datetime:
    if value is None:
        raise MarketDataError(f"Missing required timestamp: {context}.")
    try:
        return datetime.fromtimestamp(float(Decimal(str(value)) / Decimal("1000")), tz=UTC)
    except Exception as exc:
        raise MarketDataError(f"Invalid timestamp in {context}: {value!r}") from exc


def _required_mapping(payload: dict[str, Any], field: str, *, context: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise MarketDataError(f"Invalid {context}: missing object {field}.")
    return value


def _required_decimal(raw: dict[str, Any], field: str, *, context: str) -> Decimal:
    if field not in raw:
        raise MarketDataError(f"Missing {field} in {context}.")
    try:
        result = Decimal(str(raw[field]))
        if not result.is_finite():
            raise ValueError("Non-finite decimal")
        return result
    except Exception as exc:
        raise MarketDataError(f"Invalid decimal {field} in {context}: {raw[field]!r}") from exc


def _optional_decimal(raw: dict[str, Any], field: str, *, context: str) -> Decimal | None:
    if raw.get(field) is None:
        return None
    return _required_decimal(raw, field, context=context)


def _levels(raw_levels: Any, *, side: str) -> tuple[OrderBookLevel, ...]:
    if not isinstance(raw_levels, list):
        raise MarketDataError(f"Missing {side} levels.")
    levels: list[OrderBookLevel] = []
    previous_price: Decimal | None = None
    for raw in raw_levels:
        if not isinstance(raw, dict):
            raise MarketDataError(f"Invalid {side} level.")
        price = _required_decimal(raw, "price", context=f"{side} level")
        quantity = _required_decimal(raw, "quantity", context=f"{side} level")
        if price <= 0 or quantity <= 0:
            raise MarketDataError(f"Non-positive {side} level.")
        if previous_price is not None:
            if side == "bid" and price > previous_price:
                raise MarketDataError("Bid levels are not sorted descending.")
            if side == "ask" and price < previous_price:
                raise MarketDataError("Ask levels are not sorted ascending.")
        previous_price = price
        levels.append(OrderBookLevel(price, quantity))
    return tuple(levels)


def _validate_ohlcv(open_price: Decimal, high: Decimal, low: Decimal, close: Decimal, volume: Decimal) -> None:
    if min(open_price, high, low, close) <= 0:
        raise MarketDataError("Candle contains non-positive price.")
    if volume < 0:
        raise MarketDataError("Candle contains negative volume.")
    if not (low <= open_price <= high and low <= close <= high and low <= high):
        raise MarketDataError("Candle OHLC values are inconsistent.")


def _validate_region(metadata: Any, expected_region: str) -> None:
    if metadata is not None and not isinstance(metadata, dict):
        raise MarketDataError("Invalid metadata object.")
    if not isinstance(metadata, dict):
        return
    region = metadata.get("region")
    if region is not None and str(region).upper() != expected_region.upper():
        raise MarketDataError(f"Region mismatch: expected {expected_region}, got {region}.")


def _validate_candle_sequence(candles: list[Candle], interval_minutes: int, *, allow_forming: bool = False) -> None:
    if not candles:
        return
    expected_interval = timedelta(minutes=interval_minutes)
    seen: set[datetime] = set()
    previous: Candle | None = None
    now = utc_now()
    for candle in candles:
        if candle.timestamp in seen:
            raise MarketDataError(f"Duplicate candle timestamp: {candle.timestamp.isoformat()}.")
        seen.add(candle.timestamp)
        if previous is not None:
            delta = candle.timestamp - previous.timestamp
            if delta < expected_interval:
                raise MarketDataError("Out-of-order or duplicate candle interval.")
            if delta > expected_interval:
                raise MarketDataError("Missing candle interval.")
        if candle.timestamp > now + timedelta(seconds=5):
            raise MarketDataError("Future candle timestamp.")
        if not allow_forming and candle.timestamp + expected_interval > now:
            raise MarketDataError("Latest candle is still forming.")
        previous = candle


def _retry_after_seconds(value: str | None) -> Decimal:
    if value is None:
        return Decimal("1")
    try:
        delay=Decimal(value)/Decimal(1000)
        if not delay.is_finite() or delay < 0:
            raise ValueError("Invalid Retry-After")
        return delay
    except Exception as exc:
        raise MarketDataError("Invalid provider Retry-After header.") from exc
