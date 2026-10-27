from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any

from autotrader.domain import Candle, DataQuality, OrderBook, TradingPair, utc_now
from autotrader.market_data.revolut import MarketDataError, RevolutXPublicClient
from autotrader.market_data.scheduling import protective_priority


@dataclass(frozen=True)
class OrderBookMetrics:
    best_bid: Decimal
    best_ask: Decimal
    mid: Decimal
    spread: Decimal
    spread_bps: Decimal
    bid_depth: Decimal
    ask_depth: Decimal
    imbalance: Decimal
    liquidity_quote: Decimal
    age_seconds: Decimal
    provider_latency_ms: Decimal


@dataclass(frozen=True)
class ValidatedMarket:
    pair: TradingPair
    candles: list[Candle]
    order_book: OrderBook
    metrics: OrderBookMetrics
    quality: DataQuality
    rejected_reasons: list[str]

    @property
    def usable_for_entry(self) -> bool:
        return self.quality is DataQuality.GOOD and not self.rejected_reasons


class MarketDataService:
    def __init__(
        self,
        client: RevolutXPublicClient,
        *,
        max_staleness_seconds: int = 90,
        candle_interval_minutes: int = 5,
        candle_lookback: int = 240,
        state_store: Any = None,
        cache_enabled: bool | None = None,
    ) -> None:
        self.client = client
        self.max_staleness_seconds = max_staleness_seconds
        self.candle_interval_minutes = candle_interval_minutes
        self.candle_lookback = candle_lookback
        self.state_store=state_store
        self.cache_enabled=isinstance(client,RevolutXPublicClient) if cache_enabled is None else cache_enabled
        self._candles:dict[str,tuple[int,list[Candle]]]={}
        self._candle_locks:dict[str,asyncio.Lock]={}
        self._protective_books:dict[str,OrderBook]|None=None
        self._discovery_rotation = 0
        self._discovery_state: dict[str, Any] = {}

    @asynccontextmanager
    async def protective_cycle(self) -> AsyncIterator[None]:
        self._protective_books={}
        try:
            async with protective_priority():
                yield
        finally:
            self._protective_books=None

    async def _metric(self,event:str,value:float=1) -> None:
        if self.state_store:
            await self.state_store.market_metric(event,value)

    @staticmethod
    def _decode_candles(raw:list[dict[str,Any]])->list[Candle]:
        return [Candle(r['symbol'],datetime.fromisoformat(r['timestamp']),
            open=Decimal(r['open']),high=Decimal(r['high']),low=Decimal(r['low']),close=Decimal(r['close']),volume=Decimal(r['volume']),timeframe=r['timeframe'],source=r['source']) for r in raw]

    async def completed_candles(self,pair:TradingPair)->list[Candle]:
        until=utc_now()
        seconds=self.candle_interval_minutes*60
        bucket=int(until.timestamp())//seconds
        key=f'{pair.symbol}:{self.candle_interval_minutes}:{self.candle_lookback}'
        async with self._candle_locks.setdefault(key,asyncio.Lock()):
            old=self._candles.get(key)
            token=None
            if self.cache_enabled and old and old[0]>=bucket:
                await self._metric('candle_cache_hit')
                return list(old[1])
            if self.cache_enabled and self.state_store:
                token,stored=await self.state_store.reserve_market_cache(key,bucket)
                if stored.get('candles'):
                    old=(stored.get('bucket',-1),self._decode_candles(stored['candles']))
                if token is None:
                    if old and old[0]>=bucket:
                        self._candles[key]=old
                        await self._metric('candle_cache_hit')
                        return list(old[1])
                    raise MarketDataError('shared_candle_refresh_in_progress')
            since=until-timedelta(seconds=seconds*self.candle_lookback)
            if self.cache_enabled and old and old[1]:
                since=max(since,old[1][-1].timestamp-timedelta(seconds=seconds))
            fresh=await self.client.get_candles(pair.symbol,self.candle_interval_minutes,int(since.timestamp()*1000),int(until.timestamp()*1000))
            merged={c.timestamp:c for c in (old[1] if self.cache_enabled and old else [])}
            merged.update({c.timestamp:c for c in fresh if c.timestamp+timedelta(seconds=seconds)<=until})
            candles=sorted(merged.values(),key=lambda c:c.timestamp)[-self.candle_lookback:]
            if self.validate_candles(candles,self.candle_interval_minutes) or len(candles)<50:
                # Never promote a bad refresh to the completed cache.
                return candles
            if self.cache_enabled:
                self._candles[key]=(bucket,candles)
                if self.state_store and token:
                    raw=[{'symbol':c.symbol,'timestamp':c.timestamp.isoformat(),**{k:str(getattr(c,k)) for k in ('open','high','low','close','volume')},'timeframe':c.timeframe,'source':c.source} for c in candles]
                    await self.state_store.publish_market_cache(key,token,bucket,raw)
            await self._metric('candle_refresh')
            await self._metric('candles_downloaded',len(fresh))
            return list(candles)

    async def close(self) -> None:
        await self.client.close()

    async def discover_pairs(self, quote_assets: tuple[str, ...] = ("EUR",), limit: int = 20) -> list[TradingPair]:
        pairs = await self.client.get_pairs()
        if quote_assets == ('EUR',) and isinstance(self.client, RevolutXPublicClient):
            from autotrader.raoe.discovery import discover
            return await discover(self,pairs,limit)
        eligible = [pair for pair in pairs if pair.quote_asset in quote_assets]
        eligible.sort(key=lambda pair: (quote_assets.index(pair.quote_asset), _asset_priority(pair.base_asset), pair.symbol))
        selected = eligible[:limit]
        if selected:
            offset = self._discovery_rotation % len(selected)
            self._discovery_rotation += 1
            selected = selected[offset:] + selected[:offset]
        return selected

    async def resolve_pair(self, symbol: str) -> TradingPair | None:
        pairs = await self.client.get_pairs()
        return next((pair for pair in pairs if pair.symbol == symbol), None)

    async def get_position_book(self, pair: TradingPair) -> OrderBook:
        if self._protective_books is not None and pair.symbol in self._protective_books:
            book=self._protective_books[pair.symbol]
        else:
            async with protective_priority():
                book = await self.client.get_order_book(pair.symbol, limit=50)
            if self._protective_books is not None:
                self._protective_books[pair.symbol]=book
        reasons, _ = self.validate_order_book(book)
        if reasons:
            raise MarketDataError(",".join(reasons))
        return book

    async def get_execution_book(self, pair: TradingPair) -> OrderBook:
        from autotrader.market_data.scheduling import request_priority
        token=request_priority.set(5)
        try:
            book=await self.client.get_order_book(pair.symbol,limit=50)
            reasons,_=self.validate_order_book(book)
            if reasons: raise MarketDataError(','.join(reasons))
            return book
        finally:
            request_priority.reset(token)

    async def get_validated_market(self, pair: TradingPair) -> ValidatedMarket:
        started = time.perf_counter()
        candles = await self.completed_candles(pair)
        order_book = await self.client.get_order_book(pair.symbol, limit=50)
        provider_latency_ms = Decimal(str(round((time.perf_counter() - started) * 1000, 3)))
        book_reasons, metrics = self.validate_order_book(order_book, provider_latency_ms)
        candle_reasons = self.validate_candles(candles, self.candle_interval_minutes)
        pair_reasons = self.validate_pair(pair)
        reasons = [*pair_reasons, *book_reasons, *candle_reasons]
        quality = DataQuality.GOOD if not reasons else DataQuality.INVALID
        if len(candles) < 50 and "insufficient_candle_history" not in reasons:
            reasons.append("insufficient_candle_history")
            quality = DataQuality.INSUFFICIENT_HISTORY
        return ValidatedMarket(pair, candles, order_book, metrics, quality, reasons)

    def validate_order_book(self, order_book: OrderBook, provider_latency_ms: Decimal = Decimal("0")) -> tuple[list[str], OrderBookMetrics]:
        reasons: list[str] = []
        if any(not level.price.is_finite() or not level.quantity.is_finite() for level in (*order_book.bids, *order_book.asks)):
            return ["non_finite_order_book_level"], OrderBookMetrics(**{name: Decimal(0) for name in OrderBookMetrics.__dataclass_fields__})
        now = utc_now()
        age = Decimal(str(max((now - order_book.timestamp).total_seconds(), 0)))
        best_bid = order_book.best_bid or Decimal("0")
        best_ask = order_book.best_ask or Decimal("0")
        mid = order_book.mid or Decimal("0")
        spread = order_book.spread or Decimal("0")

        if not order_book.bids:
            reasons.append("missing_bids")
        if not order_book.asks:
            reasons.append("missing_asks")
        if any(level.price <= 0 or level.quantity <= 0 for level in (*order_book.bids, *order_book.asks)):
            reasons.append("non_positive_order_book_level")
        if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
            reasons.append("inconsistent_bid_ask")
        if age > Decimal(self.max_staleness_seconds):
            reasons.append("stale_order_book")
        if (order_book.timestamp-now).total_seconds()>5:
            reasons.append('future_order_book')
        if order_book.bids and any(left.price < right.price for left, right in pairwise(order_book.bids)):
            reasons.append("bid_levels_not_descending")
        if order_book.asks and any(left.price > right.price for left, right in pairwise(order_book.asks)):
            reasons.append("ask_levels_not_ascending")

        bid_depth = sum((level.quantity for level in order_book.bids), Decimal("0"))
        ask_depth = sum((level.quantity for level in order_book.asks), Decimal("0"))
        if bid_depth <= 0 or ask_depth <= 0:
            reasons.append("non_positive_liquidity")
        total_depth = bid_depth + ask_depth
        liquidity_quote = sum((level.price * level.quantity for level in (*order_book.bids, *order_book.asks)), Decimal("0"))
        imbalance = (bid_depth - ask_depth) / total_depth if total_depth > 0 else Decimal("0")
        spread_bps = (spread / mid * Decimal("10000")) if mid > 0 else Decimal("0")
        return reasons, OrderBookMetrics(
            best_bid=best_bid,
            best_ask=best_ask,
            mid=mid,
            spread=spread,
            spread_bps=spread_bps,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            imbalance=imbalance,
            liquidity_quote=liquidity_quote,
            age_seconds=age,
            provider_latency_ms=provider_latency_ms,
        )

    def validate_pair(self, pair: TradingPair) -> list[str]:
        reasons: list[str] = []
        if pair.status.lower() != "active":
            reasons.append("inactive_pair")
        if pair.price_step <= 0:
            reasons.append("invalid_price_step")
        if pair.quantity_step <= 0:
            reasons.append("invalid_quantity_step")
        if pair.min_order_quote < 0:
            reasons.append("invalid_min_order_quote")
        if pair.min_order_base < 0:
            reasons.append("invalid_min_order_base")
        return reasons

    def validate_candles(self, candles: list[Candle], interval_minutes: int) -> list[str]:
        reasons: list[str] = []
        if not candles:
            return ["missing_candles"]
        ordered = sorted(candles, key=lambda candle: candle.timestamp)
        if ordered != candles:
            reasons.append("out_of_order_candles")
        seen = {candle.timestamp for candle in candles}
        if len(seen) != len(candles):
            reasons.append("duplicate_candles")
        if any(min(candle.open, candle.high, candle.low, candle.close) <= 0 for candle in candles):
            reasons.append("non_positive_candle_price")
        if any(candle.volume < 0 for candle in candles):
            reasons.append("negative_candle_volume")
        if any(
            not (candle.low <= candle.open <= candle.high and candle.low <= candle.close <= candle.high and candle.low <= candle.high)
            for candle in candles
        ):
            reasons.append("invalid_ohlc_relationship")
        expected = timedelta(minutes=interval_minutes)
        gaps = [
            current.timestamp - previous.timestamp
            for previous, current in pairwise(ordered)
            if current.timestamp - previous.timestamp != expected
        ]
        if gaps:
            reasons.append("incorrect_candle_interval")
        latest_age = utc_now() - ordered[-1].timestamp
        if latest_age > timedelta(minutes=max(interval_minutes * 3, 15)):
            reasons.append("stale_candles")
        if ordered[-1].timestamp + expected > utc_now():
            reasons.append("forming_candle")
        return reasons


def _asset_priority(asset: str) -> int:
    leaders = {"BTC": 0, "ETH": 1, "SOL": 2, "XRP": 3, "ADA": 4, "AVAX": 5, "LINK": 6, "DOT": 7}
    return leaders.get(asset, 100)
