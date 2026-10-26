"""Isolated deterministic engineering evidence, never prospective returns."""
import asyncio
import json
import os
from dataclasses import replace
from decimal import Decimal as D

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import func, select

from autotrader.config import Settings
from autotrader.domain import OrderStatus, OrderType, Side
from autotrader.indicators import calculate_features
from autotrader.market_data.replay import FileReplayClient
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.models import JournalEventModel, OrderModel, ShadowIdentityModel
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.personal_paper.policy import ACCOUNT, INITIAL
from autotrader.personal_paper.runtime import PersonalPaperRuntime
from autotrader.personal_paper.service import PersonalPaperService
from autotrader.scanner import ScanCandidate
from v46_support import successor_frame


@pytest.fixture
async def paper(pg_repo):
    await pg_repo.initialize_portfolio(D(500))
    settings = Settings(database_url=pg_repo.test_database_url, environment='test',
        personal_paper_enabled=True, _env_file=None)
    service = PersonalPaperService(pg_repo, settings)
    repo = await service.ensure()
    yield service, repo
    name = repo.manifest['database_name']
    await service.close()
    def drop():
        with psycopg.connect(os.environ['AUTOTRADER_TEST_PG_ADMIN_URL'], autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
    await asyncio.to_thread(drop)


async def candidates_for(path, frame):
    path.write_text(json.dumps(frame))
    market = MarketDataService(FileReplayClient(str(path)), candle_lookback=720)
    candidates = []
    for pair in await market.discover_pairs():
        data = await market.get_validated_market(pair)
        features = calculate_features(data.candles[-240:], data.metrics.imbalance, data.metrics.spread_bps)
        candidates.append(ScanCandidate(data, features, [], None, None, D(1)))
    return market, candidates


async def test_single_funding_scope_official_isolation_and_reopen(paper, pg_repo):
    service, repo = paper
    await service.ensure()
    assert (await repo.snapshot())['initial_cash'] == '7000'
    assert D((await repo.snapshot())['equity']) == 7000
    assert D((await pg_repo.snapshot())['equity']) == 500
    async with repo.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(JournalEventModel).where(JournalEventModel.event_type=='INITIAL_FUNDING')) == 1
        assert await session.get(ShadowIdentityModel, 1)
    await service.close()
    repo = await service.repository()
    assert repo.account_id == ACCOUNT and await repo.verify_invariants(INITIAL) == []
    with pytest.raises(ValueError, match='official_repository_cannot_initialize'):
        await PersistentTradingRepository(repo.session_factory).initialize_portfolio(D(500))
    with pytest.raises(ValueError):
        await repo.initialize_portfolio(D(500))


