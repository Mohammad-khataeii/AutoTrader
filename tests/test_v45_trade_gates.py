"""Deterministic execution acceptance; these tests are not performance evidence."""
import json
from dataclasses import replace
from decimal import Decimal as D

import pytest

from autotrader.domain import OrderStatus, utc_now
from autotrader.indicators import calculate_features
from autotrader.market_data.replay import FileReplayClient
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.models import OrderModel, SystemStateModel
from autotrader.research.context import completed_context
from autotrader.risk import RiskEngine, RiskLimits
from autotrader.scanner import ScanCandidate
from autotrader.shadow.diagnostics import explain
from autotrader.shadow.gates import aggregate, first_blocker
from autotrader.shadow.runtime import ShadowRuntime
from autotrader.shadow.versions import convert, legacy_module
from autotrader.shadow.views import page
from process_support import write_frame
from test_v4_execution import PAIR
from test_v42_lifecycle import experimental_frame


@pytest.mark.parametrize('strategy', ['A2_CONFIRMED_PULLBACK', 'B2_CONFIRMED_COMPRESSION'])
async def test_frozen_completed_setup_through_bridge_allocation_order_fill_and_dedup(lab, tmp_path, strategy):
    frame = experimental_frame('v45-liveness', D('129.4'))
    if strategy.startswith('B2'):
        for market in frame['markets'].values():
            market['candles'][-2].update(close='129.3', high='129.6', volume='2500')
            market['candles'][-1].update(open='129.3', close='129.4', high='129.7', low='129.0', volume='2000')
    path = tmp_path / 'frame.json'
    write_frame(path, frame)
    feed = MarketDataService(FileReplayClient(str(path)), candle_lookback=720)
    old = legacy_module('persistence.repository').PersistentTradingRepository(lab.official.session_factory)
    frozen = legacy_module('shadow.lab').ShadowLab(old, lab.settings)
    runtime = ShadowRuntime(lab, feed, RiskEngine(RiskLimits()), 'v45-test')
    try:
        record = await frozen.create('v45-' + strategy, 'Deterministic acceptance', strategy)
        pairs = await feed.discover_pairs()
        market = await feed.get_validated_market(pairs[0])
        assert market.usable_for_entry
        f = calculate_features(market.candles[-240:], market.metrics.imbalance, market.metrics.spread_bps)
        # Deliberately corrupt incoming computed indicators. Bridge must reconstruct raw data.
        candidate = ScanCandidate(market, replace(f, ema_9=D(0), ema_21=D(0)), [], None, None, D(0))
        await runtime.scan([candidate])
        repo = await lab.repository(record['experiment_id'])
        assert len(await repo.list_fills()) == 1
        assert await repo.verify_invariants(D(500)) == []
        stored = await page(repo, 'decisions')
        assert stored['items'][0]['accepted']
        explanation = stored['items'][0]['explanation']
        assert explanation['diagnostic_parity'] is True
        assert explanation['allocation']['accepted'] is True
        assert explanation['execution']['stage'] == 'entry'
        assert explanation['final_state'] == 'ACCEPTED'
        await runtime.scan([candidate])
        assert len(await repo.list_fills()) == 1
        assert (await page(repo, 'decisions'))['items'][0]['decision_id'] == stored['items'][0]['decision_id']
        assert (await lab.official.snapshot())['equity'] == '500.000000000000'
        # Use independently computed frozen features and context for signal parity.
        original = legacy_module('indicators').calculate_features(convert(market.candles[-240:]), market.metrics.imbalance, market.metrics.spread_bps)
        original.metadata['experimental_context'] = legacy_module('research.context').completed_context(convert(market.candles), market.order_book.timestamp)
        signals = legacy_module('research.experimental').ExperimentalStrategyEngine(enabled={strategy}).generate(original, original, original)
        assert next(s for s in signals if s.strategy_id == strategy).evidence['entry_eligible']
    finally:
        await frozen.close()
        await lab.close()
        await feed.close()


def test_attribution_overlapping_failures_veto_and_unreached_stages():
    row = {'schema': 'shadow-decision-explanation/2', 'symbol': 'BTC-EUR', 'signal_entry_eligible': False,
           'decision_accepted': False, 'independently_failed': ['higher_timeframe_bullish', 'breakout_volume'],
           'momentum_veto': True, 'diagnostic_parity': True,
           'momentum_components': {'adverse_regime': True}, 'data_quality': 'GOOD'}
    assert first_blocker(row) == 'strategy:higher_timeframe_bullish'
    result = aggregate([row])
    assert result['counts']['execution_attempts'] == 0
    assert result['momentum_components']['adverse_regime']['otherwise_eligible'] == 0
    assert result['pairwise_intersections']['breakout_volume & higher_timeframe_bullish'] == 1
    assert first_blocker({**row, 'signal_entry_eligible': True}) == 'momentum_veto'
    assert first_blocker({**row, 'diagnostic_parity': False}) == 'strategy_unresolved_diagnostic_mismatch'
    assert first_blocker({'reason': 'Entry conditions not met.'}) == 'unknown'


async def test_order_history_excludes_live_orders_and_partial_ioc_is_terminal(pg_repo):
    async with pg_repo.session_factory() as session, session.begin():
        for status in OrderStatus:
            session.add(OrderModel(order_id=status.value, client_order_id=status.value,
                                  symbol=PAIR.symbol, side='BUY', order_type='MARKET', status=status.value,
                                  quantity=D(1), quote_amount=D(1), filled_quantity=D(0)))
    opened = await page(pg_repo, 'orders', status='open')
    closed = await page(pg_repo, 'orders', status='history')
    assert {r['status'] for r in opened['items']} == {'PENDING', 'ACCEPTED'}
    assert not {'PENDING', 'ACCEPTED'} & {r['status'] for r in closed['items']}
    assert 'PARTIALLY_FILLED' in {r['status'] for r in closed['items']}


