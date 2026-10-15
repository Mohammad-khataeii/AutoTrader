from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
    ) -> None:
        self.repository = repository
        self.market_data = market_data
        self.risk_engine = risk_engine
        self.initial_cash = initial_cash
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps

    async def execute_entry_decision(
        self,
        pair: TradingPair,
        decision: TradingDecision,
        order_book: OrderBook,
        idempotency_key: str,
    ) -> ExecutionResult:
        if decision.action is not DecisionAction.BUY or not decision.accepted:
            return ExecutionResult(False, decision.rejected_reason or "decision_not_accepted")
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
        reasons, _ = self.market_data.validate_order_book(order_book)
        if reasons:
            return ExecutionResult(False, ",".join(reasons))
        if decision.entry_price is None or decision.stop_loss is None:
            return ExecutionResult(False, "missing_entry_risk_inputs")
        portfolio = await self._portfolio()
        day_start = _period_start(days=0)
        week_start = _week_start()
        entries_today = await self.repository.count_buy_entries_since(day_start)
        daily_pnl = await self.repository.realized_pnl_since(day_start)
        weekly_pnl = await self.repository.realized_pnl_since(week_start)
        risk = self.risk_engine.evaluate_entry(
            portfolio,
            pair,
            decision.proposed_quote_amount,
            decision.entry_price,
            decision.stop_loss,
            entries_today,
            daily_pnl,
            weekly_pnl,
        )
        if not risk.accepted:
            return ExecutionResult(False, f"risk_rejected:{','.join(risk.reasons)}")
        order = await self.repository.submit_order(
            pair=pair,
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=decision.proposed_quantity,
            quote_amount=decision.proposed_quote_amount,
            order_book=order_book,
            idempotency_key=idempotency_key,
            decision_id=decision.decision_id,
            fee_bps=self.fee_bps,
            slippage_bps=self.slippage_bps,
        )
        if order.status in {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED}:
            await self.repository.set_position_exit_plan(
                pair.symbol,
                decision.stop_loss,
                list(decision.take_profit_targets),
                pair.quantity_step,
            )
        return ExecutionResult(order.status is not OrderStatus.REJECTED, order.status.value, order)

    async def execute_exit(
        self,
        pair: TradingPair,
        quantity: Decimal,
        order_book: OrderBook,
        idempotency_key: str,
        reason: str,
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
        )
        return ExecutionResult(order.status is not OrderStatus.REJECTED, reason, order)

    def cycle_key(self, prefix: str, symbol: str) -> str:
        return f"{prefix}-{symbol}-{utc_now().strftime('%Y%m%d%H%M')}"

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