@pytest.mark.parametrize('strategy', ['A3_COST_AWARE_CONTINUATION', 'B3_STATEFUL_BREAKOUT', 'E3_ADAPTIVE_RELATIVE_STRENGTH'])
async def test_ranked_buy_partial_target_stop_and_restart(paper, pg_repo, tmp_path, strategy):
    service, repo = paper
    market, candidates = await candidates_for(tmp_path/'frame.json', successor_frame(strategy))
    runtime = PersonalPaperRuntime(service, market, 'paper-test')
    try:
        await runtime.scan(candidates)
        fills = await repo.list_fills()
        assert fills, (await service.detail())['scan']
        assert all(f['simulated'] == 'True' for f in fills)
        assert all(p.account_id==ACCOUNT for p in await repo.list_positions())
        assert D((await repo.snapshot())['available_cash']) >= 2800
        assert await repo.verify_invariants(INITIAL) == []
        count = len(fills)
        await runtime.scan(candidates)
        assert len(await repo.list_fills()) == count
        # Reopen repository and replay the same completed observation.
        await service.close()
        repo = await service.repository()
        await runtime.scan(candidates)
        assert len(await repo.list_fills()) == count
        position = next(p for p in await repo.list_positions() if p.quantity>0)
        assert position.expires_at is not None
        assert 10800 <= (position.expires_at-position.opened_at).total_seconds() < 10801
        candidate = next(c for c in candidates if c.market.pair.symbol==position.symbol)
        from autotrader.domain import OrderBook, OrderBookLevel, utc_now
        target = position.take_profit_targets[0]*D('1.02')
        book = OrderBook(position.symbol, utc_now(), (OrderBookLevel(target,D(10000)),), (OrderBookLevel(target+D('.01'),D(10000)),), 'replay:SYNTHETIC-V47')
        gateway = runtime.gateway(repo)
        partial = await gateway.execute_exit(candidate.market.pair, position.target_quantities[0], book, 'paper-partial', 'take_profit_target', position_id=position.position_id, exit_target_id=position.target_ids[0])
        assert partial.accepted
        await repo.sync_exit_plan_from_fills(position.symbol)
        position = next(p for p in await repo.list_positions() if p.position_id==position.position_id)
        assert 0<position.quantity<position.original_quantity
        exit_book = replace(book, bids=(OrderBookLevel(position.protective_stop*D('.99'),D(10000)),), asks=(OrderBookLevel(position.protective_stop*D('.99')+D('.01'),D(10000)),))
        class ExitFeed:
            async def resolve_pair(self, symbol):return next(c.market.pair for c in candidates if c.features.symbol==symbol)
            async def get_position_book(self, pair):return replace(exit_book,symbol=pair.symbol)
        from autotrader.position_manager import PositionManager
        actions = await PositionManager(repository=repo,market_data=ExitFeed(),execution_gateway=gateway).monitor_once()
        assert any(a.reason=='protective_stop' for a in actions)
        assert await repo.verify_invariants(INITIAL) == []
        detail = await service.detail()
        assert detail['performance']['sell_fills'] >= 2
        from autotrader.api.paper_analytics import attributed_summary
        from autotrader.personal_paper.policy import VERSION
        attributed=await attributed_summary(service)
        assert all(o['execution_profile']==VERSION for o in attributed['orders'] if o['side']=='SELL' and o['status'] in {'FILLED','PARTIALLY_FILLED'})
        from autotrader.api.paper_activity import activity_feed
        feed = await activity_feed(service)
        assert feed['read_only'] is True and feed['evidence_category'] == 'SYNTHETIC_ACCEPTANCE'
        assert {'BUY', 'SELL'} <= {e['side'] for e in feed['events'] if e['kind'] == 'FILL'}
        assert all(e['order_id'] for e in feed['events'] if e['kind'] == 'FILL')
        assert any(e['accepted'] and e['order_id'] for e in feed['evaluations'])
        assert len({e['id'] for e in feed['events']}) == len(feed['events'])
        assert D(7000)-D(attributed['cash_flow']['spent_on_buys_eur'])+D(attributed['cash_flow']['sale_proceeds_eur']) == D(detail['portfolio']['cash'])
        assert D(detail['performance']['fees_eur'])>0
        assert len(await pg_repo.list_orders()) == 0
        assert D((await pg_repo.snapshot())['equity']) == 500
    finally:
        await market.close()


async def test_activity_readmodel_keeps_rejected_orders_separate_from_fills(paper, tmp_path):
    from autotrader.api.paper_activity import activity_feed
    service, repo = paper
    market, candidates = await candidates_for(tmp_path/'rejected-feed.json', successor_frame('A3_COST_AWARE_CONTINUATION'))
    try:
        c = candidates[0]
        order = await repo.submit_order(c.market.pair, Side.BUY, OrderType.MARKET, D(1), D(150),
            c.market.order_book, 'feed-rejection', stop_loss=D(120), targets=[D(140), D(145), D(150)])
        assert order.status is OrderStatus.REJECTED
        before = await repo.snapshot()
        first = await activity_feed(service)
        await service.close()
        second = await activity_feed(service)
        assert first['events'] == second['events']
        assert first['events'][0]['kind'] == 'ORDER'
        assert first['events'][0]['status'] == 'REJECTED'
        assert not any(e['kind'] == 'FILL' for e in first['events'])
        assert first['evaluations'] == []
        repo = await service.repository()
        after = await repo.snapshot()
        assert all(before[k] == after[k] for k in ['equity', 'available_cash', 'reserved_cash', 'orders'])
        assert await repo.verify_invariants(INITIAL) == []
    finally:
        await market.close()


async def test_prospective_rejects_replay_before_any_financial_entry(paper, tmp_path):
    service, repo = paper
    repo.manifest['data_kind'] = 'REVOLUT_X_PROSPECTIVE_PAPER'
    # This directly tests the source boundary before any scope/financial mutation.
    market, candidates = await candidates_for(tmp_path/'frame.json', successor_frame('A3_COST_AWARE_CONTINUATION'))
    try:
        runtime = PersonalPaperRuntime(service, market, 'x')
        # Scope tamper must also fail closed, never silently change history.
        with pytest.raises(ValueError, match='identity_mismatch'):
            await runtime.scan(candidates)
        assert not await repo.list_orders()
    finally:
        await market.close()


