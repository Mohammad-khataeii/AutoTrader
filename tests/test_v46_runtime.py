import json
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from test_v42_lifecycle import (
    test_actual_experimental_worker_partial_targets_sigkill_restart_and_official_api as original_lifecycle,
)


async def test_a3_actual_worker_partial_exits_sigkill_recovery_and_official_isolation(lab, tmp_path, monkeypatch):
    import test_v42_lifecycle as old_fixture

    original = old_fixture.experimental_frame

    def wide_movement_fixture(*args, **kwargs):
        frame = original(*args, **kwargs)
        # Explicitly synthetic engineering observation: a larger higher-timeframe
        # movement budget supports the proposed targets. No parameter relaxation.
        for market in frame['markets'].values():
            for candle in market['candles'][:-2]:
                close = D(candle['close'])
                candle.update(high=str(close + D('1.5')), low=str(close - D('1.5')))
        return frame

    monkeypatch.setattr(old_fixture, 'experimental_frame', wide_movement_fixture)

    class SuccessorLab:
        def __getattr__(self, name):
            return getattr(lab, name)

        async def create(self, request_id, name, strategy):
            assert strategy == 'A2_CONFIRMED_PULLBACK'
            return await lab.create(request_id, 'SYNTHETIC A3 worker acceptance', 'A3_COST_AWARE_CONTINUATION')

    await original_lifecycle(SuccessorLab(), tmp_path, monkeypatch)
    record = (await lab.records())[0]
    assert record['manifest']['strategy_id'] == 'A3_COST_AWARE_CONTINUATION'
    repo = await lab.repository(record['experiment_id'])
    assert len(await repo.list_fills()) == 5 and await repo.verify_invariants(D(500)) == []


async def test_successor_resumes_exact_decision_after_gateway_exception_without_duplicate_fill(lab, tmp_path, monkeypatch):
    from autotrader.execution_gateway import PaperExecutionGateway
    from autotrader.indicators import calculate_features
    from autotrader.market_data.replay import FileReplayClient
    from autotrader.market_data.service import MarketDataService
    from autotrader.persistence.models import SystemStateModel, TradingDecisionModel
    from autotrader.risk import RiskEngine, RiskLimits
    from autotrader.scanner import ScanCandidate
    from autotrader.shadow.runtime import ShadowRuntime
    from autotrader.shadow.trace import key, stage_states
    from test_v42_lifecycle import experimental_frame

    frame = experimental_frame('SYNTHETIC-RECOVERY', D('129.1'))
    for market in frame['markets'].values():
        for candle in market['candles'][:-2]:
            close = D(candle['close']);candle.update(high=str(close+D('1.5')),low=str(close-D('1.5')))
    path = tmp_path/'recovery.json';path.write_text(json.dumps(frame))
    feed = MarketDataService(FileReplayClient(str(path)), candle_lookback=720)
    record = await lab.create('resumable-v46', 'SYNTHETIC recovery', 'A3_COST_AWARE_CONTINUATION')
    repo = await lab.repository(record['experiment_id'])
    runtime = ShadowRuntime(lab, feed, RiskEngine(RiskLimits()), 'recovery-owner')
    candidates = []
    for pair in await feed.discover_pairs():
        market = await feed.get_validated_market(pair)
        candidates.append(ScanCandidate(market, calculate_features(market.candles[-240:], market.metrics.imbalance, market.metrics.spread_bps), [], None, None, D(1)))
    async def unavailable(*args, **kwargs):
        raise RuntimeError('synthetic_gateway_interruption_before_order')
    try:
        with monkeypatch.context() as fault:
            fault.setattr(PaperExecutionGateway, 'execute_entry_decision', unavailable)
            await runtime.scan(candidates)
        assert not await repo.list_orders()
        async with repo.session_factory() as session:
            first = (await session.scalars(select(TradingDecisionModel))).one()
            original_id, original_payload = first.decision_id, first.payload_json
            assert stage_states(json.loads((await session.get(SystemStateModel, key(original_id))).payload_json))['ENTRY_PREFLIGHT'] == 'EXCEPTION'
        await runtime.scan(candidates)
        assert len(await repo.list_fills()) == 1
        await runtime.scan(candidates)
        assert len(await repo.list_fills()) == 1 and await repo.verify_invariants(D(500)) == []
        async with repo.session_factory() as session:
            assert (await session.get(TradingDecisionModel, original_id)).payload_json == original_payload
            trace = json.loads((await session.get(SystemStateModel, key(original_id))).payload_json)
            assert stage_states(trace)['ENTRY_PREFLIGHT'] == 'SUCCEEDED'
            assert len([e for e in trace['events'].values() if e['stage']=='ENTRY_PREFLIGHT']) == 2
    finally:
        await feed.close()


@pytest.mark.parametrize('strategy', ['A3_COST_AWARE_CONTINUATION', 'B3_STATEFUL_BREAKOUT', 'E3_ADAPTIVE_RELATIVE_STRENGTH'])
async def test_each_successor_actual_entry_dedup_protection_and_reconstructed_runner(lab, tmp_path, strategy):
    from autotrader.indicators import calculate_features
    from autotrader.market_data.replay import FileReplayClient
    from autotrader.market_data.service import MarketDataService
    from autotrader.risk import RiskEngine, RiskLimits
    from autotrader.scanner import ScanCandidate
    from autotrader.shadow.runtime import ShadowRuntime
    from test_v42_lifecycle import experimental_frame
    from v46_support import successor_frame

    frame = successor_frame(strategy)
    path = tmp_path/'successor.json';path.write_text(json.dumps(frame))
    feed = MarketDataService(FileReplayClient(str(path)), candle_lookback=720)
    record = await lab.create(strategy, 'SYNTHETIC V46 ' + strategy, strategy)
    repo = await lab.repository(record['experiment_id'])
    runtime = ShadowRuntime(lab, feed, RiskEngine(RiskLimits()), 'v46-lifecycle')
    candidates = []
    try:
        for pair in await feed.discover_pairs():
            m = await feed.get_validated_market(pair)
            candidates.append(ScanCandidate(m, calculate_features(m.candles[-240:],m.metrics.imbalance,m.metrics.spread_bps),[],None,None,D(1)))
        await runtime.scan(candidates)
        assert len(await repo.list_fills()) == 1
        await runtime.scan(candidates)
        assert len(await repo.list_fills()) == 1
        position = (await repo.list_positions())[0]
        assert position.protective_stop and len(await repo.list_targets(position.position_id)) == 3
        stop = experimental_frame('SYNTHETIC-V46-STOP', D(120))
        if strategy.startswith('E3'):
            stop['pairs'].append(frame['pairs'][-1]);stop['markets']['SOL-EUR'] = stop['markets']['BTC-EUR']
        path.write_text(json.dumps(stop));feed.client.refresh()
        await ShadowRuntime(lab, feed, RiskEngine(RiskLimits()), 'v46-lifecycle').monitor()
        assert (await repo.list_positions())[0].quantity == 0
        assert len(await repo.list_fills()) == 2 and await repo.verify_invariants(D(500)) == []
        assert (await lab.scope(record['experiment_id'])).manifest == record['manifest']
        assert not await lab.official.list_orders() and not await lab.official.list_fills()
    finally:
        await feed.close()
