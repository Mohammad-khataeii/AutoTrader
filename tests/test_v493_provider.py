"""Concurrent public reads, timestamp integrity and protection priority."""
import asyncio
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from autotrader.clock import at
from autotrader.market_data.revolut import RevolutXPublicClient
from autotrader.market_data.scheduling import protective_priority


async def test_coalescing_cancelled_waiter_and_fresh_subsequent_request():
    c=RevolutXPublicClient();started=asyncio.Event();release=asyncio.Event();calls=[]
    async def request(path,params):
        calls.append(path);started.set();await release.wait()
        return {'data':{'stamp':'original','rows':[1]}}
    c._request_once=request
    a=asyncio.create_task(c._request('/2.0/public/order-book/BTC-EUR',{'limit':50}))
    await started.wait()
    b=asyncio.create_task(c._request('/2.0/public/order-book/BTC-EUR',{'limit':50}))
    await asyncio.sleep(0);a.cancel()
    with pytest.raises(asyncio.CancelledError):await a
    release.set();result=await b
    assert len(calls)==1 and result['data']['stamp']=='original'
    result['data']['rows'].append(2)
    again=await c._request('/2.0/public/order-book/BTC-EUR',{'limit':50})
    assert len(calls)==2 and again['data']['rows']==[1]
    await c.close()


async def test_protection_has_independent_singleflight_and_ticker_subset_reuses_timestamp():
    c=RevolutXPublicClient();release=asyncio.Event();calls=[]
    async def request(path,params):
        calls.append(path);await release.wait();return {'data':[]}
    c._request_once=request
    discovery=asyncio.create_task(c._request('/2.0/public/order-book/BTC-EUR'))
    await asyncio.sleep(0)
    async with protective_priority():protection=asyncio.create_task(c._request('/2.0/public/order-book/BTC-EUR'))
    await asyncio.sleep(0);await asyncio.sleep(0);release.set();await asyncio.gather(discovery,protection)
    assert len(calls)==2
    now=datetime(2026,10,30,tzinfo=UTC)
    c._ticker_cache=(now,[{'symbol':'BTC/EUR','last':'100'},{'symbol':'ETH/EUR','last':'10'}])
    with at(now):assert await c.get_tickers(['BTC-EUR'])==[{'symbol':'BTC/EUR','last':'100'}]
    assert len(calls)==2 and c._ticker_cache[0]==now
    await c.close()


async def test_real_endpoint_shared_pacing_margin_preserves_other_families(pg_repo):
    await pg_repo.initialize_portfolio(D(500));now=datetime(2026,10,30,tzinfo=UTC)
    with at(now):
        assert await pg_repo.reserve_public_request('/2.0/public/order-book')==0
        assert await pg_repo.reserve_public_request('/2.0/public/order-book',priority=0)==pytest.approx(1.05)
        assert await pg_repo.reserve_public_request('/1.0/public/candles')==0