async def test_unapproved_or_changed_manifest_rejected(paper):
    _service, repo = paper
    async with repo.session_factory() as session:
        assert await repo._entry_policy_error(session,'UNKNOWN',{},D(10),D(8)) == 'paper_strategy_not_authorized_for_manifest'
    repo.manifest['risk_limits']['max_position_size'] = '7000'
    with pytest.raises(ValueError, match='identity_mismatch'):
        await repo.snapshot()


async def test_no_cash_can_be_spent_twice_and_pending_reservations_reconcile(paper, tmp_path):
    service, repo = paper
    market, candidates = await candidates_for(tmp_path/'frame.json',successor_frame('A3_COST_AWARE_CONTINUATION'))
    runtime = PersonalPaperRuntime(service,market,'risk-test')
    try:
        await runtime.scan(candidates)
        p = next(p for p in await repo.list_positions() if p.quantity>0)
        c = next(c for c in candidates if c.market.pair.symbol==p.symbol)
        # A second independent intent for the same asset must be rejected under
        # the ledger lock even when multiple strategies competed above it.
        results = await asyncio.gather(*(repo.submit_order(c.market.pair,Side.BUY,OrderType.MARKET,D(1),D(150),c.market.order_book,'duplicate-'+str(i),stop_loss=D(120),targets=[D(140),D(145),D(150)]) for i in range(2)))
        assert all(r.status is OrderStatus.REJECTED for r in results)
        assert await repo.verify_invariants(INITIAL) == []
        async with repo.session_factory() as session:
            assert not (await session.scalars(select(OrderModel).where(OrderModel.status.in_(['PENDING','ACCEPTED'])))).all()
    finally:
        await market.close()


async def test_genuine_manifest_refuses_synthetic_market_input(pg_repo, tmp_path):
    await pg_repo.initialize_portfolio(D(500))
    service = PersonalPaperService(pg_repo, Settings(database_url=pg_repo.test_database_url,
        environment='local', personal_paper_enabled=True, _env_file=None))
    repo = await service.ensure()
    market, candidates = await candidates_for(tmp_path/'synthetic.json',successor_frame('A3_COST_AWARE_CONTINUATION'))
    try:
        assert repo.manifest['data_kind']=='REVOLUT_X_PROSPECTIVE_PAPER'
        with pytest.raises(ValueError,match='prospective_paper_rejects_synthetic'):
            await PersonalPaperRuntime(service,market,'source-test').scan(candidates)
        assert not await repo.list_orders()
        assert await repo.verify_invariants(INITIAL)==[]
    finally:
        await market.close();await service.close()
        with psycopg.connect(os.environ['AUTOTRADER_TEST_PG_ADMIN_URL'],autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(repo.manifest['database_name'])))


async def test_committed_reservation_recovers_without_duplicate_funding_or_buy(paper,tmp_path,monkeypatch):
    service,repo=paper
    market,candidates=await candidates_for(tmp_path/'crash.json',successor_frame('A3_COST_AWARE_CONTINUATION'))
    runtime=PersonalPaperRuntime(service,market,'crash-test')
    from autotrader.persistence import accounting
    original=accounting.failpoint
    def interruption(name):
        if name=='after_reservation_persistence':raise RuntimeError('synthetic_crash_after_reservation')
        return original(name)
    try:
        with monkeypatch.context() as fault:
            fault.setattr(accounting,'failpoint',interruption)
            with pytest.raises(RuntimeError,match='synthetic_crash'):
                await runtime.scan(candidates)
        before=await repo.snapshot()
        assert D(before['reserved_cash'])>0 and not await repo.list_fills()
        assert await repo.verify_invariants(INITIAL)==[]
        await service.close();repo=await service.repository()
        await repo.claim_coordinator('crash-test')
        await repo.recover_pending_orders()
        await runtime.scan(candidates)
        count=len(await repo.list_fills())
        assert count>0 and D((await repo.snapshot())['reserved_cash'])==0
        await runtime.scan(candidates)
        assert len(await repo.list_fills())==count and await repo.verify_invariants(INITIAL)==[]
    finally:await market.close()


