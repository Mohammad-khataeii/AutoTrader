"""Synthetic engineering proof; no performance or prospective evidence."""
import copy
import json
import shutil
from dataclasses import replace
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from autotrader.indicators import calculate_features
from autotrader.market_data.replay import FileReplayClient
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.models import SystemStateModel
from autotrader.risk import RiskEngine, RiskLimits
from autotrader.scanner import ScanCandidate
from autotrader.shadow import versions
from autotrader.shadow.runtime import ShadowRuntime
from process_support import write_frame
from test_v42_lifecycle import experimental_frame


def test_v44_exact_original_algorithm_and_all_dependencies():
    assert len(versions.verify_legacy()) == 71
    assert len(versions.verify_v44()) == 76
    old = versions.frozen_module("shadow.versions", "v44")
    assert old.execution_fingerprint() == versions.V44_EXECUTION
    assert versions.compatibility({"execution_fingerprint": versions.V44_EXECUTION}) == {
        "compatible": True, "runner": "verified-v44", "reason": None}
    assert versions.compatibility({"execution_fingerprint": versions.execution_fingerprint()})["runner"] == "native-v45"
    assert not versions.compatibility({"execution_fingerprint": "unknown"})["compatible"]


@pytest.mark.parametrize("name", ["research/experimental.py", "shadow/repository.py", "research/artifacts.py"])
def test_v44_source_and_nonclosure_dependency_tamper_rejected(tmp_path, monkeypatch, name):
    shutil.copytree(versions.FROZEN_V44, tmp_path / "v44")
    shutil.copy(versions.FROZEN_V44.parent / "v44-manifest.json", tmp_path / "v44-manifest.json")
    (tmp_path / "v44" / name).write_text("# tampered\n")
    monkeypatch.setattr(versions, "FROZEN_V44", tmp_path / "v44")
    assert not versions.compatibility({"execution_fingerprint": versions.V44_EXECUTION})["compatible"]


