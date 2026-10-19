"""Exercise actual candidate image execution against disposable synthetic domains."""
from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import tempfile
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

from autotrader.config import Settings
from autotrader.indicators import calculate_features, higher_timeframe_context
from autotrader.market_data.replay import FileReplayClient
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.risk import RiskEngine, RiskLimits
from autotrader.scanner import ScanCandidate
from autotrader.shadow.lab import ShadowLab
from autotrader.shadow.runtime import ShadowRuntime
from autotrader.shadow.versions import (
    compatibility,
    execution_fingerprint,
    frozen_module,
    verify_legacy,
    verify_v44,
)

sys.path.insert(0, '/acceptance/tests')
from process_support import write_frame
from test_v42_lifecycle import experimental_frame

STRATEGIES = ('A2_CONFIRMED_PULLBACK', 'B2_CONFIRMED_COMPRESSION', 'C2_LIQUID_RETEST', 'E2_ABSOLUTE_RELATIVE_STRENGTH')


def frame(strategy):
    result = experimental_frame('container-entry-' + strategy, D('129.4'))
    if strategy.startswith('B2'):
        for market in result['markets'].values():
            market['candles'][-2].update(close='129.3', high='129.6', volume='2500')
            market['candles'][-1].update(open='129.3', close='129.4', high='129.7', low='129.0', volume='2000')
    if strategy.startswith('C2'):
        for market in result['markets'].values():
            market['candles'][-2].update(open='128.8', close='129.4', high='129.5', volume='2500')
            market['candles'][-1].update(open='129.4', close='129.7', high='130.0', low='128.9', volume='2000')
            market['book']['bids'] = [['129.7', '1000']]
            market['book']['asks'] = [['129.71', '1000']]
    if strategy.startswith('E2'):
        result['pairs'].append({**result['pairs'][0], 'symbol': 'SOL-EUR', 'base_asset': 'SOL'})
        result['markets']['SOL-EUR'] = copy.deepcopy(result['markets']['BTC-EUR'])
        for i, candle in enumerate(result['markets']['SOL-EUR']['candles']):
            close = D(100)+D(i)*D('.04')+D(max(0, i-699))*D('.23')
            candle.update(open=str(close-D('.1')), high=str(close+D('1.5')), low=str(close-D('1.5')), close=str(close), volume='2000' if i == 719 else '1000')
        result['markets']['SOL-EUR']['book']['bids'] = [['133.36', '1000']]
        result['markets']['SOL-EUR']['book']['asks'] = [['133.37', '1000']]
    return result


async def main():
    base = make_url(os.environ['DATABASE_URL'])
    if base.host != 'acceptance-postgres' or os.environ.get('AUTOTRADER_SYNTHETIC_ACCEPTANCE') != '1':
        raise ValueError('disposable_acceptance_cluster_required')
    output = {'evidence_class': 'SYNTHETIC_DETERMINISTIC_ENGINEERING_TEST', 'architecture': __import__('platform').machine(),
              'candidate_execution': execution_fingerprint(), 'v42_files': len(verify_legacy()), 'v44_files': len(verify_v44()), 'accounts': []}
    for generation in ('v42', 'v44', 'v45'):
        database = 'autotrader_test_rc2_' + generation
        with psycopg.connect(base.set(drivername='postgresql', database='postgres').render_as_string(hide_password=False), autocommit=True) as conn:
            from psycopg import sql
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        settings = Settings(database_url=base.set(database=database).render_as_string(hide_password=False),
                            environment='test', shadow_enabled=True, _env_file=None)
        engine = make_engine(settings)
        await create_schema(engine)
        official = PersistentTradingRepository(make_session_factory(engine))
        await official.initialize_portfolio(D(500))
        lab = ShadowLab(official, settings)
        builder = lab
        if generation != 'v45':
            old = lambda name, selected=generation: frozen_module(name, selected)
            builder = old('shadow.lab').ShadowLab(old('persistence.repository').PersistentTradingRepository(official.session_factory), settings)
        try:
            for strategy in STRATEGIES:
                record = await builder.create(strategy, 'Synthetic container lifecycle', strategy)
                manifest = record['manifest']
                assert compatibility(manifest)['compatible']
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory)/'frame.json'
                    observation = frame(strategy)
                    write_frame(path, observation)
                    client = FileReplayClient(str(path))
                    feed = MarketDataService(client, candle_lookback=720)
                    runtime = ShadowRuntime(lab, feed, RiskEngine(RiskLimits()), 'container-' + generation)
                    candidates = []
                    for pair in await feed.discover_pairs():
                        market = await feed.get_validated_market(pair)
                        f = calculate_features(market.candles[-240:], market.metrics.imbalance, market.metrics.spread_bps)
                        f.metadata['higher_timeframe_confirmation'] = higher_timeframe_context(market.candles[-240:])
                        for key in ('best_bid', 'best_ask', 'spread_bps', 'bid_depth', 'ask_depth', 'liquidity_quote', 'provider_latency_ms', 'age_seconds'):
                            f.metadata['order_book_age_seconds' if key == 'age_seconds' else key] = getattr(market.metrics, key)
                        f.metadata['last_price'] = market.metrics.mid
                        candidates.append(ScanCandidate(market, f, [], None, None, D(0)))
                    await runtime.scan(candidates)
                    repo = await lab.repository(record['experiment_id'])
                    fills = await repo.list_fills()
                    assert len(fills) == 1, (generation, strategy, await repo.list_orders())
                    await runtime.scan(candidates)
                    assert len(await repo.list_fills()) == 1
                    position = (await repo.list_positions())[0]
                    assert position.protective_stop and len(await repo.list_targets(position.position_id)) == 3
                    # Release connections and reconstruct the correct runner before protection.
                    if generation == 'v42':
                        await runtime.legacy().close()
                    elif generation == 'v44':
                        await runtime.frozen_v44().close()
                    runtime = ShadowRuntime(lab, feed, RiskEngine(RiskLimits()), 'container-' + generation)
                    stop = experimental_frame('container-stop', D(127))
                    if strategy.startswith('E2'):
                        stop['pairs'].append(observation['pairs'][-1])
                        stop['markets']['SOL-EUR'] = copy.deepcopy(stop['markets']['BTC-EUR'])
                    write_frame(path, stop)
                    client.refresh()
                    await runtime.monitor()
                    assert (await repo.list_positions())[0].quantity == 0
                    assert len(await repo.list_fills()) == 2
                    assert await repo.verify_invariants(D(500)) == []
                    assert (await lab.scope(record['experiment_id'])).manifest == manifest
                    output['accounts'].append({'generation': generation, 'strategy': strategy,
                        'manifest': manifest, 'runtime': compatibility(manifest), 'fills': await repo.list_fills(),
                        'position': asdict((await repo.list_positions())[0]), 'reconciliation': [], 'duplicate_fill': False})
                    await feed.close()
                    if generation == 'v42':
                        await runtime.legacy().close()
                    elif generation == 'v44':
                        await runtime.frozen_v44().close()
            assert not await official.list_orders() and (await official.snapshot())['equity'] == '500.000000000000'
        finally:
            if builder is not lab:
                await builder.close()
            await lab.close()
            await engine.dispose()
    output['status'] = 'PASS'
    print(json.dumps(output, default=str))


if __name__ == '__main__':
    asyncio.run(main())