async def test_actual_worker_opens_protects_and_recovers_primary_portfolio(paper, pg_repo, tmp_path, monkeypatch):
    _service,repo=paper
    from process_support import WorkerProcess, wait_for, write_frame
    monkeypatch.setenv('PERSONAL_PAPER_ENABLED','true')
    monkeypatch.setenv('SHADOW_ENABLED','true')
    path=tmp_path/'worker.json'
    frame=successor_frame('A3_COST_AWARE_CONTINUATION')
    write_frame(path,frame)
    worker=WorkerProcess(pg_repo.test_database_url,path,execution_costs=('10','8'))
    try:
        await worker.wait_started(pg_repo)
        async def opened():
            if await pg_repo.last_worker_frame() != frame['frame_id']:
                return None
            return await repo.list_fills() or None
        await wait_for(opened,worker=worker)
        positions=[p for p in await repo.list_positions() if p.quantity>0]
        assert positions and D((await repo.snapshot())['reserved_cash'])==0
        first_count=len(await repo.list_fills())
        worker.kill()
        worker=WorkerProcess(pg_repo.test_database_url,path,execution_costs=('10','8'))
        await worker.wait_started(pg_repo)
        assert len(await repo.list_fills())==first_count
        # A fresh observed gap below every entry stop reaches the real worker's
        # independent protection path. No synthetic rows are posted directly.
        stop_frame=successor_frame('A3_COST_AWARE_CONTINUATION')
        stop_frame['frame_id']='synthetic-worker-stop'
        for market in stop_frame['markets'].values():
            market['book']['bids']=[['110','1000']]
            market['book']['asks']=[['110.01','1000']]
        write_frame(path,stop_frame)
        async def closed():
            return all(p.quantity==0 for p in await repo.list_positions())
        await wait_for(closed,worker=worker)
        assert any(f['side']=='SELL' for f in await repo.list_fills())
        assert await repo.verify_invariants(INITIAL)==[]
        assert len(await pg_repo.list_orders())==0
        async with repo.session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(JournalEventModel).where(JournalEventModel.event_type=='INITIAL_FUNDING'))==1
    finally:
        worker.kill()


async def test_readonly_attribution_does_not_change_execution_manifest(paper,tmp_path):
    from autotrader.api.paper_analytics import attributed_summary
    service,repo=paper
    manifest=json.dumps(repo.manifest,sort_keys=True)
    market,candidates=await candidates_for(tmp_path/'attribution.json',successor_frame('A3_COST_AWARE_CONTINUATION'))
    try:
        await PersonalPaperRuntime(service,market,'attribution').scan(candidates)
        before=await repo.verify_invariants(INITIAL)
        summary=await attributed_summary(service)
        assert sum(r['open_positions'] for r in summary['attribution']['asset'])==summary['performance']['open_positions']
        assert all(r['expectancy'] is None for r in summary['attribution']['strategy'])
        assert json.dumps(repo.manifest,sort_keys=True)==manifest
        assert await repo.verify_invariants(INITIAL)==before==[]
    finally:await market.close()


def test_mac_release_explicitly_blocks_vps_preflight(tmp_path):
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('v47_release',Path('deploy/release.py'))
    release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
    (tmp_path/'pyproject.toml').write_text('[project]\nversion="4.7.0.dev1"\n')
    with pytest.raises(ValueError,match='Mac-only.*VPS deployment is not authorized'):
        release.verify_release_preflight(tmp_path)
    assert release.allowed('docker-compose.mac.yml')


def test_backup_inventory_includes_and_validates_primary_identity():
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('v47_financial',Path('deploy/financial_set.py'))
    financial=importlib.util.module_from_spec(spec);spec.loader.exec_module(financial)
    m={'account_id':ACCOUNT,'initial_cash_eur':'7000','currency':'EUR','database_name':'autotrader_paper_'+'a'*32,'official_database':'autotrader','live_authorized':False}
    records=[{'account_id':'paper-eur','database':'autotrader','state':'OFFICIAL','manifest':None},
        {'account_id':ACCOUNT,'database':m['database_name'],'state':'PAPER_EXPERIMENTAL_ACTIVE','manifest':m,'manifest_hash':financial.manifest_hash(m)}]
    financial.validate_inventory(records,required=frozenset())
    m['initial_cash_eur']='14000';records[1]['manifest_hash']=financial.manifest_hash(m)
    with pytest.raises(ValueError,match='primary_paper_registry'):
        financial.validate_inventory(records,required=frozenset())


