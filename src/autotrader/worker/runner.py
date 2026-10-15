from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from autotrader.ai import make_ai_provider
from autotrader.config import get_settings
from autotrader.decision import DecisionEngine
from autotrader.execution_gateway import ExecutionResult, PaperExecutionGateway
from autotrader.market_data.revolut import MarketDataError, RevolutXPublicClient
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.position_manager import PositionManager
from autotrader.risk import RiskEngine, RiskLimits
from autotrader.scanner import MarketScanner, ScanCandidate
from autotrader.strategies import BreakoutStrategyEngine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CandidateExecution:
    symbol: str
    accepted: bool
    reason: str
    order_id: str | None


async def execute_ranked_candidates(
    candidates: list[ScanCandidate],
    execution_gateway: PaperExecutionGateway,
    max_entries: int,
) -> list[CandidateExecution]:
    executions: list[CandidateExecution] = []
    accepted_entries = 0
    for candidate in candidates:
        if accepted_entries >= max_entries:
            executions.append(CandidateExecution(candidate.market.pair.symbol, False, "cycle_capacity_reached", None))
            continue
        if not candidate.decision.accepted:
            executions.append(CandidateExecution(candidate.market.pair.symbol, False, "decision_not_accepted", None))
            continue
        result: ExecutionResult = await execution_gateway.execute_entry_decision(
            candidate.market.pair,
            candidate.decision,
            candidate.market.order_book,
            candidate.decision.decision_id,
        )
        if result.accepted:
            accepted_entries += 1
        executions.append(
            CandidateExecution(
                candidate.market.pair.symbol,
                result.accepted,
                result.reason,
                result.order.order_id if result.order else None,
            )
        )
    return executions


async def main() -> None:
    settings = get_settings()
    engine = make_engine(settings)
    await create_schema(engine)
    repository = PersistentTradingRepository(make_session_factory(engine))
    await repository.initialize_portfolio(settings.initial_cash_eur)
    market_client = RevolutXPublicClient(
        base_url=settings.revolut_x_base_url,
        region=settings.revolut_x_region,
        timeout=float(settings.market_data_timeout_seconds),
    )
    replay_client = None
    if settings.market_data_replay_file:
        from autotrader.market_data.replay import FileReplayClient
        await market_client.close()
        replay_client = FileReplayClient(settings.market_data_replay_file)
        market_client = replay_client  # type: ignore[assignment]
    market_data = MarketDataService(market_client, max_staleness_seconds=settings.market_data_max_staleness_seconds)
    risk = RiskEngine(
        RiskLimits(
            max_allocated_capital=settings.max_allocated_capital_eur,
            max_total_open_exposure=settings.max_total_open_exposure_eur,
            min_uncommitted_reserve=settings.min_uncommitted_reserve_eur,
            max_position_size=settings.max_position_size_eur,
            max_simultaneous_positions=settings.max_simultaneous_positions,
            max_planned_loss_per_trade=settings.max_planned_loss_per_trade_eur,
            daily_loss_threshold=settings.daily_loss_threshold_eur,
            weekly_loss_threshold=settings.weekly_loss_threshold_eur,
            max_new_entries_per_day=settings.max_new_entries_per_day,
        )
    )
    execution_gateway = PaperExecutionGateway(
        repository,
        market_data=market_data,
        risk_engine=risk,
        initial_cash=settings.initial_cash_eur,
        fee_bps=settings.default_fee_bps,
        slippage_bps=settings.default_slippage_bps,
    )
    strategy_engine = BreakoutStrategyEngine()
    decision_engine = DecisionEngine(risk)
    ai_provider = make_ai_provider(settings, repository)
    scanner = MarketScanner(
        market_data=market_data,
        repository=repository,
        strategy_engine=strategy_engine,
        decision_engine=decision_engine,
        ai_provider=ai_provider,
        initial_cash=settings.initial_cash_eur,
    )
    position_manager = PositionManager(
        repository=repository,
        market_data=market_data,
        execution_gateway=execution_gateway,
    )
    await repository.recover_pending_orders()
    await repository.reconcile_runtime_health(settings.initial_cash_eur)
    logger.info("starting worker in durable paper mode", extra={"ai_provider": settings.ai_provider})
    try:
        while True:
            try:
                frame_id = replay_client.refresh() if replay_client else None
                if replay_client and frame_id == await repository.last_worker_frame():
                    await asyncio.sleep(settings.worker_scan_interval_seconds)
                    continue
                await repository.recover_pending_orders()
                position_actions = await position_manager.monitor_once()
                if position_actions:
                    logger.info(
                        "position manager actions",
                        extra={"actions": [action.reason for action in position_actions]},
                    )
                result = await scanner.scan_once(settings.scanner_max_pairs)
                executions = await execute_ranked_candidates(
                    result.candidates,
                    execution_gateway,
                    settings.worker_max_entries_per_cycle,
                )
                if executions:
                    logger.info("worker entry executions complete", extra={"executions": [execution.__dict__ for execution in executions]})
                else:
                    logger.info(
                        "worker scan complete",
                        extra={
                            "status": result.status,
                            "scanned": result.scanned,
                            "candidates": len(result.candidates),
                            "provider_errors": len(result.provider_errors),
                        },
                    )
                await repository.snapshot()
                await repository.worker_heartbeat(frame_id)
            except MarketDataError as exc:
                logger.warning("market data unavailable; skipping worker cycle", extra={"error": str(exc)})
            problems = await repository.reconcile_runtime_health(settings.initial_cash_eur)
            if problems:
                logger.error("reconciliation failed", extra={"problems": problems})
            await asyncio.sleep(settings.worker_scan_interval_seconds)
    finally:
        await market_data.close()
        await engine.dispose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
