"""Actual ARM64 image, isolated deterministic EUR7000 financial lifecycle."""
import asyncio
import json
import os
import sys
import tempfile
from decimal import Decimal as D
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from autotrader.config import Settings
from autotrader.indicators import calculate_features
from autotrader.market_data.replay import FileReplayClient
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.personal_paper.policy import INITIAL
from autotrader.personal_paper.runtime import PersonalPaperRuntime
from autotrader.personal_paper.service import PersonalPaperService
from autotrader.scanner import ScanCandidate

sys.path.insert(0,'/acceptance/tests')
from v46_support import successor_frame


async def main():
    base=make_url(os.environ['DATABASE_URL'])
    if base.host!='acceptance-postgres' or os.environ.get('AUTOTRADER_SYNTHETIC_ACCEPTANCE')!='1':raise ValueError('isolated_synthetic_cluster_required')
    database='autotrader_test_v47_primary'
    with psycopg.connect(base.set(drivername='postgresql',database='postgres').render_as_string(hide_password=False),autocommit=True) as c:
        c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
    settings=Settings(database_url=base.set(database=database).render_as_string(hide_password=False),environment='test',personal_paper_enabled=True,_env_file=None)
    engine=make_engine(settings);await create_schema(engine)
    official=PersistentTradingRepository(make_session_factory(engine));await official.initialize_portfolio(D(500))
    service=PersonalPaperService(official,settings);repo=await service.ensure()
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'fixture.json';path.write_text(json.dumps(successor_frame('A3_COST_AWARE_CONTINUATION')))
        client=FileReplayClient(str(path));feed=MarketDataService(client,candle_lookback=720)
        runtime=PersonalPaperRuntime(service,feed,'container-primary')
        candidates=[]
        for pair in await feed.discover_pairs():
            m=await feed.get_validated_market(pair)
            candidates.append(ScanCandidate(m,calculate_features(m.candles[-240:],m.metrics.imbalance,m.metrics.spread_bps),[],None,None,D(1)))
        await runtime.scan(candidates);await runtime.scan(candidates)
        positions=[p for p in await repo.list_positions() if p.quantity>0];assert positions
        count=len(await repo.list_fills());await service.close();repo=await service.repository();await runtime.scan(candidates)
        assert len(await repo.list_fills())==count
        target=max(p.take_profit_targets[0] for p in positions)*D('1.02')
        for p in positions:
            from dataclasses import replace

            from autotrader.domain import OrderBookLevel, utc_now
            c=next(c for c in candidates if c.features.symbol==p.symbol)
            book=replace(c.market.order_book,timestamp=utc_now(),bids=(OrderBookLevel(target,D(10000)),),asks=(OrderBookLevel(target+D('.01'),D(10000)),))
            assert (await runtime.gateway(repo).execute_exit(c.market.pair,p.target_quantities[0],book,'partial-'+p.position_id,'take_profit_target',position_id=p.position_id,exit_target_id=p.target_ids[0])).accepted
        frame=successor_frame('A3_COST_AWARE_CONTINUATION');frame['frame_id']='synthetic-stop'
        for m in frame['markets'].values():m['book'].update(bids=[['110','1000']],asks=[['110.01','1000']])
        path.write_text(json.dumps(frame));client.refresh()
        async with feed.protective_cycle():await runtime.monitor()
        assert all(p.quantity==0 for p in await repo.list_positions())
        assert await repo.verify_invariants(INITIAL)==[]
        assert not await official.list_orders() and D((await official.snapshot())['equity'])==500
        detail=await service.detail();assert detail['performance']['buy_fills'] and detail['performance']['sell_fills']
        print(json.dumps({'status':'PASS','evidence_category':'SYNTHETIC_DETERMINISTIC_ENGINEERING_TEST','architecture':__import__('platform').machine(),
            'account_id':repo.account_id,'initial_cash':'7000','official_equity':'500','reconciliation':[],
            'performance':detail['performance'],'portfolio':detail['portfolio'],'restart_duplicate_fill':False},default=str))
        await feed.close()
    await service.close();await engine.dispose()


if __name__=='__main__':asyncio.run(main())
