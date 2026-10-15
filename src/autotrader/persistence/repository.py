from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from autotrader.domain import (
    AIAssessment,
    Fill,
    Order,
    OrderBook,
    OrderStatus,
    OrderType,
    Position,
    RiskEvaluation,
    RuntimeHealth,
    Side,
    StrategySignal,
    TradingDecision,
    TradingPair,
    new_id,
    quantize_down,
    utc_now,
)
from autotrader.persistence.models import (
    AIAssessmentModel,
    BalanceModel,
    CapitalReservationModel,
    FillModel,
    OrderModel,
    OrderTransitionModel,
    PortfolioSnapshotModel,
    PositionModel,
    RiskEvaluationModel,
    StrategySignalModel,
    SystemIncidentModel,
    SystemStateModel,
    TradingDecisionModel,
)


def _json(value: object) -> str:
    def default(item: object) -> str | dict[str, Any] | list[Any]:
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, Enum):
            return str(item.value)
        if is_dataclass(item) and not isinstance(item, type):
            return asdict(item)
        if hasattr(item, "isoformat"):
            return str(item)
        return str(item)

    return json.dumps(value, default=default, sort_keys=True)


def _target_rows(position: PositionModel) -> list[tuple[Decimal | None, Decimal, Decimal]]:
    return [
        (
            position.target_1,
            position.target_1_quantity or Decimal("0"),
            position.target_1_filled_quantity or Decimal("0"),
        ),
        (
            position.target_2,
            position.target_2_quantity or Decimal("0"),
            position.target_2_filled_quantity or Decimal("0"),
        ),
        (
            position.target_3,
            position.target_3_quantity or Decimal("0"),
            position.target_3_filled_quantity or Decimal("0"),
        ),
    ]


def _default_target_quantities(original_quantity: Decimal, quantity_step: Decimal, target_count: int) -> list[Decimal]:
    if target_count <= 0:
        return []
    if target_count == 1:
        return [quantize_down(original_quantity, quantity_step)]
    weights = [Decimal("0.30"), Decimal("0.40"), Decimal("0.30")][:target_count]
    quantities = [quantize_down(original_quantity * weight, quantity_step) for weight in weights[:-1]]
    final_quantity = quantize_down(max(original_quantity - sum(quantities, Decimal("0")), Decimal("0")), quantity_step)
    return [*quantities, final_quantity]


