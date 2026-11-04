"""Optional public snapshots for research, independent of protective worker calls. Untested and unvalidated."""
from __future__ import annotations

from typing import Any

from autotrader.perpetuals.market import PublicMarket, SYMBOL, clock_ms, number
from autotrader.perpetuals.micro.types import Book, Ticker


class ResearchMarket(PublicMarket):
    async def envelope(self, endpoint: str, **params: Any) -> tuple[dict[str, Any], int, int]:
        response = await self.client.get(
            'https://api.bybit.com/v5/market/' + endpoint,
            params={'category': 'linear', 'symbol': SYMBOL, **params},
        )
        response.raise_for_status()
        received = clock_ms()
        body = response.json()
        if body['retCode'] != 0:
            raise ValueError('research_market_request_rejected')
        return body['result'], int(body['time']), received

    async def book(self) -> Book:
        result, _, received = await self.envelope('orderbook', limit=50)
        if result['s'] != SYMBOL:
            raise ValueError('research_depth_symbol_mismatch')
        bids = tuple((number(row[0]), number(row[1])) for row in result['b'])
        asks = tuple((number(row[0]), number(row[1])) for row in result['a'])
        if len(bids) > 50 or len(asks) > 50 or not bids or not asks:
            raise ValueError('research_depth_size_invalid')
        # Matching-engine timestamp, not HTTP response generation time. Missing
        # cts is unknown execution timing; do not substitute a recent receipt.
        exchange = int(result['cts'])
        return Book(exchange, received, bids, asks, int(result['u']))

    async def ticker(self) -> Ticker:
        result, exchange, received = await self.envelope('tickers')
        if result['category'] != 'linear' or len(result['list']) != 1:
            raise ValueError('research_ticker_identity_mismatch')
        row = result['list'][0]
        if row['symbol'] != SYMBOL or not 0 <= received - exchange <= 2000:
            raise ValueError('research_ticker_stale_or_future')
        rate = row.get('fundingRate')
        return Ticker(exchange, received, number(row['markPrice']), int(row['nextFundingTime']),
                      number(rate, positive=False) if rate not in (None, '') else None)
