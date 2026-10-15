from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

from autotrader.domain import Order, Position, Side, TradingPair, utc_now
from autotrader.execution.pricing import quote_execution, target_gross_floor
from autotrader.execution_gateway import PaperExecutionGateway
from autotrader.market_data.revolut import MarketDataError
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.accounting import aware
from autotrader.persistence.repository import PersistentTradingRepository


@dataclass(frozen=True)
class PositionAction:
    symbol: str
    reason: str
    order: Order | None


class PositionManager:
    def __init__(
        self,
        *,
        repository: PersistentTradingRepository,
        market_data: MarketDataService,
        execution_gateway: PaperExecutionGateway,
    ) -> None:
        self.repository = repository
        self.market_data = market_data
        self.execution_gateway = execution_gateway

    async def monitor_once(self, pairs: list[TradingPair] | None = None) -> list[PositionAction]:
        pair_by_symbol = {pair.symbol: pair for pair in pairs or []}
        actions: list[PositionAction] = []
        for position in await self.repository.list_positions():
            if position.closed_at is not None or position.quantity <= 0:
                continue
            if position.account_id != self.repository.account_id:
                actions.append(PositionAction(position.symbol, "unresolved_legacy_position", None))
                continue
            pair = pair_by_symbol.get(position.symbol)
            if pair is None:
                try:
                    pair = await self.market_data.resolve_pair(position.symbol)
                except MarketDataError as exc:
                    await self.repository.protection_watch(position.position_id, str(exc))
                    actions.append(PositionAction(position.symbol, f"market_metadata_unavailable:{exc}", None))
                    continue
                if pair is None:
                    await self.repository.protection_watch(position.position_id, "market_metadata_unavailable")
                    actions.append(PositionAction(position.symbol, "market_metadata_unavailable", None))
                    continue
            try:
                if hasattr(self.market_data, "get_position_book"):
                    order_book = await self.market_data.get_position_book(pair)
                else:
                    order_book = (await self.market_data.get_validated_market(pair)).order_book
            except MarketDataError as exc:
                await self.repository.protection_watch(position.position_id, str(exc))
                actions.append(PositionAction(position.symbol, f"market_data_unavailable:{exc}", None))
                continue
            try:
                quote_execution(order_book, Side.SELL, position.quantity)
            except ValueError as exc:
                await self.repository.protection_watch(position.position_id, str(exc))
                actions.append(PositionAction(position.symbol, f"market_data_unavailable:{exc}", None))
                continue
            bid = order_book.best_bid
            assert bid is not None
            await self.repository.protection_watch(position.position_id, None)
            await self.repository.record_mark(order_book)
            await self.repository.update_position_monitor(position.position_id, bid,
                fee_bps=getattr(self.execution_gateway, "fee_bps", Decimal(0)),
                slippage_bps=getattr(self.execution_gateway, "slippage_bps", Decimal(0)))
            position = next(p for p in await self.repository.list_positions() if p.position_id == position.position_id)
            if position.protective_stop is not None and bid <= position.protective_stop:
                result = await self.execution_gateway.execute_exit(
                    pair,
                    position.quantity,
                    order_book,
                    self._intent_key(position, "STOP", order_book.timestamp.isoformat()),
                    "protective_stop",
                    position_id=position.position_id,
                )
                actions.append(PositionAction(position.symbol, result.reason, result.order))
                continue
            if position.expires_at is not None and aware(position.expires_at) <= utc_now():
                result = await self.execution_gateway.execute_exit(pair, position.quantity, order_book,
                    self._intent_key(position, "TIME_EXIT", order_book.timestamp.isoformat()), "time_exit", position_id=position.position_id)
                actions.append(PositionAction(position.symbol, result.reason, result.order))
                continue
            reduction = "emergency" if await self.repository.control_state() == "EMERGENCY" else await self.repository.market_exit_reason(position.symbol)
            if reduction:
                result = await self.execution_gateway.execute_exit(pair, position.quantity, order_book,
                    self._intent_key(position, reduction, order_book.timestamp.isoformat()), reduction, position_id=position.position_id)
                actions.append(PositionAction(position.symbol, result.reason, result.order))
                continue
            target = position.take_profit_targets[0] if position.take_profit_targets else None
            fee_bps = getattr(self.execution_gateway, "fee_bps", Decimal(0))
            slippage_bps = getattr(self.execution_gateway, "slippage_bps", Decimal(0))
            target_quote = quote_execution(order_book, Side.SELL, self._target_quantity(position),
                quantity_step=pair.quantity_step, fee_bps=fee_bps, slippage_bps=slippage_bps,
                limit_price=target_gross_floor(target, fee_bps)) if target is not None else None
            if target_quote is not None and target_quote.fillable_quantity > 0:
                quantity = self._target_quantity(position)
                result = await self.execution_gateway.execute_exit(
                    pair,
                    quantity,
                    order_book,
                    self._intent_key(position, position.target_ids[0], order_book.timestamp.isoformat()),
                    "take_profit_target",
                    position_id=position.position_id,
                    exit_target_id=position.target_ids[0],
                )
                filled_quantity = (
                    await self.repository.filled_quantity_for_order(result.order.order_id)
                    if result.order is not None
                    else Decimal("0")
                )
                if filled_quantity > 0:
                    await self.repository.sync_exit_plan_from_fills(position.symbol)
                actions.append(PositionAction(position.symbol, result.reason, result.order))
        return actions

    def _intent_key(self, position: Position, reason: str, observation_id: str) -> str:
        return sha256(f"{position.position_id}:{reason}:{observation_id}".encode()).hexdigest()

    def _target_quantity(self, position: Position) -> Decimal:
        if position.target_quantities:
            target_quantity = position.target_quantities[0]
            filled_quantity = position.target_filled_quantities[0] if position.target_filled_quantities else Decimal("0")
            return min(max(target_quantity - filled_quantity, Decimal("0")), position.quantity)
        if len(position.take_profit_targets) <= 1:
            return position.quantity
        return max(position.quantity / Decimal(len(position.take_profit_targets)), Decimal("0"))