@pytest.mark.parametrize("strategy", ["A2_CONFIRMED_PULLBACK", "B2_CONFIRMED_COMPRESSION", "C2_LIQUID_RETEST", "E2_ABSOLUTE_RELATIVE_STRENGTH"])
async def test_original_v44_admission_and_protective_exit_with_unchanged_manifest(lab, tmp_path, strategy, production_record=None):
    old = lambda name: versions.frozen_module(name, "v44")
    official = old("persistence.repository").PersistentTradingRepository(lab.official.session_factory)
    original = old("shadow.lab").ShadowLab(official, lab.settings)
    frame = experimental_frame("rc2-entry", D("129.4"))
    if strategy.startswith("B2"):
        for market in frame["markets"].values():
            market["candles"][-2].update(close="129.3", high="129.6", volume="2500")
            market["candles"][-1].update(open="129.3", close="129.4", high="129.7", low="129.0", volume="2000")
    if strategy.startswith("C2"):
        for market in frame["markets"].values():
            market["candles"][-2].update(open="128.8", close="129.4", high="129.5", volume="2500")
            market["candles"][-1].update(open="129.4", close="129.7", high="130.0", low="128.9", volume="2000")
            market["book"]["bids"] = [["129.7", "1000"]]
            market["book"]["asks"] = [["129.71", "1000"]]
    if strategy.startswith("E2"):
        frame["pairs"].append({**frame["pairs"][0], "symbol": "SOL-EUR", "base_asset": "SOL"})
        frame["markets"]["SOL-EUR"] = copy.deepcopy(frame["markets"]["BTC-EUR"])
        for i, candle in enumerate(frame["markets"]["SOL-EUR"]["candles"]):
            close = D(100) + D(i) * D(".04") + D(max(0, i-699)) * D(".23")
            candle.update(open=str(close-D(".1")), high=str(close+D("1.5")), low=str(close-D("1.5")), close=str(close), volume="2000" if i == 719 else "1000")
        frame["markets"]["SOL-EUR"]["book"]["bids"] = [["133.36", "1000"]]
        frame["markets"]["SOL-EUR"]["book"]["asks"] = [["133.37", "1000"]]
    path = tmp_path / "frame.json"
    write_frame(path, frame)
    class IsolatedProductionObservation(FileReplayClient):
        async def get_candles(self, *args, **kwargs):
            return [replace(c, source="revolut-x-SYNTHETIC-ISOLATED-FIXTURE") for c in await super().get_candles(*args, **kwargs)]
        async def get_order_book(self, *args, **kwargs):
            return replace(await super().get_order_book(*args, **kwargs), source="revolut-x-SYNTHETIC-ISOLATED-FIXTURE")
    client = IsolatedProductionObservation(str(path)) if production_record else FileReplayClient(str(path))
    feed = MarketDataService(client, candle_lookback=720)
    runtime = ShadowRuntime(lab, feed, RiskEngine(RiskLimits()), "rc2-test")
    try:
        record = production_record or await original.create("rc2-" + strategy, "Synthetic original V44", strategy)
        manifest = record["manifest"]
        assert manifest["execution_fingerprint"] == versions.V44_EXECUTION
        candidates = []
        for pair in await feed.discover_pairs():
            market = await feed.get_validated_market(pair)
            f = calculate_features(market.candles[-240:], market.metrics.imbalance, market.metrics.spread_bps)
            candidates.append(ScanCandidate(market, replace(f, ema_9=D(0), ema_21=D(0)), [], None, None, D(0)))
        await runtime.scan(candidates)
        repo = await lab.repository(record["experiment_id"])
        fills = await repo.list_fills()
        assert len(fills) == 1
        assert await repo.verify_invariants(D(500)) == []
        frozen_repo = await runtime.frozen_v44().lab.repository(record["experiment_id"])
        assert type(frozen_repo).__module__.startswith("autotrader._frozen.v44.")
        assert next(r for r in await lab.records() if r["experiment_id"] == record["experiment_id"])["manifest"] == manifest
        await runtime.scan(candidates)
        assert len(await repo.list_fills()) == 1
        position = (await repo.list_positions())[0]
        assert position.protective_stop and await repo.list_targets(position.position_id)
        # Recreate the runner with the same immutable account, then monitor a stop.
        await runtime.frozen_v44().close()
        runtime._v44 = None
        stop = experimental_frame("rc2-stop", D(127))
        if strategy.startswith("E2"):
            stop["pairs"].append(frame["pairs"][-1])
            stop["markets"]["SOL-EUR"] = copy.deepcopy(stop["markets"]["BTC-EUR"])
        write_frame(path, stop)
        feed.client.refresh()
        await runtime.monitor()
        assert (await repo.list_positions())[0].quantity == 0
        assert len(await repo.list_fills()) == 2
        assert await repo.verify_invariants(D(500)) == []
        async with repo.session_factory() as session:
            traces = (await session.scalars(select(SystemStateModel).where(SystemStateModel.key.like("trace:%")))).all()
        events = [e for t in traces for e in json.loads(t.payload_json)["events"].values()]
        assert {e["stage"] for e in events if e["status"] == "SUCCEEDED"} >= set(__import__('autotrader.shadow.trace', fromlist=['STAGES']).STAGES)
        assert (await lab.official.snapshot())["equity"] == "500.000000000000"
        from rc2_identity_support import evidence
        evidence((record["experiment_id"] if production_record else strategy) + "-lifecycle.json", {
            "status": "PASS", "manifest": manifest, "manifest_unchanged": True,
            "runner": type(frozen_repo).__module__, "parameters": manifest["parameters"],
            "fills": await repo.list_fills(), "orders": await repo.list_orders(),
            "positions": [str(p) for p in await repo.list_positions()], "reconciliation": [],
            "trace": [json.loads(t.payload_json) for t in traces], "original_accounts_mutated": False})
    finally:
        await original.close()
        await lab.close()
        await feed.close()


