import asyncio
import json
from dataclasses import replace
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from autotrader.decision import DecisionEngine
from autotrader.domain import OrderStatus, OrderType, Side
from autotrader.persistence.models import AccountModel, JournalEventModel
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.portfolio import Portfolio
from autotrader.research.strategies import V4StrategyEngine
from autotrader.risk import RiskEngine, RiskLimits
from autotrader.shadow.repository import ShadowScope, ShadowTradingRepository
from autotrader.shadow.runtime import ShadowExecutionGateway
from test_v4_execution import PAIR, Boundary, book
from test_v4_regimes_strategies import features


async def enter(repo, key="entry"):
    f = replace(features(), timeframe="5m")
    f.metadata["best_ask"] = D(103)
    signals = V4StrategyEngine(enabled={"A_TREND_PULLBACK"}).generate(f)
    decision = DecisionEngine(RiskEngine(RiskLimits())).decide(
        PAIR, f, signals, Portfolio(D(500)), None
    )
    assert decision.accepted
    await repo.store_analysis(signals, None, decision)
    observation = book("102.99", "103")
    gateway = ShadowExecutionGateway(
        repo,
        market_data=Boundary(observation),
        risk_engine=RiskEngine(RiskLimits()),
        initial_cash=D(500),
        fee_bps=D(10),
        slippage_bps=D(8),
    )
    return await gateway.execute_entry_decision(PAIR, decision, observation, key), gateway


async def test_real_shadow_buy_partial_sell_restore_and_official_isolation(lab):
    first = await lab.create("one", "Original pullback", "A_TREND_PULLBACK")
    identity = first["experiment_id"]
    repo = await lab.repository(identity)
    result, gateway = await enter(repo)
    assert result.accepted
    position = (await repo.list_positions())[0]
    before = await repo.snapshot()
    sell = await gateway.execute_exit(
        PAIR,
        position.quantity / 2,
        book("110", "110.01"),
        "half",
        "manual",
        position_id=position.position_id,
    )
    assert sell.accepted and sell.order.side is Side.SELL
    assert D((await repo.snapshot())["realized_pnl"]) > 0
    assert await repo.verify_invariants(D(500)) == []
    await lab.close()
    recovered = await lab.repository(identity)
    assert (await recovered.list_positions())[
        0
    ].quantity == position.quantity - sell.order.filled_quantity
    assert D((await recovered.snapshot())["available_cash"]) > D(before["available_cash"])
    await recovered.initialize_portfolio(D(500))
    assert (await lab.create("one", "Original pullback", "A_TREND_PULLBACK"))[
        "experiment_id"
    ] == identity
    official = await lab.official.snapshot()
    assert official["equity"] == "500.000000000000" and official["positions"] == "0"
    assert await lab.official.verify_invariants(D(500)) == []
    async with lab.official.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(JournalEventModel)) == 1


async def test_domain_forgery_frozen_config_and_official_mistarget_are_rejected(lab):
    record = await lab.create("scope", "Scope", "A_TREND_PULLBACK")
    repo = await lab.repository(record["experiment_id"])
    with pytest.raises(ValueError, match="scope_mismatch"):
        ShadowTradingRepository(lab.official.session_factory, repo.scope)
    with pytest.raises(ValueError, match="isolated_repository"):
        ShadowExecutionGateway(lab.official)
    with pytest.raises(AttributeError):
        repo.account_id = "paper-eur"
    wrong = PersistentTradingRepository(repo.session_factory)
    with pytest.raises(ValueError, match="cannot_initialize_shadow"):
        await wrong.initialize_portfolio(D(500))
    async with repo.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(AccountModel)) == 1
    altered = json.loads(repo.scope.manifest_json)
    altered["strategy_id"] = "F_MEAN_REVERSION"
    forged = ShadowTradingRepository(
        repo.session_factory, ShadowScope(repo.scope.database_name, json.dumps(altered))
    )
    with pytest.raises(ValueError, match="marker_mismatch"):
        await forged.snapshot()
    # A direct BUY without an eligible frozen strategy/decision cannot evade admission.
    direct = await repo.submit_order(
        PAIR,
        Side.BUY,
        OrderType.MARKET,
        D(".5"),
        D(60),
        book("102.99", "103"),
        "forged",
        stop_loss=D(100),
        targets=[D(110)],
    )
    assert direct.status is OrderStatus.REJECTED
    assert direct.rejection_reason == "shadow_frozen_strategy_mismatch"
    assert D((await repo.snapshot())["equity"]) == 500


async def test_concurrent_retries_candle_dedup_and_pause_preserve_funding(lab):
    a, b = await asyncio.gather(
        lab.create("same", "Same", "A_TREND_PULLBACK"),
        lab.create("same", "Same", "A_TREND_PULLBACK"),
    )
    assert a["experiment_id"] == b["experiment_id"]
    repo = await lab.repository(a["experiment_id"])
    flags = await asyncio.gather(
        *(repo.claim_candle("BTC-EUR", "2026-10-16T01:00:00+00:00") for _ in range(4))
    )
    assert flags.count(True) == 1
    results = await asyncio.gather(enter(repo, "same-order"), enter(repo, "same-order"))
    assert all(r[0].accepted for r in results)
    assert len(await repo.list_fills()) == 1
    await lab.control(a["experiment_id"], "pause")
    denied, _ = await enter(repo, "paused")
    assert not denied.accepted and "paused" in denied.reason
    await lab.control(a["experiment_id"], "resume")
    assert await repo.verify_invariants(D(500)) == []


