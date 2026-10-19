"""Cheap public ticker ranking before a bounded number of expensive validations."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from autotrader.domain import TradingPair
from autotrader.opportunity.regime import number

D = Decimal


@dataclass(frozen=True)
class DiscoveryCandidate:
    symbol: str
    score: Decimal
    spread_bps: Decimal
    daily_range_bps: Decimal
    quote_volume: Decimal
    evidence: str = "Ticker screen only; history, depth, regime and setup are not yet verified"

    def payload(self) -> dict[str, Any]:
        return {k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()}


def rank_markets(pairs: list[TradingPair], tickers: list[dict[str, Any]], *,
                 excluded: set[str] | None = None, limit: int = 3) -> tuple[list[DiscoveryCandidate], dict[str, int]]:
    supported = {p.symbol for p in pairs if p.quote_asset == 'EUR' and p.status.lower() == 'active' and p.price_step > 0 and p.quantity_step > 0}
    rows: list[DiscoveryCandidate] = []
    counts = {'supported_eur': len(supported), 'missing_or_invalid_summary': 0, 'expensive_or_thin': 0, 'screened': 0}
    seen = set()
    for ticker in tickers:
        symbol = str(ticker.get('symbol', '')).replace('/', '-')
        if symbol not in supported or symbol in seen or symbol in (excluded or set()):
            continue
        seen.add(symbol)
        bid, ask, high, low, volume = (number(ticker.get(k)) for k in ('bid', 'ask', 'high_24h', 'low_24h', 'quote_volume_24h'))
        if any(v is None or v <= 0 for v in (bid, ask, high, low, volume)):
            counts['missing_or_invalid_summary'] += 1
            continue
        assert bid is not None and ask is not None and high is not None and low is not None and volume is not None
        if ask <= bid or high < low:
            counts['missing_or_invalid_summary'] += 1
            continue
        spread = (ask - bid) / ((ask + bid) / 2) * 10000
        amplitude = (high - low) / ((ask + bid) / 2) * 10000
        if spread > 25 or volume < 100000:
            counts['expensive_or_thin'] += 1
            continue
        # Bounded independent factors; daily range is an exploration proxy, not ATR or a target forecast.
        score = min(amplitude / (36 + spread), D(10)) * D('.5') + min(volume / 1000000, D(5)) * D('.3') + (1 - spread / 25) * D('.2')
        rows.append(DiscoveryCandidate(symbol, score, spread, amplitude, volume))
    counts['screened'] = len(rows)
    return sorted(rows, key=lambda r: (-r.score, r.symbol))[:max(0, min(limit, 6))], counts
