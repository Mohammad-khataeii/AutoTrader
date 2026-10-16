from __future__ import annotations

import asyncio
import logging
import signal
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from autotrader.ai import make_ai_provider
from autotrader.config import get_settings
from autotrader.decision import DecisionEngine
from autotrader.domain import new_id, utc_now
from autotrader.execution_gateway import ExecutionResult, PaperExecutionGateway
from autotrader.market_data.revolut import MarketDataError, RevolutXPublicClient
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.pilot import pilot_configuration
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
        selected_decision = candidate.decision
        if accepted_entries >= max_entries:
            executions.append(CandidateExecution(candidate.market.pair.symbol, False, "cycle_capacity_reached", None))
            continue
        if not candidate.decision.accepted:
            executions.append(CandidateExecution(candidate.market.pair.symbol, False, "decision_not_accepted", None))
            continue
        if hasattr(execution_gateway, "allocate_candidate") and hasattr(candidate, "features"):
            allocated, allocation_reason = await execution_gateway.allocate_candidate(candidate)
            if allocated is None:
                executions.append(CandidateExecution(candidate.market.pair.symbol, False, allocation_reason, None))
                continue
            selected_decision = allocated
        result: ExecutionResult = await execution_gateway.execute_entry_decision(
            candidate.market.pair,
            selected_decision,
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
    owner=new_id('coordinator')
    while not await repository.claim_coordinator(owner):
        await asyncio.sleep(2)
    await repository.operation_state('INITIALIZING','coordinator_acquired')
    await repository.configure_research_policy(Path(settings.research_root), test_environment=settings.environment == "test",
        approved={s.strip() for s in settings.approved_strategy_ids.split(",") if s.strip()},
        execution_costs={'fee_bps':str(settings.default_fee_bps),'slippage_bps':str(settings.default_slippage_bps),'spread_bps':'10','volume_participation':'.01'})
    market_client = RevolutXPublicClient(
        base_url=settings.revolut_x_base_url,
        region=settings.revolut_x_region,
        timeout=float(settings.market_data_timeout_seconds),
        rate_reserver=repository.reserve_public_request,
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
        allocation_profile=settings.allocation_profile,
        slippage_bps=settings.default_slippage_bps,
    )
    strategy_engine = BreakoutStrategyEngine(member_parameters=await repository.frozen_runtime_parameters())
    decision_engine = DecisionEngine(risk, default_quote_amount={"conservative":Decimal(50), "balanced":Decimal(75), "opportunistic":Decimal(100)}[settings.allocation_profile])
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
    await repository.worker_heartbeat(key='worker_instance')
    logger.info("starting worker in durable paper mode", extra={"ai_provider": settings.ai_provider})
    stopping=asyncio.Event()
    loop=asyncio.get_running_loop()
    for signum in (signal.SIGINT,signal.SIGTERM):
        try:
            loop.add_signal_handler(signum,stopping.set)
        except (NotImplementedError,RuntimeError):
            pass
    async def renew_ownership()->None:
        while not stopping.is_set():
            try:
                if not await repository.claim_coordinator(owner):
                    stopping.set()
                    return
                await repository.worker_heartbeat(key='coordinator_heartbeat')
            except Exception:
                logger.exception('coordinator renewal unavailable; financial ownership checks remain authoritative')
            try:
                await asyncio.wait_for(stopping.wait(),timeout=5)
            except TimeoutError:
                pass
    async def protective_loop()->None:
        while not stopping.is_set():
            monitor_started=time.monotonic()
            try:
                await position_manager.monitor_once()
                await repository.snapshot()
                await repository.worker_heartbeat(key="position_monitor")
            except Exception:
                logger.exception("independent position monitoring cycle failed")
            try:
                await asyncio.wait_for(stopping.wait(),timeout=max(.1,settings.worker_position_interval_seconds-(time.monotonic()-monitor_started)))
            except TimeoutError:
                pass
    ownership_task=asyncio.create_task(renew_ownership())
    protective_task=asyncio.create_task(protective_loop()) if replay_client is None else None
    failures=0
    await repository.operation_state('DATA_SYNCING','waiting_for_completed_market_observations')
    try:
        while not stopping.is_set():
            cycle_started=time.monotonic()
            delay=float(settings.worker_scan_interval_seconds)
            try:
                await repository.configure_research_policy(Path(settings.research_root),test_environment=settings.environment=='test',
                    approved={s.strip() for s in settings.approved_strategy_ids.split(',') if s.strip()},
                    execution_costs={'fee_bps':str(settings.default_fee_bps),'slippage_bps':str(settings.default_slippage_bps),'spread_bps':'10','volume_participation':'.01'})
                strategy_engine.member_parameters=await repository.frozen_runtime_parameters()
                frame_id = replay_client.refresh() if replay_client else None
                if replay_client and frame_id == await repository.last_worker_frame():
                    await asyncio.sleep(settings.worker_scan_interval_seconds)
                    continue
                await repository.recover_pending_orders()
                position_actions = await position_manager.monitor_once() if replay_client else []
                if position_actions:
                    logger.info(
                        "position manager actions",
                        extra={"actions": [action.reason for action in position_actions]},
                    )
                result = await scanner.scan_once(settings.scanner_max_pairs)
                await repository.store_scan(result)
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
                await repository.refresh_opportunity_feedback()
                await repository.worker_heartbeat(frame_id)
                problems=await repository.reconcile_runtime_health(settings.initial_cash_eur)
                snapshot=await repository.snapshot()
                allowed=await repository.frozen_runtime_parameters()
                state=('RECOVERY_REQUIRED' if problems else 'RISK_HALTED' if snapshot['risk_state']!='HEALTHY'
                    else 'DATA_DEGRADED' if result.provider_errors or result.status=='DATA_UNAVAILABLE'
                    else 'ENTRY_SUSPENDED' if snapshot['control']!='RUNNING'
                    else 'RESEARCH_ONLY' if not allowed and settings.environment!='test'
                    else 'PAPER_TRADING' if int(snapshot['positions']) else 'PAPER_READY')
                duration=time.monotonic()-cycle_started
                await repository.operation_state(state,'scan_cycle_completed',{
                    'last_completed_scan':utc_now().isoformat(),'scan_duration_seconds':duration,
                    'schedule_overrun_seconds':max(0,duration-settings.worker_scan_interval_seconds),
                    'markets_scanned':result.scanned,'successful_observations':len(result.candidates),
                    'data_failures':len(result.provider_errors),'strategies_evaluated':sum(len(c.signals) for c in result.candidates),
                    'qualified_signals':sum(bool(sig.evidence.get('entry_eligible')) for c in result.candidates for sig in c.signals),
                    'rejected_signals':sum(not c.decision.accepted for c in result.candidates),
                    'paper_entries_filled':sum(e.accepted for e in executions),
                    'execution_outcomes':[e.__dict__ for e in executions],
                    'next_scan_at':(utc_now()+__import__('datetime').timedelta(seconds=max(0,settings.worker_scan_interval_seconds-duration))).isoformat()})
                if hasattr(repository,'capture_pilot_snapshot'):
                    await repository.capture_pilot_snapshot(test_environment=settings.environment=="test",current_config=pilot_configuration(settings))
                failures=0
                delay=max(.1,settings.worker_scan_interval_seconds-duration)
            except MarketDataError as exc:
                logger.warning("market data unavailable; skipping worker cycle", extra={"error": str(exc)})
                failures+=1
                try:
                    await repository.operation_state('DATA_DEGRADED',type(exc).__name__)
                except Exception:
                    logger.exception('incident persistence unavailable')
                delay=min(60,2**min(failures,6))
            except Exception as exc:
                failures+=1
                logger.exception('worker cycle failed; durable state preserved')
                try:
                    await repository.operation_state('SYSTEM_ERROR',type(exc).__name__)
                except Exception:
                    logger.exception('incident persistence unavailable')
                delay=min(60,2**min(failures,6))
            try:
                await asyncio.wait_for(stopping.wait(),timeout=delay)
            except TimeoutError:
                pass
    finally:
        ownership_task.cancel()
        await asyncio.gather(ownership_task,return_exceptions=True)
        if protective_task:
            protective_task.cancel()
            await asyncio.gather(protective_task,return_exceptions=True)
        try:
            await repository.release_coordinator(owner)
        except Exception:
            logger.exception('lease release unavailable; bounded expiry applies')
        await market_data.close()
        await engine.dispose()


def run() -> None:
    from autotrader.logging_config import configure_logging
    configure_logging()
    import os
    logger.info('worker_process_identity',extra={'process_id':os.getpid(),'parent_process_id':os.getppid()})
    asyncio.run(main())


if __name__ == "__main__":
    run()
