from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from autotrader.domain import Candle, utc_now

TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
ASSETS = ("BTC", "ETH", "SOL", "XRP", "ADA", "LINK", "AVAX", "DOT")
SOURCE = "coinbase-exchange-public"
SCHEMA = "eur-ohlcv-4.0.0"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


@dataclass(frozen=True)
class HistoricalBar:
    source: str
    symbol: str
    base: str
    quote: str
    start: str
    timeframe: str
    open: str
    high: str
    low: str
    close: str
    volume: str
    ingested_at: str
    quality_flags: tuple[str, ...]
    dataset_version: str = SCHEMA

    def candle(self) -> Candle:
        return Candle(self.symbol, datetime.fromisoformat(self.start),
            Decimal(self.open), Decimal(self.high), Decimal(self.low), Decimal(self.close), Decimal(self.volume),
            timeframe=self.timeframe, source=self.source)


def validate_bar(bar: HistoricalBar) -> None:
    if bar.base not in ASSETS or bar.quote != "EUR" or bar.symbol != f"{bar.base}-EUR":
        raise ValueError("historical_currency_or_symbol_mismatch")
    seconds = TIMEFRAMES[bar.timeframe]
    start = datetime.fromisoformat(bar.start)
    if start.tzinfo is None or int(start.timestamp()) % seconds or start.microsecond:
        raise ValueError("unaligned_or_naive_historical_timestamp")
    if start.timestamp() + seconds > utc_now().timestamp():
        raise ValueError("incomplete_or_future_historical_bar")
    o, h, low, c, v = [Decimal(getattr(bar, key)) for key in ("open", "high", "low", "close", "volume")]
    if not all(x.is_finite() for x in (o, h, low, c, v)) or min(o, h, low, c) <= 0 or v < 0:
        raise ValueError("invalid_historical_values")
    if not low <= o <= h or not low <= c <= h:
        raise ValueError("inconsistent_historical_ohlc")


def aggregate_complete(bars: list[HistoricalBar], target: str) -> list[HistoricalBar]:
    if not bars:
        return []
    source_seconds = TIMEFRAMES[bars[0].timeframe]
    seconds = TIMEFRAMES[target]
    if seconds <= source_seconds or seconds % source_seconds:
        raise ValueError("invalid_aggregation_ratio")
    groups: dict[tuple[str, int], list[HistoricalBar]] = {}
    for bar in bars:
        validate_bar(bar)
        if TIMEFRAMES[bar.timeframe] != source_seconds:
            raise ValueError("mixed_source_timeframes")
        bucket = int(datetime.fromisoformat(bar.start).timestamp()) // seconds * seconds
        groups.setdefault((bar.symbol, bucket), []).append(bar)
    result = []
    for (_, bucket), members in sorted(groups.items()):
        ordered = sorted(members, key=lambda b: b.start)
        expected = list(range(bucket, bucket + seconds, source_seconds))
        actual = [int(datetime.fromisoformat(b.start).timestamp()) for b in ordered]
        if actual != expected or bucket + seconds > utc_now().timestamp():
            continue
        first, last = ordered[0], ordered[-1]
        result.append(HistoricalBar(first.source + ":aggregated", first.symbol, first.base, first.quote,
            datetime.fromtimestamp(bucket, UTC).isoformat(), target, first.open,
            str(max(Decimal(b.high) for b in ordered)), str(min(Decimal(b.low) for b in ordered)),
            last.close, str(sum((Decimal(b.volume) for b in ordered), Decimal(0))),
            max(b.ingested_at for b in ordered), tuple(sorted({flag for b in ordered for flag in b.quality_flags}))))
    return result


