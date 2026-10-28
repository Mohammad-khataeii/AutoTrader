"""Shadow evaluation consumes the official scanner's shared observations."""

import logging
from dataclasses import replace
from decimal import Decimal
from typing import Any, cast

logger = logging.getLogger(__name__)

from autotrader.decision import DecisionEngine
from autotrader.execution_gateway import PaperExecutionGateway
from autotrader.portfolio import Portfolio
from autotrader.position_manager import PositionManager
from autotrader.research.context import completed_context
from autotrader.research.data import digest
from autotrader.research.experimental import VERSION, ExperimentalStrategyEngine
from autotrader.research.strategies import StrategyParameters, V4StrategyEngine
from autotrader.scanner import ScanCandidate
from autotrader.shadow.lab import ShadowLab
from autotrader.shadow.repository import ShadowTradingRepository
from autotrader.shadow.versions import CURRENT_RUNTIME, LEGACY_SOURCE, V44_EXECUTION, compatibility


class ShadowExecutionGateway(PaperExecutionGateway):
    def __init__(self, repository: ShadowTradingRepository, **kwargs: Any):
        if (
            not isinstance(repository, ShadowTradingRepository)
            or repository.account_id == "paper-eur"
        ):
            raise ValueError("shadow_gateway_requires_isolated_repository")
        super().__init__(repository, **kwargs)


