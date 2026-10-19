import asyncio
import json
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from autotrader.api.main import create_app
from autotrader.domain import TradingPair, utc_now
from autotrader.market_data.revolut import MarketDataError, RevolutXPublicClient
from autotrader.opportunity.discovery import rank_markets
from autotrader.persistence.models import SystemStateModel


def test_lightweight_discovery_ranks_supported_eur_and_refuses_missing_values():
    pairs = [TradingPair(s + '-EUR', s, 'EUR') for s in ('BTC', 'XRP', 'LINK', 'DOT')]
    def row(s, spread, volume):
        return {'symbol': s + '/EUR', 'bid': '100', 'ask': str(D(100) + spread), 'high_24h': '105', 'low_24h': '95', 'quote_volume_24h': volume}
    selected, counts = rank_markets(pairs, [row('BTC', D('.01'), '10000000'), row('LINK', D('.02'), '2000000'),
        row('XRP', D(1), '5000000'), row('DOT', D('.01'), None), row('NOT_SUPPORTED', D('.01'), '90000000')], excluded={'BTC-EUR'})
    assert [r.symbol for r in selected] == ['LINK-EUR']
    assert counts['missing_or_invalid_summary'] == 1 and counts['expensive_or_thin'] == 1


async def test_public_ticker_singleflight_cache_and_stale_metadata_refusal(monkeypatch):
    client = RevolutXPublicClient()
    calls = []
    async def response(*args):
        calls.append(1)
        return {'data': [{'symbol': 'BTC/EUR'}], 'metadata': {'timestamp': int(utc_now().timestamp()*1000)}}
    monkeypatch.setattr(client, '_request', response)
    try:
        a, b = await asyncio.gather(client.get_tickers(), client.get_tickers())
        assert a == b and len(calls) == 1
        a[0]['symbol'] = 'CHANGED'
        assert (await client.get_tickers())[0]['symbol'] == 'BTC/EUR'
        client._ticker_cache = None
        async def stale(*args):
            return {'data': [], 'metadata': {'timestamp': int((utc_now().timestamp()-120)*1000)}}
        monkeypatch.setattr(client, '_request', stale)
        with pytest.raises(MarketDataError, match='stale_or_invalid'):
            await client.get_tickers()
    finally:
        await client.close()


async def test_opportunity_api_missing_evidence_stays_unknown_and_pagination_is_authenticated(lab, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', lab.official.test_database_url)
    monkeypatch.setenv('ENVIRONMENT', 'test')
    monkeypatch.setenv('SHADOW_ENABLED', 'true')
    monkeypatch.setenv('DASHBOARD_PASSWORD', 'change-me')
    def missing():
        with TestClient(create_app()) as client:
            assert client.get('/api/opportunities').status_code == 401
            data = client.get('/api/opportunities', auth=('admin','change-me')).json()
            assert data['status'] == 'NOT_RECORDED' and 'technical_candidates' not in data
            assert client.get('/api/opportunities?limit=51', auth=('admin','change-me')).status_code == 422
    await asyncio.to_thread(missing)
    body = {'updated_at': utc_now().isoformat(), 'technical_candidates': 3,
            'rows': [{'symbol': str(i), 'technical_eligible': True, 'economic_eligible': False, 'score': '0.5'} for i in range(3)]}
    async with lab.official.session_factory() as session, session.begin():
        session.add(SystemStateModel(key='opportunity_snapshot', state='ERROR', reason='SyntheticProviderOutage', payload_json=json.dumps(body)))
    def pages():
        with TestClient(create_app()) as client:
            a = client.get('/api/opportunities?limit=2', auth=('admin','change-me')).json()
            b = client.get('/api/opportunities?limit=2&cursor=2', auth=('admin','change-me')).json()
            assert len(a['rows']) == 2 and len(b['rows']) == 1 and b['next_cursor'] is None
            assert a['stale'] is True and a['runtime_incident'] == 'SyntheticProviderOutage'
            assert client.get('/api/strategies/comparison', auth=('admin','change-me')).json()['read_only']
    await asyncio.to_thread(pages)
    assert not await lab.official.list_fills() and await lab.official.verify_invariants(D(500)) == []


async def test_discovery_stops_on_provider_deferral_and_never_creates_financial_actions(lab, monkeypatch):
    from types import SimpleNamespace

    from autotrader.market_data.revolut import RateLimitDeferred
    from autotrader.opportunity.service import OpportunityObserver

    client = RevolutXPublicClient()
    calls = []
    async def pairs():
        return [TradingPair(s+'-EUR', s, 'EUR') for s in ('LINK', 'XRP')]
    async def tickers():
        return [{'symbol': s+'/EUR','bid':'100','ask':'100.01','high_24h':'110','low_24h':'90','quote_volume_24h':'2000000'} for s in ('LINK','XRP')]
    async def unavailable(pair):
        calls.append(pair.symbol)
        raise RateLimitDeferred('synthetic_shared_provider_cooldown')
    monkeypatch.setattr(client, 'get_pairs', pairs)
    monkeypatch.setattr(client, 'get_tickers', tickers)
    try:
        observer = OpportunityObserver(lab.official, SimpleNamespace(client=client,get_validated_market=unavailable))
        assert await observer.observe([]) == [] and len(calls) == 1
        async with lab.official.session_factory() as session:
            row = await session.get(SystemStateModel, 'opportunity_snapshot')
            data = json.loads(row.payload_json)
            assert row.state == 'DEGRADED' and data['technical_candidates'] is None
            assert data['measurement']['shared_counter_deltas']['request_429'] is None
        assert not await lab.official.list_orders()
    finally:
        await client.close()
