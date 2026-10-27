from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from autotrader.allocation import allocation_advice

if TYPE_CHECKING:
    from autotrader.scanner import ScanCandidate

from autotrader.domain import (
    DecisionAction,
    Order,
    OrderBook,
    OrderStatus,
    OrderType,
    RuntimeHealth,
    Side,
    TradingDecision,
    TradingPair,
    new_id,
    utc_now,
)
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.portfolio import Portfolio
from autotrader.risk import RiskEngine


@dataclass(frozen=True)
class ExecutionResult:
    accepted: bool
    reason: str
    order: Order | None = None


class PaperExecutionGateway:
    def __init__(
        self,
        repository: PersistentTradingRepository,
        *,
        market_data: MarketDataService,
        risk_engine: RiskEngine,
        initial_cash: Decimal,
        fee_bps: Decimal,
        slippage_bps: Decimal,
        entry_order_type: OrderType = OrderType.MARKET,
        allocation_profile: str = "balanced",
    ) -> None:
        self.repository = repository
        self.market_data = market_data
        self.risk_engine = risk_engine
        self.initial_cash = initial_cash
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.entry_order_type = entry_order_type
        self.allocation_profile = allocation_profile

    async def allocate_candidate(self, candidate: ScanCandidate) -> tuple[TradingDecision | None, str]:
        metadata = {**candidate.features.metadata, "_feature_timestamp": candidate.features.timestamp.isoformat()}
        advice = allocation_advice(metadata, await self.repository.allocation_context(), profile=self.allocation_profile)
        await self.repository.store_allocation_advice(candidate.decision.decision_id, asdict(advice))
        if not advice.accepted:
            return None, ",".join(advice.reasons)
        quote = min(candidate.decision.proposed_quote_amount, advice.quote_cap)
        ratio = quote / candidate.decision.proposed_quote_amount if candidate.decision.proposed_quote_amount > 0 else Decimal(0)
        return replace(candidate.decision, proposed_quote_amount=quote,
            proposed_quantity=candidate.decision.proposed_quantity * ratio), "allocation_accepted"

    async def execute_entry_decision(
        self,
        pair: TradingPair,
        decision: TradingDecision,
        order_book: OrderBook,
        idempotency_key: str,
    ) -> ExecutionResult:
        if decision.action is not DecisionAction.BUY or not decision.accepted:
            return ExecutionResult(False, decision.rejected_reason or "decision_not_accepted")
        from autotrader.persistence.accounting import aware
        age=(utc_now()-aware(decision.timestamp)).total_seconds()
        if age>self.repository.mark_max_age_seconds or age < -5:
            return ExecutionResult(False,'stale_or_future_decision')
        if decision.symbol != pair.symbol:
            return ExecutionResult(False, "decision_pair_mismatch")
        if pair.quote_asset != self.repository.quote_asset:
            return ExecutionResult(False, f"unsupported_quote_currency:{pair.quote_asset}")
        if decision.proposed_quote_amount < pair.min_order_quote:
            return ExecutionResult(False, "below_min_order_quote")
        if decision.proposed_quantity < pair.min_order_base:
            return ExecutionResult(False, "below_min_order_base")
        if pair.max_order_base is not None and decision.proposed_quantity > pair.max_order_base:
            return ExecutionResult(False, "above_max_order_base")
        runtime_health = await self.repository.get_runtime_health()
        if runtime_health is not RuntimeHealth.HEALTHY:
            return ExecutionResult(False, f"runtime_not_healthy:{runtime_health.value}")
        reconciliation = await self.repository.reconcile_runtime_health(self.initial_cash)
        if reconciliation:
            return ExecutionResult(False, f"reconciliation_required:{','.join(reconciliation)}")
        from autotrader.market_data.revolut import RevolutXPublicClient
        if isinstance(getattr(self.market_data,'client',None),RevolutXPublicClient):
            from autotrader.market_data.revolut import MarketDataError
            try:
                order_book = await self.market_data.get_execution_book(pair)
            except MarketDataError as exc:
                return ExecutionResult(False,'execution_book_unavailable:'+str(exc))
        reasons, _ = self.market_data.validate_order_book(order_book)
        if reasons:
            return ExecutionResult(False, ",".join(reasons))
        if decision.entry_price is None or decision.stop_loss is None:
            return ExecutionResult(False, "missing_entry_risk_inputs")
        # The authoritative risk check runs under the account row lock in submit_order.
        await self.repository.record_mark(order_book)
        order = await self.repository.submit_order(
            pair=pair,
            side=Side.BUY,
            order_type=self.entry_order_type,
            quantity=decision.proposed_quantity,
            quote_amount=decision.proposed_quote_amount,
            order_book=order_book,
            idempotency_key=idempotency_key,
            decision_id=decision.decision_id,
            fee_bps=self.fee_bps,
            slippage_bps=self.slippage_bps,
            stop_loss=decision.stop_loss,
            targets=list(decision.take_profit_targets),
            limit_price=decision.entry_price if self.entry_order_type is OrderType.LIMIT else None,
        )
        return ExecutionResult(order.status in {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED}, order.rejection_reason or order.status.value, order)

    async def execute_exit(
        self,
        pair: TradingPair,
        quantity: Decimal,
        order_book: OrderBook,
        idempotency_key: str,
        reason: str,
        *,
        position_id: str | None = None,
        exit_target_id: str | None = None,
    ) -> ExecutionResult:
        if quantity <= 0:
            return ExecutionResult(False, "non_positive_exit_quantity")
        if pair.quote_asset != self.repository.quote_asset:
            return ExecutionResult(False, f"unsupported_quote_currency:{pair.quote_asset}")
        reasons, _ = self.market_data.validate_order_book(order_book)
        if reasons:
            return ExecutionResult(False, ",".join(reasons))
        order = await self.repository.submit_order(
            pair=pair,
            side=Side.SELL,
            order_type=OrderType.MARKET,
            quantity=quantity,
            quote_amount=Decimal("0"),
            order_book=order_book,
            idempotency_key=idempotency_key,
            fee_bps=self.fee_bps,
            slippage_bps=self.slippage_bps,
            position_id=position_id,
            exit_target_id=exit_target_id,
            exit_reason={"protective_stop": "STOP", "take_profit_target": "TAKE_PROFIT", "time_exit": "TIME_EXIT", "market_risk": "MARKET_RISK", "regime_exit":"MARKET_RISK", "failed_breakout":"FAILED_BREAKOUT", "emergency": "EMERGENCY"}.get(reason, "MANUAL_EXIT"),
        )
        accepted=order.status in {OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED}
        return ExecutionResult(accepted, reason if accepted else order.rejection_reason or order.status.value, order)

    def cycle_key(self, prefix: str, symbol: str) -> str:
        # New decisions get new keys. A caller retry must retain the returned key.
        return new_id(prefix[:16])

    async def _portfolio(self) -> Portfolio:
        await self.repository.initialize_portfolio(self.initial_cash)
        snapshot = await self.repository.snapshot()
        portfolio = Portfolio(Decimal(snapshot["available_cash"]), quote_asset=self.repository.quote_asset)
        portfolio.balances[portfolio.quote_asset].reserved = Decimal(snapshot["reserved_cash"])
        for position in await self.repository.list_positions():
            if position.closed_at is None and position.quantity > 0:
                portfolio.positions[position.symbol] = position
        return portfolio


def _period_start(*, days: int) -> datetime:
    now = datetime.now(tz=UTC) - timedelta(days=days)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _week_start() -> datetime:
    now = datetime.now(tz=UTC)
    start = now - timedelta(days=now.weekday())
    return start.replace(hour=0, minute=0, second=0, microsecond=0)
