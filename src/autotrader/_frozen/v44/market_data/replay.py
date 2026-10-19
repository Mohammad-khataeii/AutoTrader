"""Explicit external market-data boundary for deterministic process acceptance tests."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from autotrader.domain import Candle, OrderBook, OrderBookLevel, TradingPair


class FileReplayClient:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.frame: dict[str, Any] = {}
        self.refresh()

    def refresh(self) -> str:
        self.frame = json.loads(self.path.read_text(encoding="utf-8"))
        return str(self.frame["frame_id"])

    async def get_pairs(self) -> list[TradingPair]:
        return [TradingPair(**{**p, **{key: Decimal(value) for key, value in p.items() if key in {"price_step", "quantity_step", "min_order_quote", "min_order_base"}}}) for p in self.frame["pairs"]]

    async def get_order_book(self, symbol: str, limit: int = 50) -> OrderBook:
        b = self.frame["markets"][symbol]["book"]
        return OrderBook(symbol, datetime.fromisoformat(b["timestamp"]),
            tuple(OrderBookLevel(Decimal(p), Decimal(q)) for p, q in b["bids"]),
            tuple(OrderBookLevel(Decimal(p), Decimal(q)) for p, q in b["asks"]), "acceptance-replay")

    async def get_candles(self, symbol: str, interval_minutes: int, since_ms: int, until_ms: int) -> list[Candle]:
        return [Candle(symbol=symbol, timestamp=datetime.fromisoformat(c["timestamp"]),
            open=Decimal(c["open"]), high=Decimal(c["high"]), low=Decimal(c["low"]),
            close=Decimal(c["close"]), volume=Decimal(c["volume"]), timeframe="5m", source="acceptance-replay")
            for c in self.frame["markets"][symbol]["candles"]]

    async def close(self) -> None:
        pass
