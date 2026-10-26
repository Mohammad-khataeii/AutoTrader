"""Read models must agree with actual accounting and active feed coverage."""
import asyncio
import json
from datetime import timedelta
from decimal import Decimal as D

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from autotrader.api.main import create_app
from autotrader.domain import utc_now
from autotrader.persistence.models import EquitySnapshotModel, MarketMarkModel, SystemStateModel
from autotrader.shadow.views import account_summary
from test_v4_execution import PAIR, book
from test_v42_shadow import enter


async def test_summary_financial_values_match_partial_exit_and_preserve_stale_mark_uncertainty(lab):
    record=await lab.create('mac-summary','Disposable summary acceptance','A_TREND_PULLBACK')
    repo=await lab.repository(record['experiment_id'])
    result,gateway=await enter(repo)
    assert result.accepted
    position=(await repo.list_positions())[0]
    assert (await gateway.execute_exit(PAIR,position.quantity/2,book('110','110.01'),'mac-half','manual',position_id=position.position_id)).accepted
    authoritative=await repo.snapshot()
    async with repo.session_factory() as session:
        before=await session.scalar(select(func.count()).select_from(EquitySnapshotModel))
    compact=(await account_summary(repo))['portfolio']
    for name in ('cash','available_cash','reserved_cash','open_exposure','realized_pnl','unrealized_pnl','equity','total_net_pnl'):
        assert D(compact[name])==D(authoritative[name]),name
    async with repo.session_factory() as session,session.begin():
        assert before==await session.scalar(select(func.count()).select_from(EquitySnapshotModel))
        mark=await session.get(MarketMarkModel,PAIR.symbol)
        mark.timestamp=utc_now()-timedelta(days=1)
    stale=(await account_summary(repo))['portfolio']
    assert stale['equity']==stale['open_exposure']==stale['unrealized_pnl']==''
    assert stale['valuation_degraded']=='true'
    assert D(stale['realized_pnl'])==D(authoritative['realized_pnl'])
    assert not await lab.official.list_fills()


async def test_monitoring_uses_active_scanner_coverage_and_keeps_missing_or_stale_active_data_unhealthy(lab,monkeypatch):
    monkeypatch.setenv('DATABASE_URL',lab.official.test_database_url)
    monkeypatch.setenv('ENVIRONMENT','test')
    monkeypatch.setenv('DASHBOARD_PASSWORD','change-me')
    async with lab.official.session_factory() as session,session.begin():
        session.add(SystemStateModel(key='scanner',state='OK',reason='real_test_scan',payload_json=json.dumps({'candidates':[{'symbol':'BTC-EUR'}]})))
    def request():
        app=create_app()
        cache=[{'key':'BTC-EUR:5:720','age_seconds':10,'observations':719},
               {'key':'RETIRED-EUR:5:720','age_seconds':900,'observations':719}]
        async def market_health():return {'caches':cache}
        app.state.repository.market_data_health=market_health
        with TestClient(app) as client:
            auth=('admin','change-me')
            assert client.get('/api/overview/summary',auth=auth).json()['application_version']==app.version
            body=client.get('/api/monitoring/summary',auth=auth).json()['market_data']
            assert body['live_observations_fresh'] is True and body['historical_cache_entries']==1
            assert body['active_scanner_symbols']==['BTC-EUR']
            cache[0]['age_seconds']=500
            assert client.get('/api/monitoring/summary',auth=auth).json()['market_data']['live_observations_fresh'] is False
            cache.pop(0)
            assert client.get('/api/monitoring/summary',auth=auth).json()['market_data']['live_observations_fresh'] is False
    await asyncio.to_thread(request)