@pytest.mark.parametrize("strategy", ["A2_CONFIRMED_PULLBACK", "B2_CONFIRMED_COMPRESSION", "C2_LIQUID_RETEST", "E2_ABSOLUTE_RELATIVE_STRENGTH"])
async def test_exact_production_identities_all_four_native_lifecycles(tmp_path, monkeypatch, strategy):
    import socket

    from rc2_identity_support import identity_fixture
    async for lab in identity_fixture(monkeypatch):
        with socket.socket() as probe, pytest.raises(RuntimeError, match="outbound_network_refused"):
            probe.connect(("production.invalid", 5432))
        records = await lab.records()
        assert len(records) == 8 and sum(bool(r["archived_at"]) for r in records) == 4
        assert all(versions.compatibility(r["manifest"])["compatible"] for r in records)
        from autotrader.decision import DecisionEngine
        from autotrader.execution_gateway import PaperExecutionGateway
        from autotrader.research.experimental import ExperimentalStrategyEngine
        def native_code_forbidden(*args, **kwargs):
            raise AssertionError("V44 must never execute current financial logic")
        monkeypatch.setattr(DecisionEngine, "decide", native_code_forbidden)
        monkeypatch.setattr(ExperimentalStrategyEngine, "generate", native_code_forbidden)
        monkeypatch.setattr(PaperExecutionGateway, "execute_entry_decision", native_code_forbidden)
        record = next(r for r in records if r["state"] == "SHADOW_ACTIVE" and r["manifest"]["strategy_id"] == strategy)
        await test_original_v44_admission_and_protective_exit_with_unchanged_manifest(lab, tmp_path, strategy, record)
        after = await lab.records()
        assert [(r["experiment_id"], r["manifest"], r["state"], r["archived_at"]) for r in after] == [(r["experiment_id"], r["manifest"], r["state"], r["archived_at"]) for r in records]
        for retained in after:
            repo = await lab.repository(retained["experiment_id"])
            assert await repo.verify_invariants(D(500)) == []
            if retained["archived_at"]:
                assert not await repo.list_fills()


async def test_v44_actual_worker_partial_fill_sigkill_and_restart(lab, tmp_path, monkeypatch):
    from test_v42_lifecycle import (
        test_actual_experimental_worker_partial_targets_sigkill_restart_and_official_api,
    )
    old = lambda name: versions.frozen_module(name, "v44")
    official = old("persistence.repository").PersistentTradingRepository(lab.official.session_factory)
    official.test_database_url = lab.official.test_database_url
    original = old("shadow.lab").ShadowLab(official, lab.settings)
    try:
        await test_actual_experimental_worker_partial_targets_sigkill_restart_and_official_api(original, tmp_path, monkeypatch)
        record = (await lab.records())[0]
        assert record['manifest']['execution_fingerprint'] == versions.V44_EXECUTION
        repo = await lab.repository(record['experiment_id'])
        assert len(await repo.list_fills()) == 5
        from rc2_identity_support import evidence
        evidence("v44-worker-restart.json", {"status": "PASS", "manifest": record['manifest'],
            "fills": await repo.list_fills(), "reconciliation": [], "actual_worker_sigkill": True,
            "partial_target_survived": True})
    finally:
        await original.close()


async def test_v44_tampering_blocks_real_scan_monitor_and_wrong_native_gateway(lab, tmp_path, monkeypatch):
    old = lambda name: versions.frozen_module(name, 'v44')
    original = old('shadow.lab').ShadowLab(old('persistence.repository').PersistentTradingRepository(lab.official.session_factory), lab.settings)
    try:
        record = await original.create('tamper-proof', 'Synthetic frozen identity', 'A2_CONFIRMED_PULLBACK')
        repo = await lab.repository(record['experiment_id'])
        runtime = ShadowRuntime(lab, None, RiskEngine(RiskLimits()), 'tamper-test')
        with pytest.raises(ValueError, match='frozen_runtime_mismatch'):
            runtime.gateway(repo)
        shutil.copytree(versions.FROZEN_V44, tmp_path/'v44')
        shutil.copy(versions.FROZEN_V44.parent/'v44-manifest.json', tmp_path/'v44-manifest.json')
        (tmp_path/'v44/decision.py').write_text('# tampered fixture only\n')
        monkeypatch.setattr(versions, 'FROZEN_V44', tmp_path/'v44')
        await runtime.scan([])
        await runtime.monitor()
        assert not await repo.list_orders() and not await repo.list_fills()
        assert await repo.verify_invariants(D(500)) == []
        async with repo.session_factory() as session:
            incident = await session.get(SystemStateModel, 'shadow_runtime_incident')
            assert incident.state == 'ERROR'
        assert (await lab.scope(record['experiment_id'])).manifest == record['manifest']
    finally:
        await original.close()
