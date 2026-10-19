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
from autotrader.shadow.versions import LEGACY_SOURCE


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

    def legacy(self) -> Any:
        if self._legacy is None:
            from autotrader.shadow.legacy import LegacyRunner
            self._legacy = LegacyRunner(self.lab, self.market_data, self.risk, self.owner)
            self.lab._legacy_runner = self._legacy
        return self._legacy

    @staticmethod
    def pinned_legacy(record: dict[str, Any]) -> bool:
        return not record["manifest"].get("execution_fingerprint") and record["manifest"]["source_fingerprint"] == LEGACY_SOURCE

    def gateway(self, repo: ShadowTradingRepository) -> ShadowExecutionGateway:
        from autotrader.shadow.diagnostics import observe_gateway
        return cast(ShadowExecutionGateway, observe_gateway(ShadowExecutionGateway(
            repo,
            market_data=self.market_data,
            risk_engine=self.risk,
            initial_cash=Decimal(500),
            fee_bps=Decimal(repo.scope.manifest["fee_bps"]),
            slippage_bps=Decimal(repo.scope.manifest["slippage_bps"]),
            allocation_profile=self.lab.settings.allocation_profile,
        ), repo))

    async def renew(self) -> None:
        if any(self.pinned_legacy(r) and not r.get("archived_at") for r in await self.lab.records()):
            await self.legacy().renew()
        for record in await self.lab.records():
            if record["state"] == "CREATING" or record.get("archived_at") or self.pinned_legacy(record):
                continue
            try:
                repo = await self.lab.repository(record["experiment_id"])
                await repo.claim_coordinator(self.owner)
            except Exception:
                logger.exception(
                    "shadow_renewal_unavailable", extra={"experiment_id": record["experiment_id"]}
                )

    async def monitor(self) -> None:
        if any(self.pinned_legacy(r) and not r.get("archived_at") for r in await self.lab.records()):
            await self.legacy().monitor()
        for record in await self.lab.records():
            if record["state"] == "CREATING" or record.get("archived_at") or self.pinned_legacy(record):
                continue
            try:
                repo = await self.lab.repository(record["experiment_id"])
                if not await repo.claim_coordinator(self.owner):
                    continue
                await repo.recover_pending_orders()
                await PositionManager(
                    repository=repo,
                    market_data=self.market_data,
                    execution_gateway=self.gateway(repo),
                ).monitor_once()
                await repo.snapshot()
                await repo.worker_heartbeat()
            except Exception:
                logger.exception(
                    "shadow_protection_unavailable",
                    extra={"experiment_id": record["experiment_id"]},
                )

    async def scan(self, candidates: list[ScanCandidate]) -> None:
        from autotrader.shadow.views import record_reconciliation
        await record_reconciliation(self.lab.official)
        for record in await self.lab.records():
            if record["state"] != "CREATING" and not record.get("archived_at"):
                try:
                    await record_reconciliation(await self.lab.repository(record["experiment_id"]))
                except Exception:
                    logger.exception("shadow_reconciliation_observation_failed")
        context = {c.features.symbol: c.features for c in candidates}
        for record in await self.lab.records():
            if record["state"] != "SHADOW_ACTIVE" or record.get("archived_at"):
                continue
            try:
                if self.pinned_legacy(record):
                    await self.legacy().scan(record, candidates)
                else:
                    await self._scan_experiment(record, candidates, context)
            except Exception:
                logger.exception(
                    "shadow_scan_unavailable", extra={"experiment_id": record["experiment_id"]}
                )

    async def _scan_experiment(self, record: dict[str, Any], candidates: list[ScanCandidate], context: dict[str, Any]) -> None:
        repo = await self.lab.repository(record["experiment_id"])
        from autotrader.shadow.diagnostics import observe_repository
        observe_repository(repo, "native-v44")
        if not await repo.claim_coordinator(self.owner):
            return
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
