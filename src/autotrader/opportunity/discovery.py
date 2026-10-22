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
                 excluded: set[str] | None = None, limit: int = 3,
                 recent: dict[str, dict[str, Any]] | None = None, cycle_bucket: int = 0) -> tuple[list[DiscoveryCandidate], dict[str, int]]:
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
        # Movement is capped and multiplied by liquidity. A large percentage
        # range cannot overwhelm thin turnover or an expensive spread.
        liquidity = min(volume / 1000000, D(1))
        spread_quality = 1-spread/25
        net_movement = min(amplitude/(36+spread), D(3))
        prior = (recent or {}).get(symbol,{})
        elapsed = cycle_bucket-int(prior.get('bucket', cycle_bucket-12))
        if prior.get('data_failed') and elapsed < 2:
            counts['recent_data_failure_deferred'] = counts.get('recent_data_failure_deferred',0)+1
            continue
        exploration = min(max(elapsed,0),12)*D('.05')
        score = net_movement*liquidity*spread_quality + liquidity + exploration
        rows.append(DiscoveryCandidate(symbol, score, spread, amplitude, volume,
            'Liquidity-weighted capped range screen with bounded revisit priority; setup and depth remain unverified'))
    counts['screened'] = len(rows)
    return sorted(rows, key=lambda r: (-r.score, r.symbol))[:max(0, min(limit, 20))], counts