def save_dataset(root: Path, bars: list[HistoricalBar], *, requested_start: datetime,
                 requested_end: datetime, symbol: str, timeframe: str,
                 provenance: dict[str, Any]) -> dict[str, Any]:
    ordered = sorted(bars, key=lambda b: b.start)
    seen: dict[str, HistoricalBar] = {}
    duplicates = 0
    for bar in ordered:
        validate_bar(bar)
        if bar.symbol != symbol or bar.timeframe != timeframe:
            raise ValueError("mixed_dataset_identity")
        if not requested_start <= datetime.fromisoformat(bar.start) < requested_end:
            raise ValueError("bar_outside_requested_range")
        if bar.start in seen:
            if seen[bar.start].candle() != bar.candle():
                raise ValueError("conflicting_duplicate_historical_bar")
            duplicates += 1
        seen[bar.start] = bar
    ordered = list(seen.values())
    # Stable content identity excludes ingestion wall time, retains all market values.
    identity = digest(canonical([{k: v for k, v in asdict(b).items() if k != "ingested_at"} for b in ordered]))
    ordered = [HistoricalBar(**{**asdict(b), "dataset_version": identity}) for b in ordered]
    seconds = TIMEFRAMES[timeframe]
    actual = {int(datetime.fromisoformat(b.start).timestamp()) for b in ordered}
    gaps: list[dict[str, Any]] = []
    for timestamp in range(int(requested_start.timestamp()), int(requested_end.timestamp()), seconds):
        if timestamp in actual:
            continue
        if gaps and gaps[-1]["end_exclusive"] == timestamp:
            gaps[-1]["end_exclusive"] += seconds
            gaps[-1]["count"] += 1
        else:
            gaps.append({"start": timestamp, "end_exclusive": timestamp + seconds, "count": 1})
    payload = b"\n".join(canonical(asdict(b)) for b in ordered) + (b"\n" if ordered else b"")
    relative = Path("datasets") / f"{symbol}-{timeframe}-{identity[:16]}.jsonl.gz"
    compressed = gzip.compress(payload, mtime=0)
    atomic_write(root / relative, compressed)
    manifest = {"schema": SCHEMA, "dataset_version": identity, "source": sorted({b.source for b in ordered}),
        "symbol": symbol, "base": symbol.split("-")[0], "quote": "EUR", "timeframe": timeframe,
        "requested_start": requested_start.isoformat(), "requested_end_exclusive": requested_end.isoformat(),
        "actual_start": ordered[0].start if ordered else None, "actual_last_start": ordered[-1].start if ordered else None,
        "observations": len(ordered), "duplicates_removed": duplicates,
        "missing_observations": sum(g["count"] for g in gaps), "gaps": gaps,
        "quality_counts": {flag: sum(flag in b.quality_flags for b in ordered) for flag in sorted({f for b in ordered for f in b.quality_flags})},
        "file": relative.as_posix(), "file_sha256": digest(compressed), "provenance": provenance,
        "historical_l2": False, "survivorship_bias": "current product universe; delisted assets not represented"}
    atomic_write(root / "manifests" / f"{symbol}-{timeframe}-{identity[:16]}.json", canonical(manifest))
    return manifest


def load_dataset(root: Path, manifest: dict[str, Any]) -> list[HistoricalBar]:
    path = (root / manifest["file"]).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("dataset_path_outside_store")
    payload = path.read_bytes()
    if digest(payload) != manifest["file_sha256"]:
        raise ValueError("dataset_hash_mismatch")
    result = []
    for line in gzip.decompress(payload).splitlines():
        raw = json.loads(line)
        raw["quality_flags"] = tuple(raw["quality_flags"])
        bar = HistoricalBar(**raw)
        validate_bar(bar)
        if bar.dataset_version != manifest["dataset_version"]:
            raise ValueError("dataset_version_mismatch")
        result.append(bar)
    if len(result) != manifest["observations"]:
        raise ValueError("dataset_count_mismatch")
    return result


