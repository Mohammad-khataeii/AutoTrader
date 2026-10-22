"""Bounded public-data discovery measurement in a disposable loopback PostgreSQL domain."""
from __future__ import annotations

import asyncio
import json
import os
import time
from decimal import Decimal as D
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from autotrader.config import Settings
from autotrader.indicators import calculate_features
from autotrader.market_data.revolut import RevolutXPublicClient
from autotrader.market_data.service import MarketDataService
from autotrader.opportunity.service import OpportunityObserver
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.models import SystemStateModel
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.scanner import ScanCandidate


async def main():
    admin=os.environ['AUTOTRADER_TEST_PG_ADMIN_URL'];base=make_url(admin)
    if base.host not in {'localhost','127.0.0.1'}:raise ValueError('loopback_disposable_database_required')
    name='autotrader_test_v46_rc2_public_'+uuid4().hex[:12]
    with psycopg.connect(admin,autocommit=True) as conn:conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    settings=Settings(database_url=base.set(drivername='postgresql+asyncpg',database=name).render_as_string(hide_password=False),environment='test',_env_file=None)
    engine=make_engine(settings);await create_schema(engine)
    repo=PersistentTradingRepository(make_session_factory(engine));await repo.initialize_portfolio(D(500))
    client=RevolutXPublicClient(event_recorder=repo.market_metric,
        rate_reserver=lambda family:repo.reserve_public_request(family),cooldown_publisher=repo.defer_public_requests)
    feed=MarketDataService(client,candle_lookback=720,state_store=repo)
    report={'evidence_class':'REAL_PUBLIC_MARKET_OBSERVATION_LOCAL_DISPOSABLE_DATABASE','production_connections':False,
        'financial_actions':False,'configurations':[],'baseline_data_failures':[],'false_positive_rate':None,
        'limitations':['One current public observation, not a profitability or sustained 429 improvement measurement.','Shared base observations and warm cache make incremental comparison explicit.']}
    try:
        started=time.perf_counter();pairs=await client.get_pairs();candidates=[]
        for pair in pairs:
            if pair.symbol not in {'BTC-EUR','ETH-EUR','SOL-EUR'}:continue
            try:
                market=await feed.get_validated_market(pair)
                if not market.usable_for_entry:
                    report['baseline_data_failures'].append({'symbol':pair.symbol,'reasons':market.rejected_reasons});continue
                f=calculate_features(market.candles[-240:],market.metrics.imbalance,market.metrics.spread_bps)
                f.metadata.update(liquidity_quote=market.metrics.liquidity_quote,order_book_age_seconds=market.metrics.age_seconds)
                candidates.append(ScanCandidate(market,f,[],None,None,D(0)))
            except Exception as exc:report['baseline_data_failures'].append({'symbol':pair.symbol,'reason':type(exc).__name__})
        report['base_preparation_seconds']=time.perf_counter()-started
        for extra in (0,6):
            observer=OpportunityObserver(repo,feed,extra_pairs=extra)
            await observer.observe(candidates)
            async with repo.session_factory() as session,session.begin():
                row=await session.get(SystemStateModel,'opportunity_snapshot');payload=json.loads(row.payload_json)
                report['configurations'].append({'extra_pairs':extra,**{k:v for k,v in payload.items() if k!='rows'}})
                await session.delete(row)
        assert not await repo.list_orders() and not await repo.list_fills()
        report['status']='MEASURED'
    except Exception as exc:
        report['status']='MEASUREMENT_INCOMPLETE';report['error']=type(exc).__name__
    finally:
        await feed.close();await engine.dispose()
        with psycopg.connect(admin,autocommit=True) as conn:conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        Path('docs/evidence/v4_6_rc2/public-discovery-measurement.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))


if __name__=='__main__':asyncio.run(main())