async def test_missing_higher_context_and_bearish_inputs_remain_rejected(tmp_path):
    frame = experimental_frame('bad-context', D('129.1'))
    path = tmp_path / 'frame.json'
    write_frame(path, frame)
    candles = await FileReplayClient(str(path)).get_candles('BTC-EUR', 5, 0, 0)
    f = calculate_features(candles[-240:], D(0), D(1))
    f.metadata['experimental_context'] = completed_context(candles[-240:], utc_now())
    engine = legacy_module('research.experimental').ExperimentalStrategyEngine()
    assert not any(s.evidence['entry_eligible'] for s in engine.generate(convert(f)))
    f.metadata['experimental_context'] = completed_context(candles, utc_now())
    f.metadata['experimental_context']['60m']['bull'] = False
    f.metadata['experimental_context']['60m']['bear'] = True
    signals = engine.generate(convert(f))
    signal = next(s for s in signals if s.strategy_id == 'A2_CONFIRMED_PULLBACK')
    assert signal.evidence['entry_eligible'] is False
    # No explanations should convert absent context to healthy eligibility.
    from autotrader.decision import DecisionEngine
    from autotrader.portfolio import Portfolio
    decision = DecisionEngine(RiskEngine(RiskLimits())).decide(PAIR, f, convert(signals, False), Portfolio(D(500)), None)
    explanation = explain(f, convert(signals, False), decision,
                          {'strategy_id':'A2_CONFIRMED_PULLBACK', 'strategy_version':'test',
                           'source_fingerprint':'test','parameters':{}}, 'verified-v42')
    assert explanation['diagnostic_parity'] is True
    assert 'higher_timeframe_bullish' in explanation['independently_failed']


async def test_scan_exception_is_visible_without_changing_experiment_or_financials(lab, monkeypatch):
    record = await lab.create('failure', 'Observed failure', 'B2_CONFIRMED_COMPRESSION')
    runtime = ShadowRuntime(lab, None, RiskEngine(RiskLimits()), 'observer')
    async def fail(*args):
        raise RuntimeError('sanitized test exception')
    monkeypatch.setattr(runtime, '_scan_experiment', fail)
    await runtime.scan([])
    repo = await lab.repository(record['experiment_id'])
    async with repo.session_factory() as session:
        row = await session.get(SystemStateModel, 'shadow_scan_observation')
        assert row.state == 'ERROR'
        assert json.loads(row.payload_json)['exception'] == 'RuntimeError'
    assert (await lab.records())[0]['state'] == 'SHADOW_ACTIVE'
    assert not await repo.list_fills()
    assert await repo.verify_invariants(D(500)) == []


async def test_authenticated_paginated_gate_api_joins_allocation_without_inventing_execution(lab, monkeypatch):
    import asyncio

    from fastapi.testclient import TestClient

    from autotrader.api.main import create_app
    from autotrader.persistence.models import TradingDecisionModel

    record = await lab.create('api-gates', 'Page evidence', 'A2_CONFIRMED_PULLBACK')
    repo = await lab.repository(record['experiment_id'])
    async with repo.session_factory() as session, session.begin():
        for i in range(3):
            session.add(TradingDecisionModel(decision_id='old-buy-'+str(i), symbol='ETH-EUR',
                                            action='BUY', accepted=True, payload_json='{}'))
            session.add(SystemStateModel(key='alloc:old-buy-'+str(i), state='ACCEPTED',
                                         reason='portfolio_allocation',payload_json='{"accepted":true,"reasons":[]}'))
    monkeypatch.setenv('DATABASE_URL', lab.official.test_database_url)
    monkeypatch.setenv('ENVIRONMENT', 'test')
    monkeypatch.setenv('SHADOW_ENABLED', 'true')
    monkeypatch.setenv('DASHBOARD_PASSWORD', 'change-me')

    def browser():
        with TestClient(create_app()) as client:
            url = '/api/trade-gates/' + record['experiment_id'] + '?limit=2'
            assert client.get(url).status_code == 401
            response = client.get(url, auth=('admin','change-me'))
            assert response.status_code == 200
            data = response.json()
            assert len(data['decisions']) == 2 and data['next_cursor']
            assert data['counts']['accepted_buy_decisions'] == 2
            assert data['counts']['allocation_attempts'] == 2
            assert data['counts']['execution_attempts'] == 0
            assert data['window']['unannotated'] == 2
            assert data['lifetime_financial_counts']['paper_fills'] == 0
            second = client.get(url + '&cursor=' + data['next_cursor'], auth=('admin','change-me')).json()
            assert len(second['decisions']) == 1
            assert client.delete('/api/shadow/'+record['experiment_id']+'?confirm='+record['experiment_id'], auth=('admin','change-me')).json()['detail'] == 'archiving_disabled_during_v45_investigation'
    await asyncio.to_thread(browser)


def test_legacy_bridge_tampering_and_diagnostic_code_are_in_integrity_closure(tmp_path, monkeypatch):
    import shutil

    from autotrader.shadow import versions
    baseline = versions.execution_fingerprint()
    shutil.copytree(versions.ROOT, tmp_path / 'package')
    monkeypatch.setattr(versions, 'ROOT', tmp_path / 'package')
    assert versions.execution_fingerprint() == baseline
    versions.verify_boundary()
    (versions.ROOT / 'shadow/diagnostics.py').write_text('# changed wrapper\n')
    assert versions.execution_fingerprint() != baseline
    with pytest.raises(ValueError, match='boundary_integrity'):
        versions.verify_boundary()
    assert versions.compatibility({'source_fingerprint': versions.LEGACY_SOURCE})['compatible'] is False
