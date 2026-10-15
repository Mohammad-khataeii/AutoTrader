from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from autotrader.domain import Order, Position, TradingPair
from autotrader.execution_gateway import PaperExecutionGateway
from autotrader.market_data.revolut import MarketDataError
from autotrader.market_data.service import MarketDataService
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
            pair = pair_by_symbol.get(position.symbol)
            if pair is None:
                pair = await self.market_data.resolve_pair(position.symbol)
                if pair is None:
                    actions.append(PositionAction(position.symbol, "market_metadata_unavailable", None))
                    continue
            try:
                market = await self.market_data.get_validated_market(pair)
            except MarketDataError as exc:
                actions.append(PositionAction(position.symbol, f"market_data_unavailable:{exc}", None))
                continue
            mid = market.order_book.mid
            if mid is None:
                continue
            if position.protective_stop is not None and mid <= position.protective_stop:
                result = await self.execution_gateway.execute_exit(
                    pair,
                    position.quantity,
                    market.order_book,
                    self.execution_gateway.cycle_key("stop", pair.symbol),
                    "protective_stop",
                )
                actions.append(PositionAction(position.symbol, result.reason, result.order))
                continue
            target = position.take_profit_targets[0] if position.take_profit_targets else None
            if target is not None and mid >= target:
                quantity = self._target_quantity(position)
                result = await self.execution_gateway.execute_exit(
                    pair,
                    quantity,
                    market.order_book,
                    self.execution_gateway.cycle_key("target", pair.symbol),
                    "take_profit_target",
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

    def _target_quantity(self, position: Position) -> Decimal:
        if position.target_quantities:
            target_quantity = position.target_quantities[0]
            filled_quantity = position.target_filled_quantities[0] if position.target_filled_quantities else Decimal("0")
            return min(max(target_quantity - filled_quantity, Decimal("0")), position.quantity)
        if len(position.take_profit_targets) <= 1:
            return position.quantity
        return max(position.quantity / Decimal(len(position.take_profit_targets)), Decimal("0"))
