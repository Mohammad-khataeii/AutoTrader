"""Public GET-only provider with protective priority, pagination and bounded caches."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from time import monotonic
from typing import Any

import httpx

from autotrader.perpetuals.market import Bar, MINUTE, clock_ms, number
from autotrader.perpetuals.micro.types import Book, Ticker
from autotrader.perpetuals.multi.contracts import Contract, parse_tiers
from autotrader.perpetuals.multi.policy import D


class PublicUnavailable(ValueError):
    pass


class RequestGate:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.next_at = 0.0
        self.cooldown = 0.0
        self.protective_waiters = 0
        self.scan_waiters = 0
        self.protective_burst = 0

    async def wait(self, protective: bool) -> None:
        if protective:self.protective_waiters += 1
        else:self.scan_waiters += 1
        try:
            while True:
                async with self.lock:
                    delay = max(self.next_at, self.cooldown) - monotonic()
                    scan_turn=self.scan_waiters>0 and self.protective_burst>=8
                    allowed=(protective and not scan_turn) or (not protective and (self.protective_waiters==0 or scan_turn))
                    if delay <= 0 and allowed:
                        self.next_at = monotonic() + .2
                        self.protective_burst=self.protective_burst+1 if protective else 0
                        return
                await asyncio.sleep(max(.02, min(1., delay if delay > 0 else .05)))
        finally:
            if protective:self.protective_waiters -= 1
            else:self.scan_waiters -= 1


class MultiMarket:
    def __init__(self, scan_client: httpx.AsyncClient, protective_client: httpx.AsyncClient):
        self.scan_client, self.protective_client = scan_client, protective_client
        self.gate = RequestGate()
        self._instruments: tuple[float, dict[str, dict[str, Any]]] | None = None
        self._contracts: OrderedDict[str, tuple[float, Contract]] = OrderedDict()
        self._candles: OrderedDict[tuple[str,int], dict[int,Bar]] = OrderedDict()

    async def get(self, endpoint: str, *, protective: bool = False, **params: Any) -> tuple[dict[str,Any],int,int]:
        if endpoint not in {'instruments-info','tickers','risk-limit','kline','mark-price-kline','orderbook','funding/history'}:
            raise PublicUnavailable('public_endpoint_not_allowed')
        await self.gate.wait(protective)
        client = self.protective_client if protective else self.scan_client
        response = await client.get('https://api.bybit.com/v5/market/' + endpoint,
                                    params={'category':'linear', **params})
        if response.status_code == 429:
            self.gate.cooldown = monotonic() + 30
            raise PublicUnavailable('provider_rate_limit_cooldown')
        response.raise_for_status()
        received = clock_ms();body = response.json()
        if body['retCode'] != 0:
            if body['retCode'] in (10006, 10429):self.gate.cooldown = monotonic() + 30
            raise PublicUnavailable('provider_rejected_public_request')
        return body['result'], int(body['time']), received

    async def pages(self, endpoint: str, *, protective: bool = False, **params: Any) -> list[dict[str,Any]]:
        cursor, visited, rows = '', set(), []
        for _ in range(100):
            body, _, _ = await self.get(endpoint, protective=protective, **params, **({'cursor':cursor} if cursor else {}))
            if body.get('category') != 'linear':raise PublicUnavailable('contract_category_mismatch')
            rows.extend(body['list'])
            cursor = body.get('nextPageCursor') or ''
            if not cursor:return rows
            if cursor in visited:raise PublicUnavailable('repeated_provider_cursor')
            visited.add(cursor)
        raise PublicUnavailable('contract_catalog_incomplete_page_budget')

    async def instruments(self) -> dict[str,dict[str,Any]]:
        if self._instruments is None or monotonic()-self._instruments[0] > 300:
            rows = await self.pages('instruments-info', status='Trading', limit=1000)
            symbols = [r['symbol'] for r in rows]
            if len(symbols) != len(set(symbols)):raise PublicUnavailable('duplicate_contract_metadata')
            self._instruments = monotonic(), {r['symbol']:r for r in rows}
        return self._instruments[1]

    async def tickers(self) -> tuple[list[dict[str,Any]],int]:
        result, exchange, received = await self.get('tickers')
        if result['category'] != 'linear' or not 0 <= received-exchange <= 5000:
            raise PublicUnavailable('stale_summary_or_wrong_category')
        return result['list'], received

    async def contract(self, symbol: str, *, protective: bool = False) -> Contract:
        saved = self._contracts.get(symbol)
        if saved and monotonic()-saved[0] <= 300:
            self._contracts.move_to_end(symbol)
            return saved[1]
        # Protective metadata does not queue a whole catalog refresh.
        if protective:
            rows = await self.pages('instruments-info', protective=True, symbol=symbol)
            row = next((r for r in rows if r['symbol']==symbol),None)
        else:row = (await self.instruments()).get(symbol)
        if row is None or row.get('status') != 'Trading' or row.get('contractType') != 'LinearPerpetual':
            raise PublicUnavailable('contract_not_actively_trading')
        if row.get('settleCoin') != 'USDT' or row.get('quoteCoin') != 'USDT' or row.get('isPreListing'):
            raise PublicUnavailable('not_standard_usdt_perpetual')
        if row.get('marketRegion') or row.get('deliveryTime') not in (None,'','0',0):
            raise PublicUnavailable('session_limited_or_delisting_contract')
        lots, leverage, prices = row['lotSizeFilter'],row['leverageFilter'],row['priceFilter']
        tiers = parse_tiers(await self.pages('risk-limit',symbol=symbol,protective=protective),symbol)
        minutes = int(row['fundingInterval'])
        if not 1 <= minutes <= 1440:raise PublicUnavailable('unsupported_funding_interval')
        contract = Contract(symbol,row['baseCoin'],*(number(lots[k]) for k in
            ('qtyStep','minOrderQty','minNotionalValue','maxMktOrderQty')),
            number(prices['tickSize']),*(number(leverage[k]) for k in ('minLeverage','maxLeverage','leverageStep')),
            minutes,tiers,clock_ms())
        self._contracts[symbol] = monotonic(),contract
        self._contracts.move_to_end(symbol)
        while len(self._contracts)>256:self._contracts.popitem(last=False)
        return contract

    async def observation(self, symbol: str, *, protective: bool = False) -> tuple[Book,Ticker]:
        async def book():
            row, _, received = await self.get('orderbook',symbol=symbol,limit=50,protective=protective)
            if row['s'] != symbol:raise PublicUnavailable('depth_symbol_mismatch')
            bids = tuple((number(r[0]),number(r[1])) for r in row['b'])
            asks = tuple((number(r[0]),number(r[1])) for r in row['a'])
            if not bids or not asks or max(len(bids),len(asks))>50:raise PublicUnavailable('invalid_depth_size')
            return Book(int(row['cts']),received,bids,asks,int(row['u']))
        async def ticker():
            body, exchange, received = await self.get('tickers',symbol=symbol,protective=protective)
            if body['category']!='linear' or len(body['list'])!=1 or body['list'][0]['symbol']!=symbol:
                raise PublicUnavailable('ticker_identity_mismatch')
            row=body['list'][0]
            if not 0<=received-exchange<=3000:raise PublicUnavailable('stale_or_future_mark')
            return Ticker(exchange,received,number(row['markPrice']),int(row['nextFundingTime']),
                          number(row['fundingRate'],positive=False) if row.get('fundingRate') else None)
        return await asyncio.gather(book(),ticker())

    async def bars(self, symbol: str, start: int, end: int, *, mark: bool = False,
                   protective: bool = False) -> dict[int,Bar]:
        if start % MINUTE or end % MINUTE or end < start or (end-start)//MINUTE >= 1000:
            raise PublicUnavailable('invalid_candle_request_window')
        key=(symbol,end)
        if not mark and key in self._candles and min(self._candles[key],default=end+1)<=start:
            self._candles.move_to_end(key);return self._candles[key]
        body, _, _ = await self.get('mark-price-kline' if mark else 'kline',symbol=symbol,
            interval='1',start=start,end=end+MINUTE-1,limit=(end-start)//MINUTE+1,protective=protective)
        if body['symbol']!=symbol or body['category']!='linear':raise PublicUnavailable('candle_identity_mismatch')
        rows={}
        for r in body['list']:
            t=int(r[0]);bar=Bar(t,*(number(v) for v in r[1:5]),
                               volume=number(r[5],positive=False) if not mark and len(r)>5 else None)
            if (t in rows or not start<=t<=end or t%MINUTE or t+MINUTE>clock_ms()
                    or not bar.low<=min(bar.open,bar.close)<=max(bar.open,bar.close)<=bar.high
                    or bar.volume is not None and bar.volume<0):
                raise PublicUnavailable('invalid_completed_candle')
            rows[t]=bar
        if set(rows)!=set(range(start,end+1,MINUTE)):raise PublicUnavailable('missing_completed_candles')
        if not mark:
            self._candles[key]=rows
            while len(self._candles)>128:self._candles.popitem(last=False)
        return rows

    async def funding(self, symbol: str, start: int, end: int) -> dict[int,tuple[Any,Any]]:
        """Inclusive settled events, backwards pagination, matching event-time mark proxies."""
        rates={};cursor=end
        for _ in range(30):
            body, _, _ = await self.get('funding/history',symbol=symbol,startTime=start,endTime=cursor,
                                        limit=200,protective=True)
            rows=body['list']
            for row in rows:
                t=int(row['fundingRateTimestamp'])
                if row['symbol']!=symbol or not start<=t<=cursor:raise PublicUnavailable('invalid_funding_history')
                rate=number(row['fundingRate'],positive=False)
                if t in rates and rates[t]!=rate:raise PublicUnavailable('conflicting_funding_history')
                rates[t]=rate
            if len(rows)<200:break
            earliest=min(int(r['fundingRateTimestamp']) for r in rows)
            if earliest<=start:break
            cursor=earliest-1
        else:raise PublicUnavailable('funding_backlog_requires_operator_review')
        result={}
        for t,rate in sorted(rates.items()):
            minute=t//MINUTE*MINUTE
            # At a settlement boundary its minute may still be open; the opening
            # mark is fixed, so request the preceding completed minute's close.
            bars=await self.bars(symbol,minute-MINUTE,minute-MINUTE,mark=True,protective=True)
            result[t]=(rate,bars[minute-MINUTE].close)
        return result