class CoinbaseHistory:
    """Public GET-only, resumable immutable response cache. No currency conversion."""
    def __init__(self, root: Path, client: httpx.AsyncClient | None = None) -> None:
        self.root = root
        self.client = client or httpx.AsyncClient(base_url="https://api.exchange.coinbase.com", timeout=30)

    async def close(self) -> None:
        await self.client.aclose()

    async def _get(self, path: str, params: dict[str, str]) -> tuple[Any, dict[str, str]]:
        if path != "/products" and not (path.startswith("/products/") and path.endswith("/candles")):
            raise ValueError("historical_endpoint_not_allowed")
        key = digest(canonical({"path": path, "params": params}))
        cache = self.root / "raw" / f"{key}.json"
        if cache.exists():
            stored = json.loads(cache.read_text(encoding="utf-8"))
            if digest(stored["body"].encode("utf-8")) != stored["body_sha256"]:
                raise ValueError("raw_history_cache_hash_mismatch")
        else:
            for attempt in range(5):
                response = await self.client.get(path, params=params)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 4:
                    try:
                        delay = float(response.headers.get("Retry-After", 2 ** attempt))
                    except ValueError:
                        delay = float(2 ** attempt)
                    await asyncio.sleep(min(max(delay, .3), 30))
                    continue
                response.raise_for_status()
                body = response.text
                stored = {"url": str(response.url), "ingested_at": utc_now().isoformat(),
                          "body": body, "body_sha256": digest(body.encode("utf-8"))}
                atomic_write(cache, canonical(stored))
                break
            await asyncio.sleep(.15)
        return json.loads(stored["body"]), {"raw_cache": cache.name, "ingested_at": stored["ingested_at"], "body_sha256": stored["body_sha256"]}

    async def fetch(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> tuple[list[HistoricalBar], dict[str, Any]]:
        seconds = TIMEFRAMES[timeframe]
        if timeframe == "4h":
            raise ValueError("provider_has_no_4h_bars_aggregate_completed_1h")
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("invalid_historical_interval")
        if int(start.timestamp()) % seconds or int(end.timestamp()) % seconds or end.timestamp() > utc_now().timestamp():
            raise ValueError("unaligned_or_future_historical_interval")
        products, product_provenance = await self._get("/products", {})
        product = next((p for p in products if p.get("id") == symbol), None)
        if not product or product.get("quote_currency") != "EUR" or product.get("base_currency") not in ASSETS or symbol != product["base_currency"] + "-EUR":
            raise ValueError("unsupported_genuine_eur_product")
        result: list[HistoricalBar] = []
        pages = []
        cursor = int(start.timestamp())
        while cursor < int(end.timestamp()):
            stop = min(cursor + 300 * seconds, int(end.timestamp()))
            params = {"granularity": str(seconds), "start": datetime.fromtimestamp(cursor, UTC).isoformat(),
                      "end": datetime.fromtimestamp(stop - 1, UTC).isoformat()}
            rows, provenance = await self._get(f"/products/{symbol}/candles", params)
            pages.append(provenance)
            if not isinstance(rows, list):
                raise TypeError("invalid_provider_historical_response")
            for raw in rows:
                if not isinstance(raw, list) or len(raw) != 6:
                    raise ValueError("invalid_provider_candle_shape")
                timestamp, low, high, opening, closing, volume = raw
                if not cursor <= timestamp < stop:
                    continue
                flags = []
                if Decimal(str(volume)) == 0:
                    flags.append("ZERO_VOLUME")
                if Decimal(str(low)) > 0 and Decimal(str(high)) / Decimal(str(low)) > Decimal("1.5"):
                    flags.append("SUSPICIOUS_RANGE")
                if product.get("status") != "online" or product.get("trading_disabled"):
                    flags.append("CURRENTLY_INACTIVE_PRODUCT")
                bar = HistoricalBar(SOURCE, symbol, product["base_currency"], "EUR",
                    datetime.fromtimestamp(timestamp, UTC).isoformat(), timeframe,
                    str(opening), str(high), str(low), str(closing), str(volume),
                    provenance["ingested_at"], tuple(flags))
                validate_bar(bar)
                result.append(bar)
            cursor = stop
        return result, {"product": product, "product_response": product_provenance,
                        "pages": pages, "provider_docs": "https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles"}
