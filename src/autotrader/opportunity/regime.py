"""Independent causal market dimensions. Compression never erases bullish trend."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from autotrader.domain import DataQuality, MarketFeatures

D = Decimal


def number(value: Any) -> Decimal | None:
    try:
        result = D(str(value))
        return result if result.is_finite() else None
    except Exception:
        return None


@dataclass(frozen=True)
class MarketRegimeAssessment:
    trend: str
    structure: tuple[str, ...]
    volatility: str
    liquidity: str
    benchmark: str
    as_of: str
    timeframes: dict[str, Any]
    evidence: dict[str, Any]
    missing: tuple[str, ...]
    version: str = "multidimensional-regime/4.6.0"

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def assess_regime(f: MarketFeatures, btc: MarketFeatures | None = None,
                  eth: MarketFeatures | None = None) -> MarketRegimeAssessment:
    close, atr = number(f.metadata.get("last_close")), number(f.atr)
    short, long = number(f.ema_21), number(f.ema_50)
    missing = tuple(k for k, v in {"close": close, "atr": atr, "ema21": short, "ema50": long}.items() if v is None or v <= 0)
    normalized = (short - long) / atr if not missing and short and long and atr else None
    trend = "UNKNOWN"
    if normalized is not None and close and short and long:
        if normalized > 0 and close >= long:
            trend = "STRONG_BULLISH" if normalized >= 1 and close >= short else "MODERATE_BULLISH"
        elif normalized < 0 and close < long:
            trend = "STRONG_BEARISH" if normalized <= -1 and close < short else "MODERATE_BEARISH"
        else:
            trend = "NEUTRAL"
    width = (f.bollinger_upper - f.bollinger_lower) / f.bollinger_mid if (
        f.bollinger_upper is not None and f.bollinger_lower is not None and f.bollinger_mid and f.bollinger_mid > 0) else None
    structure = []
    if width is not None and width < D(".04"):
        structure.append("COMPRESSION")
    fraction = atr / close if atr and close and close > 0 else None
    momentum = number(f.momentum)
    if fraction and momentum is not None and abs(momentum) > fraction and f.relative_volume and f.relative_volume >= D("1.5"):
        structure.append("EXPANSION")
    if normalized is not None:
        structure.append("TRENDING" if abs(normalized) >= D(".5") else "RANGING")
    if atr and f.ema_21 and close and (close - f.ema_21) / atr > 3:
        structure.append("EXHAUSTION")
    volatility = "UNKNOWN" if fraction is None else "LOW" if fraction < D(".003") else "NORMAL" if fraction < D(".01") else "ELEVATED" if fraction < D(".04") else "EXTREME"
    spread = number(f.spread_bps)
    depth = number(f.metadata.get("liquidity_quote"))
    age = number(f.metadata.get("order_book_age_seconds"))
    unreliable = f.data_quality is not DataQuality.GOOD or bool(missing) or not f.metadata.get("history_contiguous", True) or (age is not None and age > 90)
    liquidity = "UNRELIABLE_DATA" if unreliable else "UNKNOWN" if spread is None or depth is None else "EXPENSIVE_EXECUTION" if spread > 25 else "THIN" if depth < 150 else "HEALTHY"
    peers = {name: p for name, p in (("BTC", btc), ("ETH", eth)) if p is not None and p.timestamp == f.timestamp}
    supportive = {name: bool(p.ema_21 and p.ema_50 and p.ema_21 > p.ema_50 and number(p.metadata.get("last_close")) is not None and D(str(p.metadata["last_close"])) >= p.ema_50) for name, p in peers.items()}
    benchmark = "UNKNOWN" if len(peers) < 2 else "SUPPORTIVE" if all(supportive.values()) else "ADVERSE" if not any(supportive.values()) else "MIXED"
    return MarketRegimeAssessment(trend, tuple(structure), volatility, liquidity, benchmark,
        f.timestamp.isoformat(), dict(f.metadata.get("successor_context", {})),
        {"ema_separation_atr": str(normalized) if normalized is not None else None,
         "atr_fraction": str(fraction) if fraction is not None else None, "bollinger_width": str(width) if width is not None else None,
         "benchmark_support": supportive, "threshold_policy": "Unvalidated deterministic research parameters; separate from frozen classifier"}, missing)
