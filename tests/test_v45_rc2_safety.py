"""Real PostgreSQL refusal/trace tests and complete backup-set fail-closed tests."""
import copy
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from autotrader.risk import RiskEngine, RiskLimits
from autotrader.shadow import trace, versions
from autotrader.shadow.runtime import ShadowRuntime
from test_v4_execution import PAIR, Boundary, book
from test_v4_regimes_strategies import features


@pytest.mark.parametrize('failure,expected', [
    ('cost', 'first_target_destroyed_by_execution_costs'),
    ('stale', 'stale_order_book'),
    ('risk', 'allocated_capital'),
])
async def test_original_v44_refusal_is_exact_durable_and_never_a_fill(lab, failure, expected):
    old = lambda name: versions.frozen_module(name, 'v44')
    original = old('shadow.lab').ShadowLab(old('persistence.repository').PersistentTradingRepository(lab.official.session_factory), lab.settings)
    runtime = ShadowRuntime(lab, Boundary(book('102.99', '103')), RiskEngine(RiskLimits()), 'refusal')
    try:
        record = await original.create('refusal', 'Synthetic refusal', 'A_TREND_PULLBACK')
        repo = await runtime.frozen_v44().lab.repository(record['experiment_id'])
        f = replace(versions.convert(features(), selected='v44'), timeframe='5m')
        f.metadata['best_ask'] = D(103)
        signals = old('research.strategies').V4StrategyEngine(enabled={'A_TREND_PULLBACK'}).generate(f)
        risk = old('risk').RiskEngine(old('risk').RiskLimits())
        decision = old('decision').DecisionEngine(risk).decide(versions.convert(PAIR, selected='v44'), f, signals, old('portfolio').Portfolio(D(500)), None)
        assert decision.accepted
        observation = versions.convert(book('102.99', '103'), selected='v44')
        if failure == 'cost':
            decision = replace(decision, take_profit_targets=(D('103.01'), D('103.02'), D('103.03')))
        elif failure == 'stale':
            observation = replace(observation, timestamp=observation.timestamp-timedelta(seconds=120))
        else:
            decision = replace(decision, proposed_quote_amount=D(1000))
        await repo.store_market_analysis([], f, observation)
        await repo.store_analysis(signals, None, decision)
        gateway = runtime.frozen_v44().runtime.gateway(repo)
        result = await gateway.execute_entry_decision(versions.convert(PAIR, selected='v44'), decision, observation, 'invalid-'+failure)
        assert not result.accepted and expected in result.reason
        assert not await repo.list_fills()
        assert await repo.verify_invariants(D(500)) == []
        from autotrader.persistence.models import SystemStateModel
        async with repo.session_factory() as session:
            row = await session.get(SystemStateModel, trace.key(decision.decision_id))
        body = json.loads(row.payload_json)
        event = body['events']['ENTRY_PREFLIGHT']
        assert event['status'] == 'REJECTED' and event['reason'] == result.reason
        assert len(row.key) <= 64 and len(row.state) <= 32
        assert trace.stage_states(body)['ORDER_FILLED'] == 'NEVER_REACHED'
    finally:
        await original.close()


async def test_trace_dedup_attempted_exception_and_unknown_history(lab):
    record = await lab.create('trace', 'Synthetic trace', 'A2_CONFIRMED_PULLBACK')
    repo = await lab.repository(record['experiment_id'])
    await trace.event(repo, 'decision', 'ENTRY_PREFLIGHT', 'ATTEMPTED')
    from autotrader.persistence.models import SystemStateModel
    async with repo.session_factory() as session:
        first = json.loads((await session.get(SystemStateModel, trace.key('decision'))).payload_json)
    assert trace.stage_states(first)['ENTRY_PREFLIGHT'] == 'OUTCOME_UNAVAILABLE'
    await trace.event(repo, 'decision', 'ENTRY_PREFLIGHT', 'EXCEPTION', reason='TimeoutError')
    await trace.event(repo, 'decision', 'ENTRY_PREFLIGHT', 'ATTEMPTED')
    async with repo.session_factory() as session:
        body = json.loads((await session.get(SystemStateModel, trace.key('decision'))).payload_json)
    assert len(body['events']) == 1
    assert body['events']['ENTRY_PREFLIGHT']['entered_at'] == first['events']['ENTRY_PREFLIGHT']['entered_at']
    assert trace.stage_states(body)['ENTRY_PREFLIGHT'] == 'EXCEPTION'
    assert set(trace.stage_states(None).values()) == {'NOT_RECORDED'}


async def test_telemetry_serialization_failure_is_visible_without_funding_or_orders(lab, monkeypatch):
    record = await lab.create('trace-failure', 'Synthetic telemetry outage', 'A2_CONFIRMED_PULLBACK')
    repo = await lab.repository(record['experiment_id'])
    def fail(*args):
        raise RuntimeError('deterministic_observer_serialization_failure')
    monkeypatch.setattr(trace, '_json', fail)
    await trace.event(repo, 'accepted-buy', 'ENTRY_PREFLIGHT', 'ATTEMPTED')
    from autotrader.persistence.models import SystemStateModel
    async with repo.session_factory() as session:
        assert (await session.get(SystemStateModel, 'execution_trace_health')).state == 'ERROR'
        assert await session.get(SystemStateModel, trace.key('accepted-buy')) is None
    assert not await repo.list_orders() and not await repo.list_fills()
    assert await repo.verify_invariants(D(500)) == []


def backup_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location('financial_set', Path('deploy/financial_set.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('mutation', ['missing', 'creating', 'database_collision', 'manifest', 'duplicate'])
def test_all_nine_backup_inventory_fails_closed(mutation):
    inventory = json.loads(Path('docs/evidence/v4_5_rc2/production-before.json').read_text())
    records = [{'database': r['database_name'], 'account_id': 'paper-eur' if r['identity']=='official' else 'shadow:'+r['identity'],
                'state': r['state'], 'manifest': r['manifest'], 'manifest_hash': r['manifest_hash']} for r in inventory['accounts']]
    module = backup_module()
    module.validate_inventory(records)
    changed = copy.deepcopy(records)
    if mutation == 'missing':
        changed.pop()
    elif mutation == 'creating':
        changed[-1]['state'] = 'CREATING'
    elif mutation == 'database_collision':
        changed[-1]['database'] = changed[-2]['database']
    elif mutation == 'manifest':
        changed[-1]['manifest']['fee_bps'] = '0'
    else:
        changed.append(changed[-1])
    with pytest.raises(ValueError):
        module.validate_inventory(changed)


def test_execution_exception_is_an_attempt_not_a_quality_refusal():
    from autotrader.shadow.gates import aggregate, first_blocker
    row = {'decision_accepted': True, 'trace_execution_state': 'EXCEPTION', 'action': 'BUY'}
    assert first_blocker(row) == 'execution:system_exception'
    counts = aggregate([row])['counts']
    assert counts['execution_attempts'] == 1 and counts['execution_exceptions'] == 1
    assert counts['execution_refusals'] == 0


def test_release_activation_requires_complete_hash_bound_passed_evidence(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location('release', Path('deploy/release.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(FileNotFoundError):
        module.verify_release_preflight(tmp_path)
    root = tmp_path/'docs/evidence/v4_5_rc2'
    root.mkdir(parents=True)
    (root/'deployment-readiness.json').write_text('{"recommendation":"READY","engineering_evidence":{}}')
    with pytest.raises(ValueError, match='incomplete'):
        module.verify_release_preflight(tmp_path)