async def test_independent_experiments_reject_foreign_exits_and_rollback_then_recover(
    lab, monkeypatch
):
    a = await lab.create("a", "A", "A_TREND_PULLBACK")
    b = await lab.create("b", "B", "A_TREND_PULLBACK")
    first = await lab.repository(a["experiment_id"])
    second = await lab.repository(b["experiment_id"])
    original = first._journal

    def fail_posting(session, key, kind, **kwargs):
        original(session, key, kind, **kwargs)
        if kind == "BUY_FILL":
            raise RuntimeError("injected_shadow_posting_rollback")

    monkeypatch.setattr(first, "_journal", fail_posting)
    with pytest.raises(RuntimeError, match="injected_shadow_posting_rollback"):
        await enter(first, "stable")
    assert not await first.list_fills()
    assert await first.verify_invariants(D(500)) == []
    monkeypatch.setattr(first, "_journal", original)
    await first.recover_pending_orders()
    assert len(await first.list_fills()) == 1
    other, gateway = await enter(second, "stable")
    assert other.accepted
    foreign = (await first.list_positions())[0]
    denied = await gateway.execute_exit(
        PAIR,
        foreign.quantity,
        book("110", "110.01"),
        "foreign",
        "manual",
        position_id=foreign.position_id,
    )
    assert not denied.accepted and denied.reason == "position_not_open"
    assert (await second.list_positions())[0].quantity == other.order.filled_quantity
    assert await first.verify_invariants(D(500)) == await second.verify_invariants(D(500)) == []
    assert D((await lab.official.snapshot())["equity"]) == 500


async def test_shadow_losses_halt_entries_and_frozen_registry_cannot_be_retargeted(lab):
    from sqlalchemy import text

    record = await lab.create("risk", "Risk", "A_TREND_PULLBACK")
    repo = await lab.repository(record["experiment_id"])
    result, _ = await enter(repo)
    assert result.accepted
    await repo.record_mark(book("50", "50.01"))
    snapshot = await repo.snapshot()
    assert snapshot["risk_state"] != "HEALTHY"
    denied, _ = await enter(repo, "halted")
    assert not denied.accepted and "runtime_not_healthy" in denied.reason
    assert await repo.verify_invariants(D(500)) == []
    with pytest.raises(Exception, match="configuration is frozen"):
        async with lab.official.session_factory() as session, session.begin():
            await session.execute(
                text("UPDATE shadow_experiments SET manifest_json='{}' WHERE experiment_id=:id"),
                {"id": record["experiment_id"]},
            )
    with pytest.raises(Exception, match="identity is immutable"):
        async with repo.session_factory() as session, session.begin():
            await session.execute(text("DELETE FROM shadow_identity"))
    assert D((await lab.official.snapshot())["equity"]) == 500


async def test_restored_foreign_registry_and_changed_source_fail_closed(lab, monkeypatch):
    from uuid import uuid4

    from autotrader.persistence.models import ShadowExperimentModel

    record = await lab.create("frozen", "Frozen", "A_TREND_PULLBACK")
    repo = await lab.repository(record["experiment_id"])
    manifest = dict(record["manifest"])
    identity = uuid4().hex
    database = "autotrader_shadow_" + uuid4().hex
    manifest.update(
        experiment_id=identity,
        database_name=database,
        official_database="foreign_original_database",
    )
    async with lab.official.session_factory() as session, session.begin():
        session.add(
            ShadowExperimentModel(
                experiment_id=identity,
                request_id="restored",
                name="Restored registry",
                state="CREATING",
                database_name=database,
                manifest_json=json.dumps(manifest),
            )
        )
    with pytest.raises(ValueError, match="restored_shadow_registry"):
        await lab.repository(identity)
    monkeypatch.setattr("autotrader.shadow.repository.execution_fingerprint", lambda: "changed")
    result, _ = await enter(repo, "changed-source")
    assert not result.accepted and result.reason == "shadow_frozen_source_changed"
    assert D((await repo.snapshot())["equity"]) == 500
    assert D((await lab.official.snapshot())["equity"]) == 500


async def test_unavailable_shadow_domain_does_not_suppress_other_protection(lab, monkeypatch):
    from autotrader.market_data.service import MarketDataService
    from autotrader.persistence.models import SystemStateModel
    from autotrader.shadow.runtime import ShadowRuntime

    broken = await lab.create("broken-domain", "Broken", "A_TREND_PULLBACK")
    good = await lab.create("healthy-domain", "Healthy", "A_TREND_PULLBACK")
    actual = lab.repository

    async def resolve(identity):
        if identity == broken["experiment_id"]:
            raise ValueError("injected_domain_unavailable")
        return await actual(identity)

    monkeypatch.setattr(lab, "repository", resolve)
    runtime = ShadowRuntime(
        lab, MarketDataService(None), RiskEngine(RiskLimits()), "isolation-test-owner"
    )
    await runtime.renew()
    await runtime.monitor()
    good_repo = await actual(good["experiment_id"])
    async with good_repo.session_factory() as session:
        assert await session.get(SystemStateModel, "worker") is not None
    assert await good_repo.verify_invariants(D(500)) == []
    assert D((await lab.official.snapshot())["equity"]) == 500