class ShadowRuntime:
    def __init__(self, lab: ShadowLab, market_data: Any, risk: Any, owner: str):
        self.lab, self.market_data, self.risk, self.owner = lab, market_data, risk, owner
        self._legacy: Any = None
        self._v44: Any = None

    def legacy(self) -> Any:
        if self._legacy is None:
            from autotrader.shadow.legacy import LegacyRunner
            self._legacy = LegacyRunner(self.lab, self.market_data, self.risk, self.owner)
            self.lab._legacy_runner = self._legacy
        return self._legacy

    def frozen_v44(self) -> Any:
        if self._v44 is None:
            from autotrader.shadow.frozen import FrozenV44Runner
            self._v44 = FrozenV44Runner(self.lab, self.market_data, self.risk, self.owner)
            self.lab._v44_runner = self._v44
        return self._v44

    @staticmethod
    def pinned_v44(record: dict[str, Any]) -> bool:
        return bool(record["manifest"].get("execution_fingerprint") == V44_EXECUTION)

    @staticmethod
    def pinned_legacy(record: dict[str, Any]) -> bool:
        return bool(not record["manifest"].get("execution_fingerprint") and record["manifest"]["source_fingerprint"] == LEGACY_SOURCE)

    def gateway(self, repo: ShadowTradingRepository) -> ShadowExecutionGateway:
        from autotrader.shadow.diagnostics import observe_gateway
        if compatibility(repo.scope.manifest)["runner"] != CURRENT_RUNTIME or not compatibility(repo.scope.manifest)["compatible"]:
            raise ValueError("frozen_runtime_mismatch")
        return cast(ShadowExecutionGateway, observe_gateway(ShadowExecutionGateway(
            repo,
            market_data=self.market_data,
            risk_engine=self.risk,
            initial_cash=Decimal(500),
            fee_bps=Decimal(repo.scope.manifest["fee_bps"]),
            slippage_bps=Decimal(repo.scope.manifest["slippage_bps"]),
            allocation_profile=self.lab.settings.allocation_profile,
        ), repo))

    async def _operate_frozen(self, method: str) -> None:
        from autotrader.shadow.trace import runtime_incident
        records = await self.lab.records()
        for predicate, factory in ((self.pinned_legacy, self.legacy), (self.pinned_v44, self.frozen_v44)):
            selected = [r for r in records if predicate(r) and not r.get("archived_at") and r["state"] != "CREATING"]
            if not selected:
                continue
            try:
                await getattr(factory(), method)()
            except Exception as exc:
                logger.exception("frozen_runtime_operation_failed", extra={"phase": method})
                for record in selected:
                    try:
                        await runtime_incident(await self.lab.repository(record["experiment_id"]), method, type(exc).__name__)
                    except Exception:
                        logger.exception("frozen_runtime_incident_unavailable")

    async def renew(self) -> None:
        await self._operate_frozen("renew")
        for record in await self.lab.records():
            if record["state"] == "CREATING" or record.get("archived_at") or self.pinned_legacy(record) or self.pinned_v44(record):
                continue
            try:
                repo = await self.lab.repository(record["experiment_id"])
                await repo.claim_coordinator(self.owner)
            except Exception:
                logger.exception(
                    "shadow_renewal_unavailable", extra={"experiment_id": record["experiment_id"]}
                )

    async def monitor(self) -> None:
        await self._operate_frozen("monitor")
        for record in await self.lab.records():
            if record["state"] == "CREATING" or record.get("archived_at") or self.pinned_legacy(record) or self.pinned_v44(record):
                continue
            try:
                repo = await self.lab.repository(record["experiment_id"])
                if not await repo.claim_coordinator(self.owner):
                    continue
                if not compatibility(record["manifest"])["compatible"]:
                    from autotrader.shadow.trace import runtime_incident
                    await runtime_incident(repo, "position_monitor", "frozen_runtime_mismatch")
                    continue
                await repo.recover_pending_orders()
                await PositionManager(
                    repository=repo,
                    market_data=self.market_data,
                    execution_gateway=self.gateway(repo),
                ).monitor_once()
                await repo.snapshot()
                await repo.worker_heartbeat()
                from autotrader.shadow.trace import recover_traces
                await recover_traces(repo)
            except Exception:
                logger.exception(
                    "shadow_protection_unavailable",
                    extra={"experiment_id": record["experiment_id"]},
                )

    async def scan(self, candidates: list[ScanCandidate], *, successors_only: bool = False) -> None:
        from autotrader.opportunity.engine import VERSION as SUCCESSOR_VERSION
        from autotrader.shadow.views import record_reconciliation
        records = [r for r in await self.lab.records() if not successors_only or r['manifest']['strategy_version'] in {SUCCESSOR_VERSION, '4.9.0-raoe.1'}]
        if not successors_only:
            await record_reconciliation(self.lab.official)
        for record in records:
            if record["state"] != "CREATING" and not record.get("archived_at"):
                try:
                    await record_reconciliation(await self.lab.repository(record["experiment_id"]))
                except Exception:
                    logger.exception("shadow_reconciliation_observation_failed")
        for record in records:
            if record["state"] != "SHADOW_ACTIVE" or record.get("archived_at"):
                continue
            selected = candidates if record['manifest']['strategy_version'] in {SUCCESSOR_VERSION, '4.9.0-raoe.1'} else [c for c in candidates if not c.features.metadata.get('successor_discovery_only')]
            observation: dict[str, Any] = {"discovered_candidates": len(candidates), "evaluated": 0, "skips": []}
            observed_repo: Any = None
            try:
                observed_repo = await self.lab.repository(record["experiment_id"])
                status = compatibility(record["manifest"])
                if not status["compatible"]:
                    from autotrader.shadow.trace import runtime_incident
                    await runtime_incident(observed_repo, "scan", "frozen_runtime_mismatch")
                    observation["skips"].append({"stage": "runtime_identity", "reasons": ["frozen_runtime_mismatch"], "detail": status["reason"]})
                    continue
                if self.pinned_legacy(record):
                    observed_repo = await self.legacy().lab.repository(record["experiment_id"])
                elif self.pinned_v44(record):
                    observed_repo = await self.frozen_v44().lab.repository(record["experiment_id"])
                observed_repo._diagnostic_scan = observation
                if self.pinned_legacy(record):
                    await self.legacy().scan(record, selected)
                elif self.pinned_v44(record):
                    await self.frozen_v44().scan(record, selected)
                else:
                    await self._scan_experiment(record, selected, {c.features.symbol: c.features for c in selected})
            except Exception as exc:
                observation["exception"] = type(exc).__name__
                if observed_repo is not None:
                    from autotrader.shadow.trace import runtime_incident
                    await runtime_incident(observed_repo, "scan", type(exc).__name__)
                logger.exception(
                    "shadow_scan_unavailable", extra={"experiment_id": record["experiment_id"]}
                )
            finally:
                if observed_repo is not None:
                    from autotrader.domain import utc_now
                    from autotrader.shadow.diagnostics import record_scan
                    observation["completed_at"] = utc_now().isoformat()
                    await record_scan(observed_repo, observation)

    async def _scan_experiment(self, record: dict[str, Any], candidates: list[ScanCandidate], context: dict[str, Any]) -> None:
        repo = await self.lab.repository(record["experiment_id"])
        from autotrader.shadow.diagnostics import observe_repository
        observe_repository(repo, CURRENT_RUNTIME)
        if not await repo.claim_coordinator(self.owner):
            return
        from autotrader.opportunity.engine import VERSION as SUCCESSOR_VERSION
        if record['manifest']['strategy_version'] in {SUCCESSOR_VERSION, '4.9.0-raoe.1'}:
            from autotrader.opportunity.runtime import scan_successor
            await scan_successor(self, repo, record['manifest'], candidates)
            return
        repo._diagnostic_benchmarks = {k: v for k, v in context.items() if k in {"BTC-EUR", "ETH-EUR"}}  # type: ignore[attr-defined]
        m = record["manifest"]
        parameters = StrategyParameters(**{k: Decimal(v) for k, v in m["parameters"].items()})
        engine = (
            ExperimentalStrategyEngine(parameters, {m["strategy_id"]})
            if m["strategy_version"] == VERSION
            else V4StrategyEngine(parameters, {m["strategy_id"]})
        )
        for candidate in sorted(candidates, key=lambda c: (-c.score, c.market.pair.symbol)):
            if m["data_kind"] == "LIVE_MARKET_SHADOW" and (
                not candidate.market.order_book.source.startswith("revolut-x")
                or any(not c.source.startswith("revolut-x") for c in candidate.market.candles)
            ):
                raise ValueError("live_shadow_rejects_non_live_observations")
            f = replace(candidate.features, metadata=dict(candidate.features.metadata))
            if not await repo.claim_candle(f.symbol, f.timestamp.isoformat()):
                continue
            f.metadata["experimental_context"] = completed_context(
                candidate.market.candles, candidate.market.order_book.timestamp
            )
            signals = engine.generate(f, context.get("BTC-EUR"), context.get("ETH-EUR"))
            await repo.record_mark(candidate.market.order_book)
            snapshot = await repo.snapshot()
            portfolio = Portfolio(Decimal(snapshot["available_cash"]))
            portfolio.balances["EUR"].reserved = Decimal(snapshot["reserved_cash"])
            portfolio.positions = {
                p.symbol: p
                for p in await repo.list_positions()
                if p.closed_at is None and p.quantity > 0
            }
            decision = DecisionEngine(self.risk).decide(
                candidate.market.pair, f, signals, portfolio, None
            )
            await repo.store_market_analysis(
                candidate.market.candles, f, candidate.market.order_book
            )
            await repo.store_analysis(signals, None, decision)
            shadow_candidate = replace(
                candidate,
                features=f,
                signals=signals,
                decision=decision,
                score=sum((s.score for s in signals), Decimal(0)),
            )
            gateway = self.gateway(repo)
            allocated, _ = await gateway.allocate_candidate(shadow_candidate)
            if allocated is not None:
                await gateway.execute_entry_decision(
                    candidate.market.pair,
                    allocated,
                    candidate.market.order_book,
                    "shadow:"
                    + digest(
                        (
                            m["experiment_id"] + ":" + f.symbol + ":" + f.timestamp.isoformat()
                        ).encode()
                    )[:56],
                )
