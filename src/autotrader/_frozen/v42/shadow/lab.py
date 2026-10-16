from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from autotrader.domain import utc_now
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.models import (
    AccountModel,
    FillModel,
    ShadowExperimentModel,
    ShadowIdentityModel,
)
from autotrader.persistence.repository import PersistentTradingRepository, _json
from autotrader.research.artifacts import source_fingerprint
from autotrader.research.data import canonical, digest
from autotrader.research.experimental import EXPERIMENTAL_REGISTRY
from autotrader.research.strategies import REGISTRY, StrategyParameters
from autotrader.shadow.repository import ShadowScope, ShadowTradingRepository

log = logging.getLogger(__name__)
D = Decimal
PRESETS = {s.strategy_id: s for s in (*REGISTRY, *EXPERIMENTAL_REGISTRY) if not s.filter_only}
MAX_EXPERIMENTS = 4


class ShadowLab:
    def __init__(self, official: PersistentTradingRepository, settings: Any):
        if official.account_id != "paper-eur":
            raise ValueError("shadow_registry_requires_official_context")
        self.official, self.settings = official, settings
        self._opened: dict[str, tuple[Any, ShadowTradingRepository]] = {}
        self._provision_lock = asyncio.Lock()

    async def records(self) -> list[dict[str, Any]]:
        async with self.official.session_factory() as session:
            rows = (
                await session.scalars(
                    select(ShadowExperimentModel).order_by(ShadowExperimentModel.created_at)
                )
            ).all()
            return [
                {
                    "experiment_id": r.experiment_id,
                    "name": r.name,
                    "state": r.state,
                    "created_at": r.created_at.isoformat(),
                    "manifest": json.loads(r.manifest_json),
                }
                for r in rows
            ]

    async def scope(self, experiment_id: str) -> ShadowScope:
        async with self.official.session_factory() as session:
            row = await session.get(ShadowExperimentModel, experiment_id)
            if not row:
                raise ValueError("unknown_shadow_experiment")
            manifest = json.loads(row.manifest_json)
            actual_official = self.official.session_factory.kw["bind"].url.database
            if manifest["official_database"] != actual_official:
                raise ValueError("restored_shadow_registry_requires_isolated_cluster_or_reviewed_mapping")
            return ShadowScope(row.database_name, row.manifest_json)

    async def repository(self, experiment_id: str) -> ShadowTradingRepository:
        scope = await self.scope(experiment_id)
        if experiment_id not in self._opened:
            settings = self.settings.model_copy(
                update={
                    "database_url": make_url(self.settings.database_url)
                    .set(database=scope.database_name)
                    .render_as_string(hide_password=False)
                }
            )
            engine = make_engine(settings)
            self._opened[experiment_id] = (
                engine,
                ShadowTradingRepository(make_session_factory(engine), scope),
            )
        repo = self._opened[experiment_id][1]
        if repo.scope != scope:
            raise ValueError("frozen_shadow_manifest_changed")
        async with repo.session_factory() as session:
            await repo._assert_scope(session)
        return repo

    async def create(self, request_id: str, name: str, strategy_id: str) -> dict[str, Any]:
        if not self.settings.shadow_enabled:
            raise ValueError("shadow_lab_disabled")
        spec = PRESETS.get(strategy_id)
        if spec is None:
            raise ValueError("unknown_or_filter_only_shadow_strategy")
        url = make_url(self.settings.database_url)
        if url.get_backend_name() != "postgresql":
            raise ValueError("shadow_requires_postgresql")
        kind = (
            "SYNTHETIC_ACCEPTANCE" if self.settings.environment == "test" else "LIVE_MARKET_SHADOW"
        )
        async with self._provision_lock:
            async with self.official.session_factory() as session, session.begin():
                await self.official._lock_account(session)
                existing = await session.scalar(
                    select(ShadowExperimentModel).where(
                        ShadowExperimentModel.request_id == request_id
                    )
                )
                if existing:
                    if (
                        existing.name != name
                        or json.loads(existing.manifest_json)["strategy_id"] != strategy_id
                    ):
                        raise ValueError("shadow_request_identity_conflict")
                    identity = existing.experiment_id
                else:
                    count = await session.scalar(
                        select(func.count()).select_from(ShadowExperimentModel)
                    )
                    if (count or 0) >= MAX_EXPERIMENTS:
                        raise ValueError(
                            "bounded_shadow_limit_reached_no_accounts_deleted_or_reset"
                        )
                    identity = uuid4().hex
                    database = (
                        "autotrader_shadow_" + digest((str(url.database) + identity).encode())[:32]
                    )
                    params = (
                        StrategyParameters(stop_atr=D(2), target_atr=D(2))
                        if strategy_id in {s.strategy_id for s in EXPERIMENTAL_REGISTRY}
                        else StrategyParameters()
                    )
                    manifest = {
                        "experiment_id": identity,
                        "database_name": database,
                        "official_database": url.database,
                        "strategy_id": strategy_id,
                        "strategy_version": spec.version,
                        "parameters": params.payload(),
                        "parameter_hash": digest(canonical(params.payload())),
                        "source_fingerprint": source_fingerprint()[0],
                        "fee_bps": str(self.settings.default_fee_bps),
                        "slippage_bps": str(self.settings.default_slippage_bps),
                        "initial_cash_eur": "500",
                        "data_kind": kind,
                        "frozen_at": utc_now().isoformat(),
                        "promotion_state": "UNVALIDATED_EXPERIMENT",
                        "minimum_prospective_days": 30,
                    }
                    session.add(
                        ShadowExperimentModel(
                            experiment_id=identity,
                            request_id=request_id,
                            name=name,
                            state="CREATING",
                            database_name=database,
                            manifest_json=_json(manifest),
                        )
                    )
            scope = await self.scope(identity)

            # CREATE DATABASE is outside a transaction. Registry is durable first;
            # retries resume the SAME domain and never re-fund an existing account.
            def provision() -> None:
                kwargs: dict[str, Any] = {
                    "dbname": url.database,
                    "user": url.username,
                    "password": url.password,
                    "host": url.host,
                    "port": url.port or 5432,
                }
                with psycopg.connect(**kwargs, autocommit=True) as conn:
                    # Serialize API/worker provisioning across processes too.
                    conn.execute("SELECT pg_advisory_lock(4211001)")
                    if not conn.execute(
                        "SELECT 1 FROM pg_database WHERE datname=%s", (scope.database_name,)
                    ).fetchone():
                        conn.execute(
                            sql.SQL("CREATE DATABASE {}").format(
                                sql.Identifier(scope.database_name)
                            )
                        )

            await asyncio.to_thread(provision)
            scoped = self.settings.model_copy(
                update={
                    "database_url": url.set(database=scope.database_name).render_as_string(
                        hide_password=False
                    )
                }
            )
            engine = make_engine(scoped)
            try:
                await create_schema(engine)
                factory = make_session_factory(engine)
                async with factory() as session, session.begin():
                    from sqlalchemy import text

                    await session.execute(text("SELECT pg_advisory_xact_lock(4211002)"))
                    marker = await session.get(ShadowIdentityModel, 1)
                    if not marker:
                        if await session.scalar(select(func.count()).select_from(AccountModel)):
                            raise ValueError("unmarked_shadow_database_contains_accounts")
                        session.add(
                            ShadowIdentityModel(
                                singleton=1,
                                manifest_hash=scope.identity_hash,
                                manifest_json=scope.manifest_json,
                            )
                        )
                    elif marker.manifest_hash != scope.identity_hash:
                        raise ValueError("shadow_database_identity_collision")
                repo = ShadowTradingRepository(factory, scope)
                await repo.initialize_portfolio(D(500))
                if await repo.verify_invariants(D(500)):
                    raise ValueError("shadow_initial_reconciliation_failed")
            finally:
                await engine.dispose()
            async with self.official.session_factory() as session, session.begin():
                await self.official._lock_account(session)
                row = cast(ShadowExperimentModel, await session.get(ShadowExperimentModel, identity))
                if row.state == "CREATING":
                    row.state = "SHADOW_ACTIVE"
            return await self.detail(identity)

    async def control(self, identity: str, action: str) -> dict[str, Any]:
        if action not in {"pause", "resume", "stop"}:
            raise ValueError("unknown_shadow_control")
        repo = await self.repository(identity)
        async with self.official.session_factory() as session, session.begin():
            await self.official._lock_account(session)
            row = cast(ShadowExperimentModel, await session.get(ShadowExperimentModel, identity))
            if row.state in {"CREATING", "STOPPED"}:
                raise ValueError("shadow_state_cannot_transition")
            await repo.set_control(action)
            row.state = {"resume": "SHADOW_ACTIVE", "pause": "PAUSED", "stop": "STOPPED"}[action]
        return await self.detail(identity)

    async def detail(self, identity: str) -> dict[str, Any]:
        record = next(r for r in await self.records() if r["experiment_id"] == identity)
        repo = await self.repository(identity)
        snapshot = await repo.snapshot()
        history = await repo.history()
        positions = await repo.list_positions()
        closed = [p.realized_pnl for p in positions if p.closed_at is not None]
        wins = [p for p in closed if p > 0]
        losses = [p for p in closed if p < 0]
        async with repo.session_factory() as session:
            fees = await session.scalar(select(func.coalesce(func.sum(FillModel.fee), 0)))
            drawdown = await session.scalar(
                text(
                    "SELECT COALESCE(MAX((peak-equity)/NULLIF(peak,0)),0) FROM (SELECT equity, MAX(equity) OVER (ORDER BY timestamp,created_at,snapshot_id ROWS UNBOUNDED PRECEDING) AS peak FROM equity_snapshots WHERE degraded=false) s"
                )
            )
        performance = {
            "closed_trades": len(closed),
            "win_rate": len(wins) / len(closed) if closed else None,
            "profit_factor": str(sum(wins) / -sum(losses)) if losses else None,
            "fees": str(fees),
            "max_drawdown": str(drawdown),
            "net_pnl": snapshot["total_net_pnl"],
            "average_winner": str(sum(wins) / len(wins)) if wins else None,
            "average_loser": str(sum(losses) / len(losses)) if losses else None,
            "expectancy": str(sum(closed) / len(closed)) if closed else None,
        }
        return {
            **record,
            "portfolio": snapshot,
            "history": history,
            "reconciliation": await repo.verify_invariants(D(500)),
            "account_id": repo.account_id,
            "source_matches": record["manifest"]["source_fingerprint"] == source_fingerprint()[0],
            "positions": [asdict(p) for p in positions],
            "orders": await repo.list_orders(),
            "fills": await repo.list_fills(),
            "targets": await repo.list_targets(),
            "performance": performance,
            "history_window_limit": 500,
            "warning": "UNVALIDATED: separate EUR500 virtual experiment; never official equity or strategy approval",
        }

    async def close(self) -> None:
        for engine, _ in self._opened.values():
            await engine.dispose()
        self._opened.clear()
