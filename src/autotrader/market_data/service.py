from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from itertools import pairwise

from autotrader.domain import Candle, DataQuality, OrderBook, TradingPair, utc_now
from autotrader.market_data.revolut import MarketDataError, RevolutXPublicClient


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
    ) -> None:
        self.client = client
        self.max_staleness_seconds = max_staleness_seconds
        self.candle_interval_minutes = candle_interval_minutes
        self.candle_lookback = candle_lookback

    async def close(self) -> None:
        await self.client.close()

    async def discover_pairs(self, quote_assets: tuple[str, ...] = ("EUR",), limit: int = 20) -> list[TradingPair]:
        pairs = await self.client.get_pairs()
        eligible = [pair for pair in pairs if pair.quote_asset in quote_assets]
        eligible.sort(key=lambda pair: (quote_assets.index(pair.quote_asset), _asset_priority(pair.base_asset), pair.symbol))
        return eligible[:limit]

    async def resolve_pair(self, symbol: str) -> TradingPair | None:
        pairs = await self.client.get_pairs()
        return next((pair for pair in pairs if pair.symbol == symbol), None)

    async def get_position_book(self, pair: TradingPair) -> OrderBook:
        book = await self.client.get_order_book(pair.symbol, limit=50)
        reasons, _ = self.validate_order_book(book)
        if reasons:
            raise MarketDataError(",".join(reasons))
        return book

    async def get_validated_market(self, pair: TradingPair) -> ValidatedMarket:
        until = utc_now()
        since = until - timedelta(minutes=self.candle_interval_minutes * self.candle_lookback)
        started = time.perf_counter()
        order_book = await self.client.get_order_book(pair.symbol, limit=50)
        provider_latency_ms = Decimal(str(round((time.perf_counter() - started) * 1000, 3)))
        candles = await self.client.get_candles(
            pair.symbol,
            self.candle_interval_minutes,
            int(since.timestamp() * 1000),
            int(until.timestamp() * 1000),
        )
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