async def test_explicit_flat_revision_preserves_origin_orders_funding_and_uses_consumed_depth(pg_repo,tmp_path,monkeypatch):
    import autotrader.personal_paper.service as service_module
    from autotrader.personal_paper.policy import VERSION
    await pg_repo.initialize_portfolio(D(500))
    settings=Settings(database_url=pg_repo.test_database_url,environment='test',personal_paper_enabled=True,_env_file=None)
    service=PersonalPaperService(pg_repo,settings)
    with monkeypatch.context() as first:
        first.setattr(service_module,'VERSION','4.7.0-paper.1')
        old=await service.ensure()
    origin=json.dumps(old.manifest,sort_keys=True)
    market,candidates=await candidates_for(tmp_path/'wide-depth.json',successor_frame('A3_COST_AWARE_CONTINUATION'))
    try:
        c=candidates[0]
        rejected=await old.submit_order(c.market.pair,Side.BUY,OrderType.MARKET,D(1),D(150),c.market.order_book,'preserved-ineligible',stop_loss=D(120),targets=[D(140),D(145),D(150)])
        assert rejected.status is OrderStatus.REJECTED
        with pytest.raises(ValueError,match='pause_entries'):
            await service.create_runtime_revision('Synthetic test: reviewed depth-aware risk correction')
        await old.set_control('pause')
        repo=await service.create_runtime_revision('Synthetic test: reviewed depth-aware risk correction')
        assert repo.manifest['version']==VERSION
        assert json.dumps(repo.manifest['account_origin'],sort_keys=True)==origin
        assert (await repo.list_orders())[0]['order_id']==rejected.order_id
        await repo.set_control('resume')
        from autotrader.domain import OrderBookLevel
        # A remote ask above EUR1000 has no effect when the entire order can
        # execute at the EUR129 top level. It must not invent EUR1000 stop risk.
        wide=[]
        for c in candidates:
            book=replace(c.market.order_book,asks=(*c.market.order_book.asks,OrderBookLevel(D(1000),D(1000))))
            wide.append(replace(c,market=replace(c.market,order_book=book)))
        await PersonalPaperRuntime(service,market,'revision').scan(wide)
        assert await repo.list_fills()
        assert await repo.verify_invariants(INITIAL)==[]
        async with repo.session_factory() as session:
            marker=await session.get(ShadowIdentityModel,1)
            assert json.dumps(json.loads(marker.manifest_json),sort_keys=True)==origin
            assert await session.scalar(select(func.count()).select_from(JournalEventModel).where(JournalEventModel.event_type=='INITIAL_FUNDING'))==1
    finally:
        await market.close();await service.close()
        with psycopg.connect(os.environ['AUTOTRADER_TEST_PG_ADMIN_URL'],autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(old.manifest['database_name'])))


async def test_dashboard_chart_deduplicates_closed_candles_and_exposes_gaps(paper):
    from datetime import timedelta

    from autotrader.api.dashboard import account_assets, chart_data
    from autotrader.domain import utc_now
    from autotrader.persistence.models import MarketCandle
    service, repo = paper
    boundary = utc_now().replace(second=0, microsecond=0)
    async with repo.session_factory() as session, session.begin():
        for minute, close in [(30, 100), (30, 101), (20, 103), (10, 104), (0, 200)]:
            session.add(MarketCandle(symbol='BTC-EUR', timeframe='5m', timestamp=boundary-timedelta(minutes=minute),
                open=D(close-1), high=D(close+1), low=D(close-2), close=D(close), volume=D(100), source='replay:chart-test'))
    chart = await chart_data(service, 'BTC-EUR', '1h')
    assert [D(c['close']) for c in chart['candles']] == [101, 103, 104]
    assert chart['missing_intervals'] == 2
    assert chart['timeframe'] == '5m'
    assert (await chart_data(service, 'ETH-EUR', '1h'))['candles'] == []
    assets = await account_assets(repo)
    assert D(assets['cash_flow']['spent_on_buys_eur']) == 0
    assert assets['holdings'] == []
    assert await repo.verify_invariants(INITIAL) == []
