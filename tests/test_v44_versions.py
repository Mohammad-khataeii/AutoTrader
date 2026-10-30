from dataclasses import replace
from decimal import Decimal as D

import pytest

from autotrader.shadow.legacy import ObservationBoundary
from autotrader.shadow.versions import (
    LEGACY_SOURCE,
    compatibility,
    convert,
    legacy_module,
    verify_legacy,
)
from test_v4_execution import PAIR, Boundary, book
from test_v4_regimes_strategies import features


def test_frozen_bytes_and_independent_strategy_imports(monkeypatch):
    assert len(verify_legacy()) == 71
    old = legacy_module("research.experimental")
    from autotrader.research.experimental import ExperimentalStrategyEngine

    old_features = convert(features())
    expected = [
        (s.strategy_id, s.evidence) for s in old.ExperimentalStrategyEngine().generate(old_features)
    ]
    monkeypatch.setattr(
        ExperimentalStrategyEngine,
        "generate",
        lambda *args: (_ for _ in ()).throw(RuntimeError("changed native engine")),
    )
    assert [
        (s.strategy_id, s.evidence)
        for s in old.ExperimentalStrategyEngine().generate(convert(features()))
    ] == expected
    assert legacy_module("research.artifacts").source_fingerprint()[0] == LEGACY_SOURCE


async def test_actual_v42_account_enters_with_original_runner_without_manifest_rewrite(lab):
    old_repository = legacy_module("persistence.repository").PersistentTradingRepository(
        lab.official.session_factory
    )
    old_lab = legacy_module("shadow.lab").ShadowLab(old_repository, lab.settings)
    try:
        record = await old_lab.create("legacy-upgrade", "Frozen old account", "A_TREND_PULLBACK")
        manifest = record["manifest"]
        assert (
            manifest["source_fingerprint"] == LEGACY_SOURCE
            and "execution_fingerprint" not in manifest
        )
        assert compatibility(manifest)["compatible"]
        repo = await old_lab.repository(record["experiment_id"])
        risk_module = legacy_module("risk")
        risk = risk_module.RiskEngine(risk_module.RiskLimits())
        f = replace(convert(features()), timeframe="5m")
        f.metadata["best_ask"] = D(103)
        signals = (
            legacy_module("research.strategies")
            .V4StrategyEngine(enabled={"A_TREND_PULLBACK"})
            .generate(f)
        )
        decision = (
            legacy_module("decision")
            .DecisionEngine(risk)
            .decide(convert(PAIR), f, signals, legacy_module("portfolio").Portfolio(D(500)), None)
        )
        await repo.store_analysis(signals, None, decision)
        gateway = legacy_module("shadow.runtime").ShadowExecutionGateway(
            repo,
            market_data=ObservationBoundary(Boundary(book("102.99", "103"))),
            risk_engine=risk,
            initial_cash=D(500),
            fee_bps=D(10),
            slippage_bps=D(8),
        )
        result = await gateway.execute_entry_decision(
            convert(PAIR), decision, convert(book("102.99", "103")), "legacy-exact-order"
        )
        assert result.accepted
        assert await repo.verify_invariants(D(500)) == []
        current = await lab.detail(record["experiment_id"])
        assert (
            current["manifest"] == manifest
            and current["runtime_compatibility"]["runner"] == "verified-v42"
        )
        assert len(current["fills"]) == 1
        assert (await lab.official.snapshot())["equity"] == "500.000000000000"
    finally:
        await old_lab.close()


def test_tampered_legacy_source_fails_closed(tmp_path, monkeypatch):
    import shutil

    from autotrader.shadow import versions

    shutil.copytree(versions.FROZEN, tmp_path / "v42")
    shutil.copy(versions.FROZEN.parent / "v42-manifest.json", tmp_path / "v42-manifest.json")
    (tmp_path / "v42/research/experimental.py").write_text("# changed implementation\n")
    monkeypatch.setattr(versions, "FROZEN", tmp_path / "v42")
    with pytest.raises(ValueError, match="integrity_failed"):
        versions.verify_legacy()
    assert not compatibility({"source_fingerprint": LEGACY_SOURCE})["compatible"]


def test_api_changes_do_not_change_native_execution_identity(tmp_path, monkeypatch):
    import shutil

    from autotrader.shadow import versions

    original = versions.execution_fingerprint()
    for file in versions.ROOT.rglob("*.py"):
        if "_frozen" not in file.parts:
            target = tmp_path / file.relative_to(versions.ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(file, target)
    shutil.copy(versions.ROOT / "shadow/v45-boundary.json", tmp_path / "shadow/v45-boundary.json")
    shutil.copy(versions.ROOT / "shadow/v493-observation-bridge.json", tmp_path / "shadow/v493-observation-bridge.json")
    monkeypatch.setattr(versions, "ROOT", tmp_path)
    assert versions.execution_fingerprint() == original
    (tmp_path / "api/main.py").write_text("# API-only upgrade\n")
    assert versions.execution_fingerprint() == original
    (tmp_path / "research/experimental.py").write_text("# strategy change\n")
    assert versions.execution_fingerprint() != original


async def test_original_runtime_reads_upgrade_observations_without_financial_restore(lab):
    import json

    from autotrader.persistence.models import SystemStateModel
    from autotrader.shadow.views import record_reconciliation

    original = legacy_module("persistence.repository").PersistentTradingRepository(
        lab.official.session_factory
    )
    old_lab = legacy_module("shadow.lab").ShadowLab(original, lab.settings)
    try:
        record = await old_lab.create(
            "rollback-readable", "Original rollback domain", "B2_CONFIRMED_COMPRESSION"
        )
        repo = await lab.repository(record["experiment_id"])
        before = (await repo.history())["journal"]
        await record_reconciliation(repo)
        async with repo.session_factory() as session, session.begin():
            session.add(
                SystemStateModel(
                    key="shadow_explanation:rollback-test",
                    state="REJECTED",
                    reason="observation_only",
                    payload_json=json.dumps({"data_kind": "SYNTHETIC_ACCEPTANCE"}),
                )
            )
        restored = await old_lab.detail(record["experiment_id"])
        assert restored["source_matches"] and restored["manifest"] == record["manifest"]
        assert restored["history"]["journal"] == before
        assert restored["reconciliation"] == []
        assert len(await old_lab.records()) == 1
    finally:
        await old_lab.close()