class PersistentTradingRepository:
    RUNTIME_STATE_KEY = "runtime_health"

    def __init__(self, session_factory: async_sessionmaker[Any], quote_asset: str = "EUR") -> None:
        self.session_factory = session_factory
        self.quote_asset = quote_asset

    async def initialize_portfolio(self, initial_cash: Decimal) -> None:
        async with self.session_factory() as session, session.begin():
            balance = await session.get(BalanceModel, self.quote_asset)
            if balance is None:
                session.add(
                    BalanceModel(
                        asset=self.quote_asset,
                        available=initial_cash,
                        reserved=Decimal("0"),
                    )
                )
                session.add(
                    PortfolioSnapshotModel(
                        snapshot_id=new_id("snap"),
                        available_cash=initial_cash,
                        reserved_cash=Decimal("0"),
                        open_exposure=Decimal("0"),
                        realized_pnl=Decimal("0"),
                        payload_json='{"event":"initial_portfolio"}',
                    )
                )

    async def store_analysis(
        self,
        signals: list[StrategySignal],
        ai_assessment: AIAssessment | None,
        decision: TradingDecision,
        risk_evaluation: RiskEvaluation | None = None,
    ) -> None:
        async with self.session_factory() as session, session.begin():
            for signal in signals:
                if await session.get(StrategySignalModel, signal.signal_id) is None:
                    session.add(
                        StrategySignalModel(
                            signal_id=signal.signal_id,
                            strategy_id=signal.strategy_id,
                            symbol=signal.symbol,
                            timestamp=signal.timestamp,
                            score=signal.score,
                            data_quality=signal.data_quality.value,
                            payload_json=_json(signal),
                        )
                    )
            if ai_assessment and await session.get(AIAssessmentModel, ai_assessment.assessment_id) is None:
                session.add(
                    AIAssessmentModel(
                        assessment_id=ai_assessment.assessment_id,
                        symbol=ai_assessment.symbol,
                        provider=ai_assessment.provider,
                        model=ai_assessment.model,
                        failed=ai_assessment.failed,
                        tokens_used=ai_assessment.tokens_used,
                        estimated_cost_usd=ai_assessment.estimated_cost_usd,
                        payload_json=_json(ai_assessment),
                    )
                )
            if await session.get(TradingDecisionModel, decision.decision_id) is None:
                session.add(
                    TradingDecisionModel(
                        decision_id=decision.decision_id,
                        symbol=decision.symbol,
                        action=decision.action.value,
                        accepted=decision.accepted,
                        rejected_reason=decision.rejected_reason,
                        payload_json=_json(decision),
                    )
                )
            if risk_evaluation and await session.get(RiskEvaluationModel, risk_evaluation.evaluation_id) is None:
                session.add(
                    RiskEvaluationModel(
                        evaluation_id=risk_evaluation.evaluation_id,
                        decision_id=decision.decision_id,
                        accepted=risk_evaluation.accepted,
                        reserved_quote=risk_evaluation.reserved_quote,
                        payload_json=_json(risk_evaluation),
                    )
                )

    async def get_runtime_health(self) -> RuntimeHealth:
        async with self.session_factory() as session:
            state = await session.get(SystemStateModel, self.RUNTIME_STATE_KEY)
            if state is None:
                return RuntimeHealth.HEALTHY
            return RuntimeHealth(state.state)

    async def set_runtime_health(
        self,
        state: RuntimeHealth,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        async with self.session_factory() as session, session.begin():
            existing = await session.get(SystemStateModel, self.RUNTIME_STATE_KEY)
            payload_json = _json(payload or {})
            if existing is None:
                session.add(
                    SystemStateModel(
                        key=self.RUNTIME_STATE_KEY,
                        state=state.value,
                        reason=reason,
                        payload_json=payload_json,
                    )
                )
            else:
                existing.state = state.value
                existing.reason = reason
                existing.payload_json = payload_json
            session.add(
                SystemIncidentModel(
                    incident_id=new_id("inc"),
                    severity="ERROR" if state is RuntimeHealth.RECONCILIATION_REQUIRED else "INFO",
                    status=state.value,
                    message=reason,
                    payload_json=payload_json,
                )
            )

    async def reconcile_runtime_health(self, initial_cash: Decimal) -> list[str]:
        problems = await self.verify_invariants(initial_cash)
        if problems:
            await self.set_runtime_health(
                RuntimeHealth.RECONCILIATION_REQUIRED,
                "reconciliation_failed",
                {"problems": problems},
            )
            return problems
        if await self.get_runtime_health() is RuntimeHealth.RECONCILIATION_REQUIRED:
            await self.set_runtime_health(
                RuntimeHealth.RECOVERING,
                "reconciliation_passed_manual_reset_required",
                {},
            )
        return []

    async def reset_runtime_health_after_reconciliation(self, initial_cash: Decimal) -> list[str]:
        problems = await self.verify_invariants(initial_cash)
        if problems:
            await self.set_runtime_health(
                RuntimeHealth.RECONCILIATION_REQUIRED,
                "reconciliation_failed_during_reset",
                {"problems": problems},
            )
            return problems
        await self.set_runtime_health(RuntimeHealth.HEALTHY, "manual_reconciliation_reset", {})
        return []

    async def submit_order(
        self,
        pair: TradingPair,
        side: Side,
        order_type: OrderType,
        quantity: Decimal,
        quote_amount: Decimal,
        order_book: OrderBook,
        idempotency_key: str,
        decision_id: str | None = None,
        limit_price: Decimal | None = None,
        fee_bps: Decimal = Decimal("10"),
        slippage_bps: Decimal = Decimal("8"),
    ) -> Order:
        async with self.session_factory() as session, session.begin():
            existing_order = await session.scalar(select(OrderModel).where(OrderModel.client_order_id == idempotency_key))
            if existing_order is not None:
                return self._domain_order(existing_order)
            existing_reservation = await session.scalar(
                select(CapitalReservationModel).where(CapitalReservationModel.idempotency_key == idempotency_key)
            )
            if existing_reservation and existing_reservation.order_id:
                existing_order = await session.get(OrderModel, existing_reservation.order_id)
                if existing_order is None:
                    raise RuntimeError("Reservation references a missing order.")
                return self._domain_order(existing_order)

            quantity = quantize_down(quantity, pair.quantity_step)
            order = Order(
                order_id=new_id("ord"),
                client_order_id=idempotency_key,
                symbol=pair.symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                quote_amount=quote_amount,
                limit_price=limit_price,
                status=OrderStatus.PENDING,
                created_at=utc_now(),
                decision_id=decision_id,
                simulated=True,
            )
            order_model = OrderModel(
                order_id=order.order_id,
                decision_id=decision_id,
                client_order_id=idempotency_key,
                symbol=pair.symbol,
                side=side.value,
                order_type=order_type.value,
                status=OrderStatus.PENDING.value,
                quantity=quantity,
                quote_amount=quote_amount,
                filled_quantity=Decimal("0"),
                average_fill_price=None,
                simulated=True,
                created_at=order.created_at,
            )
            session.add(order_model)
            self._transition(session, order.order_id, None, OrderStatus.PENDING, "created")

            try:
                await self._accept_and_fill(
                    session,
                    order_model,
                    pair,
                    order_book,
                    limit_price,
                    fee_bps,
                    slippage_bps,
                    idempotency_key,
                )
            except ValueError as exc:
                order_model.status = OrderStatus.REJECTED.value
                self._transition(session, order.order_id, OrderStatus.PENDING, OrderStatus.REJECTED, str(exc))

            await session.flush()
            return self._domain_order(order_model)

    async def snapshot(self) -> dict[str, str]:
        async with self.session_factory() as session:
            balance = await session.get(BalanceModel, self.quote_asset)
            positions = list((await session.scalars(select(PositionModel))).all())
            orders = list((await session.scalars(select(OrderModel))).all())
            if balance is None:
                return {"available_cash": "0", "reserved_cash": "0", "open_exposure": "0", "positions": "0", "orders": str(len(orders))}
            open_positions = [position for position in positions if position.state == "OPEN"]
            exposure = sum((position.quantity * position.average_entry_price for position in open_positions), Decimal("0"))
            return {
                "available_cash": str(balance.available),
                "reserved_cash": str(balance.reserved),
                "open_exposure": str(exposure),
                "positions": str(len(open_positions)),
                "orders": str(len(orders)),
            }

    async def count_buy_entries_since(self, since: datetime) -> int:
        async with self.session_factory() as session:
            count = await session.scalar(
                select(func.count()).select_from(OrderModel).where(OrderModel.side == Side.BUY.value, OrderModel.created_at >= since)
            )
            return int(count or 0)

    async def realized_pnl_since(self, since: datetime) -> Decimal:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(FillModel, PositionModel)
                    .join(PositionModel, PositionModel.position_id == FillModel.position_id)
                    .where(FillModel.side == Side.SELL.value, FillModel.created_at >= since)
                )
            ).all()
            return sum(
                ((fill.quantity * (fill.price - position.average_entry_price)) - fill.fee for fill, position in rows),
                Decimal("0"),
            )

    async def unrealized_pnl(self, marks: dict[str, Decimal]) -> Decimal:
        async with self.session_factory() as session:
            positions = list(
                (
                    await session.scalars(
                        select(PositionModel).where(PositionModel.state == "OPEN", PositionModel.quantity > 0)
                    )
                ).all()
            )
            missing = [position.symbol for position in positions if position.symbol not in marks]
            if missing:
                raise ValueError(f"Missing marks for open positions: {', '.join(sorted(missing))}")
            return sum(
                (position.quantity * (marks[position.symbol] - position.average_entry_price) for position in positions),
                Decimal("0"),
            )

    async def ai_spend_since(self, since: datetime) -> Decimal:
        async with self.session_factory() as session:
            spend = await session.scalar(
                select(func.sum(AIAssessmentModel.estimated_cost_usd)).where(
                    AIAssessmentModel.provider == "openai",
                    AIAssessmentModel.created_at >= since,
                )
            )
            return spend or Decimal("0")

    async def list_orders(self) -> list[dict[str, str]]:
        async with self.session_factory() as session:
            orders = list((await session.scalars(select(OrderModel).order_by(OrderModel.created_at))).all())
            return [
                {
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "side": order.side,
                    "status": order.status,
                    "quantity": str(order.quantity),
                    "filled_quantity": str(order.filled_quantity),
                    "average_fill_price": str(order.average_fill_price) if order.average_fill_price is not None else "",
                }
                for order in orders
            ]

    async def list_fills(self) -> list[dict[str, str]]:
        async with self.session_factory() as session:
            fills = list((await session.scalars(select(FillModel).order_by(FillModel.created_at))).all())
            return [
                {
                    "fill_id": fill.fill_id,
                    "order_id": fill.order_id,
                    "symbol": fill.symbol,
                    "side": fill.side,
                    "quantity": str(fill.quantity),
                    "price": str(fill.price),
                    "fee": str(fill.fee),
                    "simulated": str(fill.simulated),
                }
                for fill in fills
            ]

    async def list_positions(self) -> list[Position]:
        async with self.session_factory() as session:
            positions = list((await session.scalars(select(PositionModel).order_by(PositionModel.created_at))).all())
            return [
                Position(
                    position_id=position.position_id,
                    symbol=position.symbol,
                    quantity=position.quantity,
                    average_entry_price=position.average_entry_price,
                    opened_at=position.opened_at,
                    realized_pnl=position.realized_pnl,
                    protective_stop=position.protective_stop,
                    take_profit_targets=[
                        target for target, quantity, filled in _target_rows(position) if target is not None and filled < quantity
                    ],
                    original_quantity=position.original_quantity or position.quantity,
                    target_quantities=[
                        quantity for target, quantity, filled in _target_rows(position) if target is not None and filled < quantity
                    ],
                    target_filled_quantities=[
                        filled for target, quantity, filled in _target_rows(position) if target is not None and filled < quantity
                    ],
                    closed_at=position.closed_at,
                )
                for position in positions
            ]

    async def set_position_exit_plan(
        self,
        symbol: str,
        stop_loss: Decimal | None,
        targets: list[Decimal],
        quantity_step: Decimal = Decimal("0.00000001"),
    ) -> None:
        async with self.session_factory() as session, session.begin():
            position = await self._get_open_position(session, symbol)
            if position is None or position.state != "OPEN":
                return
            position.protective_stop = stop_loss
            original_quantity = position.original_quantity or position.quantity
            position.original_quantity = original_quantity
            padded = [*targets[:3], None, None, None]
            position.target_1 = padded[0]
            position.target_2 = padded[1]
            position.target_3 = padded[2]
            quantities = _default_target_quantities(original_quantity, quantity_step, len(targets[:3]))
            quantity_padded = [*quantities, None, None, None]
            position.target_1_quantity = quantity_padded[0]
            position.target_2_quantity = quantity_padded[1]
            position.target_3_quantity = quantity_padded[2]
            position.target_1_filled_quantity = position.target_1_filled_quantity or Decimal("0")
            position.target_2_filled_quantity = position.target_2_filled_quantity or Decimal("0")
            position.target_3_filled_quantity = position.target_3_filled_quantity or Decimal("0")

    async def advance_position_target(self, symbol: str, hit_target: Decimal) -> None:
        async with self.session_factory() as session, session.begin():
            position = await self._get_open_position(session, symbol)
            if position is None:
                return
            targets = [target for target in (position.target_1, position.target_2, position.target_3) if target is not None]
            remaining = [target for target in targets if target != hit_target]
            padded = [*remaining[:3], None, None, None]
            position.target_1 = padded[0]
            position.target_2 = padded[1]
            position.target_3 = padded[2]

    async def filled_quantity_for_order(self, order_id: str) -> Decimal:
        async with self.session_factory() as session:
            filled = await session.scalar(select(func.sum(FillModel.quantity)).where(FillModel.order_id == order_id))
            return filled or Decimal("0")

    async def sync_exit_plan_from_fills(self, symbol: str) -> None:
        async with self.session_factory() as session, session.begin():
            position = await self._get_open_position(session, symbol)
            if position is None:
                return
            original_quantity = position.original_quantity or position.quantity
            position.original_quantity = original_quantity
            sell_filled = await session.scalar(
                select(func.sum(FillModel.quantity)).where(
                    FillModel.position_id == position.position_id,
                    FillModel.side == Side.SELL.value,
                )
            )
            exited = sell_filled or Decimal("0")
            remaining_exited = exited
            for index in range(1, 4):
                target_price = getattr(position, f"target_{index}")
                target_quantity = getattr(position, f"target_{index}_quantity") or Decimal("0")
                if target_price is None or target_quantity <= 0:
                    setattr(position, f"target_{index}_filled_quantity", Decimal("0"))
                    continue
                filled = min(max(remaining_exited, Decimal("0")), target_quantity)
                setattr(position, f"target_{index}_filled_quantity", filled)
                remaining_exited -= filled
                if filled >= target_quantity:
                    setattr(position, f"target_{index}", None)

    async def verify_invariants(self, initial_cash: Decimal) -> list[str]:
        async with self.session_factory() as session:
            problems: list[str] = []
            balance = await session.get(BalanceModel, self.quote_asset)
            if balance is None:
                return ["missing_quote_balance"]
            if balance.available < 0:
                problems.append("negative_available_cash")
            if balance.reserved < 0:
                problems.append("negative_reserved_cash")
            for position in (await session.scalars(select(PositionModel))).all():
                if position.quantity < 0:
                    problems.append(f"negative_position:{position.symbol}")
            fills = list((await session.scalars(select(FillModel))).all())
            cash_from_fills = initial_cash
            position_quantities: dict[str, Decimal] = {}
            for fill in fills:
                notional = fill.quantity * fill.price
                if fill.side == Side.BUY.value:
                    cash_from_fills -= notional + fill.fee
                    if fill.position_id:
                        position_quantities[fill.position_id] = position_quantities.get(fill.position_id, Decimal("0")) + fill.quantity
                else:
                    cash_from_fills += notional - fill.fee
                    if fill.position_id:
                        position_quantities[fill.position_id] = position_quantities.get(fill.position_id, Decimal("0")) - fill.quantity
            if (balance.available + balance.reserved - cash_from_fills).copy_abs() > Decimal("0.000001"):
                problems.append("cash_balance_does_not_match_fill_replay")
            open_reservations = await session.scalar(
                select(func.sum(CapitalReservationModel.amount)).where(CapitalReservationModel.status == "OPEN")
            )
            if (balance.reserved - (open_reservations or Decimal("0"))).copy_abs() > Decimal("0.000001"):
                problems.append("reserved_cash_does_not_match_open_reservations")
            for position in (await session.scalars(select(PositionModel))).all():
                expected = position_quantities.get(position.position_id)
                if expected is not None and (position.quantity - expected).copy_abs() > Decimal("0.000001"):
                    problems.append(f"position_quantity_does_not_match_fill_replay:{position.position_id}")
            return problems

    async def _accept_and_fill(
        self,
        session: Any,
        order: OrderModel,
        pair: TradingPair,
        order_book: OrderBook,
        limit_price: Decimal | None,
        fee_bps: Decimal,
        slippage_bps: Decimal,
        idempotency_key: str,
    ) -> None:
        if order.quantity <= 0:
            raise ValueError("Order quantity rounds to zero.")

        balance = await session.get(BalanceModel, self.quote_asset, with_for_update=True)
        if balance is None:
            raise ValueError("Portfolio is not initialized.")

        reservation: CapitalReservationModel | None = None
        if order.side == Side.BUY.value:
            if balance.available < order.quote_amount:
                raise ValueError("Insufficient available cash.")
            balance.available -= order.quote_amount
            balance.reserved += order.quote_amount
            reservation = CapitalReservationModel(
                reservation_id=new_id("res"),
                order_id=order.order_id,
                asset=self.quote_asset,
                amount=order.quote_amount,
                status="OPEN",
                idempotency_key=idempotency_key,
            )
            session.add(reservation)
        else:
            position = await self._get_open_position(session, order.symbol, lock=True)
            if position is None or position.quantity < order.quantity:
                raise ValueError("Cannot sell more than the available position quantity.")

        previous_status = OrderStatus(order.status)
        order.status = OrderStatus.ACCEPTED.value
        self._transition(session, order.order_id, previous_status, OrderStatus.ACCEPTED, "accepted")
        filled = await self._fill_order(session, order, order_book, limit_price, fee_bps, slippage_bps)
        if reservation is not None:
            reservation.status = "CLOSED" if filled else "RELEASED"
            if not filled:
                balance.reserved -= order.quote_amount
                balance.available += order.quote_amount
        if not filled:
            previous_status = OrderStatus(order.status)
            order.status = OrderStatus.REJECTED.value
            self._transition(session, order.order_id, previous_status, OrderStatus.REJECTED, "unfilled_market_order")

    async def _fill_order(
        self,
        session: Any,
        order: OrderModel,
        order_book: OrderBook,
        limit_price: Decimal | None,
        fee_bps: Decimal,
        slippage_bps: Decimal,
    ) -> bool:
        side = Side(order.side)
        book_side = order_book.asks if side is Side.BUY else order_book.bids
        if not book_side:
            return False

        remaining = order.quantity - order.filled_quantity
        filled_qty = Decimal("0")
        cost = Decimal("0")
        for level in book_side:
            if remaining <= 0:
                break
            if OrderType(order.order_type) is OrderType.LIMIT and limit_price is not None:
                crosses = level.price <= limit_price if side is Side.BUY else level.price >= limit_price
                if not crosses:
                    continue
            qty = min(remaining, level.quantity)
            fill_price = self._with_slippage(level.price, side, slippage_bps)
            projected_cost = cost + (qty * fill_price)
            projected_fee = projected_cost * fee_bps / Decimal("10000")
            if side is Side.BUY and projected_cost + projected_fee > order.quote_amount:
                affordable_qty = ((order.quote_amount - cost) / (fill_price * (Decimal("1") + fee_bps / Decimal("10000")))).quantize(
                    Decimal("0.00000001")
                )
                qty = max(min(qty, affordable_qty), Decimal("0"))
            if qty <= 0:
                break
            filled_qty += qty
            cost += qty * fill_price
            remaining -= qty

        if filled_qty == 0:
            return False

        avg_price = cost / filled_qty
        fee = cost * fee_bps / Decimal("10000")
        fill = Fill(new_id("fill"), order.order_id, order.symbol, side, filled_qty, avg_price, fee, utc_now(), simulated=True)
        fill_model = FillModel(
            fill_id=fill.fill_id,
            order_id=fill.order_id,
            position_id=None,
            symbol=fill.symbol,
            side=fill.side.value,
            quantity=fill.quantity,
            price=fill.price,
            fee=fill.fee,
            simulated=True,
        )
        session.add(fill_model)
        fill_model.position_id = await self._apply_fill(session, fill, order.quote_amount)
        previous_status = OrderStatus(order.status)
        order.filled_quantity += filled_qty
        order.average_fill_price = avg_price
        order.status = (OrderStatus.FILLED if order.filled_quantity >= order.quantity else OrderStatus.PARTIALLY_FILLED).value
        self._transition(session, order.order_id, previous_status, OrderStatus(order.status), "simulated_fill")
        return True

    async def _apply_fill(self, session: Any, fill: Fill, quote_amount: Decimal) -> str:
        balance = await session.get(BalanceModel, self.quote_asset, with_for_update=True)
        if balance is None:
            raise ValueError("Portfolio is not initialized.")
        notional = fill.quantity * fill.price
        if fill.side is Side.BUY:
            spend = notional + fill.fee
            balance.reserved -= quote_amount
            balance.available += max(quote_amount - spend, Decimal("0"))
            position = await self._get_open_position(session, fill.symbol, lock=True)
            if position is None:
                position = PositionModel(
                    position_id=new_id("pos"),
                    symbol=fill.symbol,
                    quantity=fill.quantity,
                    original_quantity=fill.quantity,
                    average_entry_price=fill.price,
                    realized_pnl=Decimal("0"),
                    protective_stop=None,
                    target_1=None,
                    target_2=None,
                    target_3=None,
                    target_1_quantity=None,
                    target_2_quantity=None,
                    target_3_quantity=None,
                    target_1_filled_quantity=Decimal("0"),
                    target_2_filled_quantity=Decimal("0"),
                    target_3_filled_quantity=Decimal("0"),
                    state="OPEN",
                    opened_at=fill.timestamp,
                    closed_at=None,
                )
                session.add(position)
            else:
                total_quantity = position.quantity + fill.quantity
                position.average_entry_price = ((position.quantity * position.average_entry_price) + notional) / total_quantity
                position.quantity = total_quantity
                position.original_quantity = (position.original_quantity or Decimal("0")) + fill.quantity
                position.state = "OPEN"
                position.closed_at = None
        else:
            position = await self._get_open_position(session, fill.symbol, lock=True)
            if position is None or position.quantity < fill.quantity:
                raise ValueError("Cannot sell more than the available position quantity.")
            proceeds = notional - fill.fee
            balance.available += proceeds
            position.quantity -= fill.quantity
            position.realized_pnl += proceeds - (fill.quantity * position.average_entry_price)
            if position.quantity <= 0:
                position.quantity = Decimal("0")
                position.state = "CLOSED"
                position.closed_at = fill.timestamp

        if balance.available < 0 or balance.reserved < 0:
            raise ValueError("Balance invariant violation.")
        await self._snapshot(session)
        return position.position_id

    async def _snapshot(self, session: Any) -> None:
        balance = await session.get(BalanceModel, self.quote_asset)
        if balance is None:
            return
        positions = list((await session.scalars(select(PositionModel))).all())
        open_positions = [position for position in positions if position.state == "OPEN"]
        open_exposure = sum((position.quantity * position.average_entry_price for position in open_positions), Decimal("0"))
        realized = sum((position.realized_pnl for position in positions), Decimal("0"))
        session.add(
            PortfolioSnapshotModel(
                snapshot_id=new_id("snap"),
                available_cash=balance.available,
                reserved_cash=balance.reserved,
                open_exposure=open_exposure,
                realized_pnl=realized,
                payload_json=_json({"positions": len(open_positions)}),
            )
        )

    async def _get_open_position(self, session: Any, symbol: str, *, lock: bool = False) -> PositionModel | None:
        statement = select(PositionModel).where(PositionModel.symbol == symbol, PositionModel.state == "OPEN")
        if lock:
            statement = statement.with_for_update()
        return cast(PositionModel | None, await session.scalar(statement))

    def _transition(
        self,
        session: Any,
        order_id: str,
        from_status: OrderStatus | None,
        to_status: OrderStatus,
        reason: str,
    ) -> None:
        session.add(
            OrderTransitionModel(
                transition_id=new_id("otx"),
                order_id=order_id,
                from_status=from_status.value if from_status else None,
                to_status=to_status.value,
                reason=reason,
                payload_json="{}",
            )
        )

    def _domain_order(self, order: OrderModel) -> Order:
        return Order(
            order_id=order.order_id,
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=Side(order.side),
            order_type=OrderType(order.order_type),
            quantity=order.quantity,
            quote_amount=order.quote_amount,
            limit_price=None,
            status=OrderStatus(order.status),
            created_at=order.created_at,
            decision_id=order.decision_id,
            simulated=order.simulated,
            filled_quantity=order.filled_quantity,
            average_fill_price=order.average_fill_price,
        )

    def _with_slippage(self, price: Decimal, side: Side, slippage_bps: Decimal) -> Decimal:
        multiplier = Decimal("1") + (slippage_bps / Decimal("10000"))
        if side is Side.SELL:
            multiplier = Decimal("1") - (slippage_bps / Decimal("10000"))
        return price * multiplier
