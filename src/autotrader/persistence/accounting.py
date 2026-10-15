"""Transactional paper accounting shared by the repository's public execution path.

Every financial transaction acquires the single account lock before subordinate
resources; no balance, order, position or target can be locked ahead of it.
All economic writes and projections commit together; dispatch follows durable intent.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from hashlib import sha256
from typing import Any, cast

from sqlalchemy import func, select, text

from autotrader.domain import (
    Order,
    OrderBook,
    OrderBookLevel,
    OrderStatus,
    OrderType,
    Position,
    RuntimeHealth,
    Side,
    TradingPair,
    new_id,
    quantize_down,
    timeframe_seconds,
    utc_now,
)
from autotrader.execution.postings import closing_posting
from autotrader.execution.pricing import (
    book_payload,
    observation_key,
    quote_execution,
    target_gross_floor,
)
from autotrader.execution.protection import trailing_update
from autotrader.execution.quality import ExecutionQualityEngine
from autotrader.failure_injection import failpoint
from autotrader.persistence.models import (
    AccountModel,
    BalanceModel,
    CapitalReservationModel,
    CooldownModel,
    EquitySnapshotModel,
    ExitIntentModel,
    ExitPlanModel,
    ExitTargetModel,
    FillModel,
    JournalEventModel,
    MarketFeature,
    MarketMarkModel,
    OrderModel,
    PositionModel,
    RiskPeriodModel,
    SystemIncidentModel,
    SystemStateModel,
)
from autotrader.persistence.retry import retry_economic
from autotrader.portfolio import Portfolio
from autotrader.risk import RiskEngine, RiskLimits

ZERO = Decimal("0")
SCALE = Decimal("0.000000000001")
TERMINAL = {"FILLED", "PARTIALLY_FILLED", "CANCELLED", "REJECTED", "EXPIRED"}


def exact(value: Decimal) -> Decimal:
    return value.quantize(SCALE, rounding=ROUND_DOWN)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class AccountingRepositoryMixin:
    # These attributes are supplied by PersistentTradingRepository.
    session_factory: Any
    quote_asset: str
    RUNTIME_STATE_KEY: str
    account_id = "paper-eur"
    mark_max_age_seconds = 90

    @staticmethod
    def strategy_cooldown_key(strategy_id:str)->str:
        return 'strategy:'+sha256(strategy_id.encode()).hexdigest()[:16]

    async def _lock_account(self, session: Any) -> AccountModel:
        account = await session.get(AccountModel, self.account_id, with_for_update=True)
        if account is None:
            raise ValueError("Portfolio is not initialized.")
        return cast(AccountModel, account)

    def _journal(self, session: Any, key: str, kind: str, *, cash: Decimal = ZERO,
                 reserved: Decimal = ZERO, quantity: Decimal = ZERO, cost: Decimal = ZERO,
                 pnl: Decimal = ZERO, position_id: str | None = None,
                 order_id: str | None = None, fill_id: str | None = None) -> None:
        session.add(JournalEventModel(ledger_event_id=new_id("jev"), event_key=key,
            account_id=self.account_id, currency=self.quote_asset, event_type=kind,
            cash_delta=exact(cash), reserved_delta=exact(reserved), quantity_delta=exact(quantity),
            cost_basis_delta=exact(cost), realized_pnl_delta=exact(pnl), position_id=position_id,
            order_id=order_id, fill_id=fill_id, reconciliation_state="CONFIRMED", payload_json="{}", created_at=utc_now()))

    async def initialize_portfolio(self, initial_cash: Decimal) -> None:
        if initial_cash != Decimal("500") or self.quote_asset != "EUR":
            raise ValueError("This paper account requires EUR 500 initial funding.")
        async with self.session_factory() as session, session.begin():
            if session.bind.dialect.name == "postgresql":
                await session.execute(text("SELECT pg_advisory_xact_lock(3400001)"))
            account = await session.get(AccountModel, self.account_id, with_for_update=True)
            if account is not None:
                return
            account = AccountModel(account_id=self.account_id, currency=self.quote_asset,
                                   initial_cash=initial_cash, control="RUNNING")
            session.add(account)
            await session.flush()
            balance = await session.get(BalanceModel, self.quote_asset, with_for_update=True)
            if balance is not None:
                # Never synthesize funding to hide unjournaled legacy activity.
                await self._health(session, RuntimeHealth.RECONCILIATION_REQUIRED, "legacy_balance_without_journal")
                return
            session.add(BalanceModel(asset=self.quote_asset, available=initial_cash, reserved=ZERO))
            self._journal(session, "funding:paper-eur", "INITIAL_FUNDING", cash=initial_cash)
            await self._period_changes(session, initial_cash, utc_now())
            session.add(EquitySnapshotModel(snapshot_id=new_id("eq"), account_id=self.account_id,
                        equity=initial_cash, timestamp=utc_now(), degraded=False))

    async def _health(self, session: Any, state: RuntimeHealth, reason: str) -> None:
        row = await session.get(SystemStateModel, self.RUNTIME_STATE_KEY)
        if row is not None and row.state == state.value and row.reason == reason:
            return
        if row is not None and row.state == "RECONCILIATION_REQUIRED" and state is not RuntimeHealth.RECONCILIATION_REQUIRED:
            return
        # Market outages and normal recovery cannot clear stronger persistent halts.
        if row is not None and row.state in {"RISK_HALTED", "RECONCILIATION_REQUIRED", "STOPPED", "RECOVERING"} and state in {RuntimeHealth.HEALTHY, RuntimeHealth.DATA_DEGRADED}:
            return
        if row is None:
            session.add(SystemStateModel(key=self.RUNTIME_STATE_KEY, state=state.value, reason=reason, payload_json="{}"))
        else:
            row.state, row.reason = state.value, reason
        session.add(SystemIncidentModel(incident_id=new_id("inc"), severity="ERROR" if state is not RuntimeHealth.HEALTHY else "INFO", status=state.value, message=reason, payload_json="{}"))

    async def record_mark(self, book: OrderBook) -> None:
        if book.mid is None or book.mid <= 0 or not book.mid.is_finite():
            raise ValueError("Invalid mark.")
        now = utc_now()
        if aware(book.timestamp) > now + timedelta(seconds=5) or now - aware(book.timestamp) > timedelta(seconds=self.mark_max_age_seconds):
            raise ValueError("Invalid mark timestamp.")
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            await self._mark(session, book)

    async def _mark(self, session: Any, book: OrderBook) -> None:
        row = await session.get(MarketMarkModel, book.symbol)
        if row is None:
            session.add(MarketMarkModel(symbol=book.symbol, price=book.mid, timestamp=book.timestamp, source=book.source))
        elif aware(book.timestamp) >= aware(row.timestamp):
            row.price, row.timestamp, row.source = book.mid, book.timestamp, book.source
        observed = await session.get(SystemStateModel, "book:" + book.symbol)
        if observed is None:
            session.add(SystemStateModel(key="book:" + book.symbol, state="OBSERVED", reason="mark_and_executable_quote",
                payload_json=json.dumps(book_payload(book))))
        elif aware(datetime.fromisoformat(json.loads(observed.payload_json)["timestamp"])) <= aware(book.timestamp):
            observed.payload_json = json.dumps(book_payload(book))
        await session.flush()

    async def _period_changes(self, session: Any, equity: Decimal, now: datetime) -> tuple[Decimal, Decimal]:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())
        changes = []
        for label, start in (("day", day_start), ("week", week_start)):
            key = f"{label}:{start.date()}"
            period = await session.get(RiskPeriodModel, key)
            if period is None:
                previous = await session.scalar(select(EquitySnapshotModel).where(
                    EquitySnapshotModel.timestamp <= start, EquitySnapshotModel.degraded.is_(False)
                ).order_by(EquitySnapshotModel.timestamp.desc()).limit(1))
                baseline = previous.equity if previous else equity
                period = RiskPeriodModel(period_id=key, account_id=self.account_id, start_equity=baseline)
                session.add(period)
                await session.flush()
            changes.append(equity - period.start_equity)
        return changes[0], changes[1]

    async def _valuation(self, session: Any, *, persist: bool = False) -> dict[str, str]:
        balance = await session.get(BalanceModel, self.quote_asset)
        if balance is None:
            raise ValueError("Missing quote balance.")
        positions = list((await session.scalars(select(PositionModel).where(PositionModel.state == "OPEN", PositionModel.quantity > 0))).all())
        now = utc_now()
        exposure, basis = ZERO, ZERO
        missing = []
        for position in positions:
            mark = await session.get(MarketMarkModel, position.symbol)
            basis += position.cost_basis
            if mark is None or (now - aware(mark.timestamp)).total_seconds() > self.mark_max_age_seconds or aware(mark.timestamp) > now + timedelta(seconds=5):
                missing.append(position.symbol)
            else:
                exposure += position.quantity * mark.price
        cash = balance.available + balance.reserved
        equity = cash + exposure
        daily, weekly = await self._period_changes(session, equity, now) if not missing else (ZERO, ZERO)
        if persist:
            if missing:
                await self._health(session, RuntimeHealth.DATA_DEGRADED, "stale_or_missing_portfolio_marks:" + ",".join(sorted(missing)))
            elif daily <= -Decimal("15") or weekly <= -Decimal("35"):
                await self._health(session, RuntimeHealth.RISK_HALTED, "equity_loss_limit_breached")
                pending = list((await session.scalars(select(OrderModel).where(OrderModel.side == "BUY", OrderModel.status.in_(["PENDING", "ACCEPTED"])))).all())
                for order in pending:
                    await self._cancel(session, order, "risk_halt_cancel_entry")
            else:
                await self._health(session, RuntimeHealth.HEALTHY, "fresh_portfolio_valuation")
            session.add(EquitySnapshotModel(snapshot_id=new_id("eq"), account_id=self.account_id,
                equity=exact(equity), timestamp=now, degraded=bool(missing)))
        realized = await session.scalar(select(func.sum(JournalEventModel.realized_pnl_delta))) or ZERO
        pending_count = await session.scalar(select(func.count()).select_from(OrderModel).where(OrderModel.status.in_(["PENDING", "ACCEPTED"]))) or 0
        orders = await session.scalar(select(func.count()).select_from(OrderModel)) or 0
        return {"initial_cash": "500", "cash": str(cash), "available_cash": str(balance.available),
            "reserved_cash": str(balance.reserved), "open_exposure": str(exact(exposure)) if not missing else "",
            "equity": str(exact(equity)) if not missing else "", "realized_pnl": str(realized),
            "unrealized_pnl": str(exact(exposure - basis)) if not missing else "",
            "daily_equity_change": str(daily) if not missing else "", "weekly_equity_change": str(weekly) if not missing else "",
            "valuation_degraded": str(bool(missing)).lower(), "missing_marks": ",".join(sorted(missing)),
            "positions": str(len(positions)), "orders": str(orders), "pending_orders": str(pending_count)}

    async def snapshot(self) -> dict[str, str]:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            result = await self._valuation(session, persist=True)
            row = await session.get(SystemStateModel, self.RUNTIME_STATE_KEY)
            account = await session.get(AccountModel, self.account_id)
            result["risk_state"] = row.state if row else "HEALTHY"
            result["control"] = account.control
            return result

    async def _entry_risk(self, session: Any, pair: TradingPair, quote: Decimal, price: Decimal,
                          stop: Decimal | None,execution_cost_bps:Decimal=Decimal(25),*,own_order:OrderModel|None=None) -> str | None:
        problems = await self._verify(session, Decimal("500"))
        if problems:
            await self._health(session, RuntimeHealth.RECONCILIATION_REQUIRED, ",".join(problems))
            return "reconciliation_required"
        valuation = await self._valuation(session, persist=True)
        account = await session.get(AccountModel, self.account_id)
        health = await session.get(SystemStateModel, self.RUNTIME_STATE_KEY)
        if account.control != "RUNNING":
            return "entries_paused:" + str(account.control)
        if health and health.state != "HEALTHY":
            return "runtime_not_healthy:" + str(health.state)
        if own_order is not None:
            promotion = await session.get(SystemStateModel, "research_entry_policy")
            if promotion:
                policy = json.loads(promotion.payload_json)
                strategy_id = json.loads(own_order.execution_json).get("strategy_id")
                if policy.get("require_validation") and strategy_id not in policy["allowed_strategy_ids"]:
                    return "strategy_not_approved_and_validated"
        if stop is None:
            return "missing_protective_stop"
        cooldown = await session.get(CooldownModel, pair.symbol)
        if cooldown and aware(cooldown.expires_at) > utc_now():
            return "symbol_cooldown"
        if own_order:
            strategy=json.loads(own_order.execution_json).get('strategy_id','ensemble-v3.4')
            strategy_cooldown=await session.get(CooldownModel,self.strategy_cooldown_key(strategy))
            if strategy_cooldown and aware(strategy_cooldown.expires_at)>utc_now():
                return 'strategy_cooldown'
        portfolio = Portfolio(Decimal(valuation["available_cash"])+(own_order.quote_amount if own_order else ZERO))
        for p in (await session.scalars(select(PositionModel).where(PositionModel.state.in_(["OPEN", "PENDING"])))).all():
            if own_order and p.position_id==own_order.position_id:
                continue
            mark=await session.get(MarketMarkModel,p.symbol)
            portfolio.positions[p.position_id] = Position(p.position_id, p.symbol, p.quantity, mark.price if mark else p.average_entry_price, p.opened_at)
            if p.symbol == pair.symbol:
                return "existing_position_or_pending_entry"
        pending = list((await session.scalars(select(OrderModel).where(OrderModel.side == "BUY", OrderModel.status.in_(["PENDING", "ACCEPTED"])))).all())
        for order in pending:
            if own_order and order.order_id==own_order.order_id:
                continue
            key=order.position_id or order.order_id
            portfolio.positions[key]=Position(key,order.symbol,order.quantity,
                order.quote_amount/order.quantity if order.quantity>0 else price,order.created_at)
        day = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
        entries = await session.scalar(select(func.count()).select_from(OrderModel).where(OrderModel.side == "BUY", OrderModel.created_at >= day, OrderModel.status.not_in(["REJECTED", "CANCELLED", "EXPIRED"]),OrderModel.order_id!=(own_order.order_id if own_order else ''))) or 0
        # Defaults are hard upper bounds; callers cannot relax the project policy.
        risk = RiskEngine(RiskLimits(planned_loss_cost_bps=max(Decimal(25),execution_cost_bps))).evaluate_entry(portfolio, pair, quote, price, stop,
            int(entries), Decimal(valuation["daily_equity_change"]), Decimal(valuation["weekly_equity_change"]))
        return None if risk.accepted else "risk_rejected:" + ",".join(risk.reasons)

    @retry_economic
    async def submit_order(self, pair: TradingPair, side: Side, order_type: OrderType,
            quantity: Decimal, quote_amount: Decimal, order_book: OrderBook, idempotency_key: str,
            decision_id: str | None = None, limit_price: Decimal | None = None,
            fee_bps: Decimal = Decimal("10"), slippage_bps: Decimal = Decimal("8"), *,
            position_id: str | None = None, exit_target_id: str | None = None,
            exit_reason: str = "MANUAL_EXIT", stop_loss: Decimal | None = None,
            targets: list[Decimal] | None = None) -> Order:
        if not idempotency_key or len(idempotency_key) > 64:
            raise ValueError("A stable intent key of at most 64 characters is required.")
        if not all(v.is_finite() for v in (quantity, quote_amount, fee_bps, slippage_bps)):
            raise ValueError("Non-finite order values.")
        failpoint("before_capital_reservation")
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            existing = await session.scalar(select(OrderModel).where(OrderModel.client_order_id == idempotency_key))
            if existing:
                if existing.account_id!=self.account_id:
                    raise ValueError('Legacy intention identity requires explicit remediation.')
                if existing.symbol != pair.symbol or existing.side != side.value:
                    raise ValueError("Idempotency key belongs to another intention.")
                order_id = existing.order_id
            else:
                quantity = quantize_down(quantity, pair.quantity_step)
                error = self._validate_execution(pair, order_book, quantity, fee_bps, slippage_bps)
                if order_type is OrderType.LIMIT and (limit_price is None or limit_price <= 0):
                    error = "invalid_limit_price"
                if side is Side.BUY and not error:
                    worst_ask=max(level.price for level in order_book.asks)*(1+slippage_bps/10000)
                    spread_cost=(order_book.spread or ZERO)/(order_book.mid or Decimal(1))*10000
                    error = await self._entry_risk(session, pair, quote_amount, worst_ask, stop_loss,2*fee_bps+2*slippage_bps+spread_cost)
                admission_quality = None
                if side is Side.BUY and not error:
                    admission_quality = ExecutionQualityEngine().evaluate(pair, order_book, quantity,
                        quote_amount, fee_bps, slippage_bps, targets or [])
                    if admission_quality.rejection_reasons:
                        error = "execution_quality:" + ",".join(admission_quality.rejection_reasons)
                position = None
                target = None
                if side is Side.SELL and not error:
                    position = await session.get(PositionModel, position_id, with_for_update=True) if position_id else await session.scalar(select(PositionModel).where(PositionModel.symbol == pair.symbol, PositionModel.state == "OPEN").with_for_update())
                    if position is None or position.symbol != pair.symbol or position.state != "OPEN" or position.account_id != self.account_id:
                        error = "position_not_open"
                    else:
                        position_id = position.position_id
                        if not await self._position_consistent(session,position):
                            error="position_reconciliation_required"
                            await self._health(session,RuntimeHealth.RECONCILIATION_REQUIRED,error)
                        if exit_reason in {"STOP", "TIME_EXIT", "MARKET_RISK", "FAILED_BREAKOUT", "EMERGENCY"}:
                            outstanding = list((await session.scalars(select(OrderModel).where(OrderModel.position_id == position_id, OrderModel.side == "SELL", OrderModel.status.in_(["PENDING", "ACCEPTED"])))).all())
                            for pending in outstanding:
                                await self._cancel(session, pending, "protective_exit_priority")
                        reserved = await session.scalar(select(func.sum(ExitIntentModel.reserved_quantity)).where(ExitIntentModel.position_id == position_id, ExitIntentModel.status == "OPEN")) or ZERO
                        if exit_reason in {"STOP","TIME_EXIT","MARKET_RISK","FAILED_BREAKOUT","EMERGENCY"}:
                            quantity=min(quantity,position.quantity-reserved)
                        if quantity > position.quantity - reserved:
                            error = "insufficient_unreserved_position_quantity"
                        if exit_target_id:
                            target = await session.get(ExitTargetModel, exit_target_id, with_for_update=True)
                            if target is None or target.position_id != position_id or exit_reason != "TAKE_PROFIT":
                                error = "invalid_target_identity"
                            elif quantity > target.remaining_quantity - target.reserved_quantity:
                                error = "insufficient_unreserved_target_quantity"
                            else:
                                # A target is a minimum NET unit realization, never a
                                # midpoint signal followed by an unrestricted market sell.
                                floor = target_gross_floor(target.target_price, fee_bps)
                                limit_price = max(limit_price or ZERO, floor)
                                order_type = OrderType.LIMIT
                        elif exit_reason == "TAKE_PROFIT":
                            error = "target_identity_required"
                order_id = new_id("ord")
                payload:dict[str,Any] = {"fee_bps": str(fee_bps), "slippage_bps": str(slippage_bps),
                    "rejection_reason": error,
                    "quantity_step": str(pair.quantity_step), "limit_price": str(limit_price) if limit_price else None,
                    "stop_loss": str(stop_loss) if stop_loss else None, "targets": [str(t) for t in targets or []],
                    "book": {"timestamp": order_book.timestamp.isoformat(), "source": order_book.source,
                        "bids": [[str(l.price), str(l.quantity)] for l in order_book.bids],
                        "asks": [[str(l.price), str(l.quantity)] for l in order_book.asks]}}
                primary_strategy="ensemble-v3.4"
                holding_seconds = None
                if admission_quality is not None:
                    payload["admission_quality"] = admission_quality.payload()
                if decision_id:
                    from autotrader.persistence.models import (
                        StrategySignalModel,
                        TradingDecisionModel,
                    )
                    decision_row=await session.get(TradingDecisionModel,decision_id)
                    if decision_row:
                        ids=json.loads(decision_row.payload_json).get('signal_ids',[])
                        strongest=await session.scalar(select(StrategySignalModel).where(StrategySignalModel.signal_id.in_(ids),StrategySignalModel.score>0).order_by(StrategySignalModel.score.desc(),StrategySignalModel.strategy_id).limit(1))
                        if strongest:
                            primary_strategy=strongest.strategy_id
                            evidence = json.loads(strongest.payload_json).get("evidence", {})
                            if evidence.get("strategy_version") == "4.0.0":
                                holding_seconds = int(evidence.get("holding_bars", 12)) * timeframe_seconds(str(evidence.get("timeframe", "5m")))
                hours={"A_VOLUME_ACCUMULATION":12,"B_VOLATILITY_COMPRESSION":24,"C_BREAKOUT_RETEST":8,"D_MOMENTUM_ACCELERATION":6,"G_RELATIVE_STRENGTH":8,"H_LIQUIDITY_ORDER_BOOK":4}.get(primary_strategy,24)
                if side is Side.BUY and not error:
                    promotion = await session.get(SystemStateModel, "research_entry_policy")
                    if promotion:
                        policy = json.loads(promotion.payload_json)
                        if policy.get("require_validation") and primary_strategy not in policy["allowed_strategy_ids"]:
                            error = "strategy_not_approved_and_validated"
                            payload["rejection_reason"] = error
                    strategy_cooldown=await session.get(CooldownModel,self.strategy_cooldown_key(primary_strategy))
                    if strategy_cooldown and aware(strategy_cooldown.expires_at)>utc_now():
                        error='strategy_cooldown'
                        payload['rejection_reason']=error
                payload.update(strategy_id=primary_strategy,holding_hours=hours,holding_seconds=holding_seconds)
                if side is Side.BUY and not error:
                    position_id = new_id("pos")
                    position = PositionModel(position_id=position_id, account_id=self.account_id, symbol=pair.symbol,
                        quantity=ZERO, original_quantity=ZERO, average_entry_price=ZERO, cost_basis=ZERO,
                        realized_pnl=ZERO, state="PENDING", opened_at=utc_now(), initial_stop=stop_loss,
                        protective_stop=stop_loss)
                    session.add(position)
                    await session.flush()
                intent = None
                if side is Side.SELL and not error:
                    plan = await session.scalar(select(ExitPlanModel).where(ExitPlanModel.position_id == position_id))
                    intent = ExitIntentModel(exit_intent_id=new_id("exit"), position_id=position_id,
                        exit_plan_id=plan.exit_plan_id if plan else None, exit_target_id=exit_target_id,
                        reason=exit_reason, quantity=quantity, reserved_quantity=quantity,
                        status="OPEN", idempotency_key=idempotency_key)
                    session.add(intent)
                    if target:
                        target.reserved_quantity += quantity
                    await session.flush()
                row = OrderModel(order_id=order_id, account_id=self.account_id, position_id=position_id,
                    exit_intent_id=intent.exit_intent_id if intent else None, exit_target_id=exit_target_id if intent else None,
                    decision_id=decision_id, client_order_id=idempotency_key, symbol=pair.symbol, side=side.value,
                    order_type=order_type.value, status="REJECTED" if error else "PENDING", quantity=quantity,
                    quote_amount=quote_amount, filled_quantity=ZERO, simulated=True, execution_json=json.dumps(payload), created_at=utc_now())
                session.add(row)
                await session.flush()
                self._transition(session, order_id, None, OrderStatus(row.status), error or "durable_intent")
                if side is Side.BUY and not error:
                    balance = await session.get(BalanceModel, self.quote_asset, with_for_update=True)
                    balance.available -= quote_amount
                    balance.reserved += quote_amount
                    session.add(CapitalReservationModel(reservation_id=new_id("res"), order_id=order_id,
                        asset=self.quote_asset, amount=quote_amount, status="OPEN", idempotency_key=idempotency_key))
                    self._journal(session, f"reserve:{order_id}", "CASH_RESERVATION", reserved=quote_amount, order_id=order_id)
        failpoint("after_reservation_persistence")
        failpoint("before_order_dispatch")
        return await self.dispatch_order(order_id)

    def _validate_execution(self, pair: TradingPair, book: OrderBook, quantity: Decimal,
                            fee: Decimal, slippage: Decimal) -> str | None:
        if pair.quote_asset != "EUR" or pair.status.lower() != "active":
            return "unsupported_market"
        if quantity <= 0 or quantity < pair.min_order_base or (pair.max_order_base is not None and quantity > pair.max_order_base):
            return "invalid_quantity"
        if fee < 0 or fee >= 10000 or slippage < 0 or slippage >= 10000:
            return "invalid_execution_costs"
        if book.symbol != pair.symbol or not book.bids or not book.asks:
            return "invalid_order_book"
        if any(not l.price.is_finite() or not l.quantity.is_finite() or l.price <= 0 or l.quantity <= 0 for l in (*book.bids, *book.asks)):
            return "invalid_book_levels"
        age = (utc_now() - aware(book.timestamp)).total_seconds()
        if age > self.mark_max_age_seconds or age < -5:
            return "stale_or_future_order_book"
        if book.best_bid is not None and book.best_ask is not None and book.best_bid > book.best_ask:
            return "crossed_order_book"
        try:
            quote_execution(book, Side.SELL, quantity, quantity_step=pair.quantity_step,
                            fee_bps=fee, slippage_bps=slippage)
        except ValueError as exc:
            return str(exc)
        return None

    def _stored_book(self, row: OrderModel, payload: dict[str, Any]) -> OrderBook:
        raw = payload["book"]
        return OrderBook(row.symbol, datetime.fromisoformat(raw["timestamp"]),
            tuple(OrderBookLevel(Decimal(p), Decimal(q)) for p, q in raw["bids"]),
            tuple(OrderBookLevel(Decimal(p), Decimal(q)) for p, q in raw["asks"]), raw["source"])

    @retry_economic
    async def dispatch_order(self, order_id: str, order_book: OrderBook | None = None) -> Order:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            row = await session.get(OrderModel, order_id, with_for_update=True)
            if row is None:
                raise ValueError("Unknown order.")
            if row.status in TERMINAL:
                return self._domain_order(row)
            if row.account_id!=self.account_id or row.position_id is None:
                raise ValueError('Unresolved legacy order cannot be automatically dispatched.')
            payload = json.loads(row.execution_json)
            book = self._stored_book(row, payload)
            if order_book is not None and order_book!=book:
                raise ValueError("Dispatch cannot replace the risk-checked durable market observation.")
            pair = TradingPair(row.symbol, row.symbol.split("-")[0], "EUR", quantity_step=Decimal(payload["quantity_step"]))
            fee_rate, slippage = Decimal(payload["fee_bps"]) / 10000, Decimal(payload["slippage_bps"]) / 10000
            error = self._validate_execution(pair, book, row.quantity, fee_rate * 10000, slippage * 10000)
            if error:
                await self._cancel(session, row, error)
                return self._domain_order(row)
            if row.side == "BUY":
                await self._valuation(session, persist=True)
                health = await session.get(SystemStateModel, self.RUNTIME_STATE_KEY)
                account = await session.get(AccountModel, self.account_id)
                if row.status in TERMINAL or account.control != "RUNNING" or (health and health.state != "HEALTHY"):
                    if row.status not in TERMINAL:
                        await self._cancel(session, row, "entry_halted_before_dispatch")
                    return self._domain_order(row)
                stop=Decimal(payload['stop_loss']) if payload['stop_loss'] else None
                worst=max(l.price for l in book.asks)*(1+slippage)
                spread_bps=(book.spread or ZERO)/(book.mid or Decimal(1))*10000
                risk_error=await self._entry_risk(session,pair,row.quote_amount,worst,stop,
                    2*fee_rate*10000+2*slippage*10000+spread_bps,own_order=row)
                if risk_error or row.status in TERMINAL:
                    if row.status not in TERMINAL:
                        await self._cancel(session,row,risk_error or 'risk_halt')
                    return self._domain_order(row)
            else:
                position=await session.get(PositionModel,row.position_id,with_for_update=True)
                if position is None or not await self._position_consistent(session,position):
                    await self._health(session,RuntimeHealth.RECONCILIATION_REQUIRED,'exit_projection_mismatch')
                    await self._cancel(session,row,'exit_projection_mismatch')
                    return self._domain_order(row)
            row.status = "ACCEPTED"
            self._transition(session, row.order_id, OrderStatus.PENDING, OrderStatus.ACCEPTED, "paper_dispatch")
            failpoint("after_order_dispatch")
            # Account lock serializes consumption across intents and process restarts.
            # Only an actually different observation can supply new paper liquidity.
            liquidity_key = observation_key(book)
            liquidity = await session.get(SystemStateModel, liquidity_key)
            usage = json.loads(liquidity.payload_json) if liquidity else {"BUY": {}, "SELL": {}}
            consumed = {int(i): Decimal(q) for i, q in usage[row.side].items()}
            limit = Decimal(payload["limit_price"]) if payload["limit_price"] else None
            step = pair.quantity_step
            quote = quote_execution(book, Side(row.side), row.quantity, quantity_step=step,
                fee_bps=fee_rate * 10000, slippage_bps=slippage * 10000, limit_price=limit,
                quote_budget=row.quote_amount if row.side == "BUY" else None, consumed=consumed)
            payload["execution_quality"] = quote.payload()
            row.execution_json = json.dumps(payload)
            filled, notional = quote.fillable_quantity, quote.gross_notional
            if filled <= 0:
                await self._cancel(session, row, "ioc_no_fill")
                return self._domain_order(row)
            for index, qty in quote.allocations:
                usage[row.side][str(index)] = str(consumed.get(index, ZERO) + qty)
            if liquidity is None:
                session.add(SystemStateModel(key=liquidity_key, state="CONSUMED",
                    reason="finite_observation_depth", payload_json=json.dumps(usage)))
            else:
                liquidity.payload_json = json.dumps(usage)
            price, fee = quote.vwap, quote.fee
            position = await session.get(PositionModel, row.position_id, with_for_update=True)
            balance = await session.get(BalanceModel, self.quote_asset, with_for_update=True)
            fill_id = "fill_" + row.order_id.removeprefix("ord_")
            failpoint("before_fill_persistence")
            fill = FillModel(fill_id=fill_id, order_id=row.order_id, account_id=self.account_id,
                position_id=row.position_id, exit_intent_id=row.exit_intent_id, exit_target_id=row.exit_target_id,
                attribution_status="CONFIRMED", symbol=row.symbol, side=row.side, quantity=filled,
                price=price, fee=fee, simulated=True, created_at=utc_now())
            session.add(fill)
            await session.flush()
            failpoint("after_fill_persistence")
            failpoint("before_ledger_posting")
            if row.side == "BUY":
                spend = notional + fee
                balance.available -= spend  # release below offsets reserved cash movement
                position.quantity = filled
                position.original_quantity = filled
                position.average_entry_price = price
                position.cost_basis = spend
                position.highest_price = book.best_bid
                position.state = "OPEN"
                position.expires_at = utc_now() + timedelta(seconds=payload.get("holding_seconds") or payload.get('holding_hours',24)*3600)
                self._journal(session, f"buy:{fill_id}", "BUY_FILL", cash=-notional, quantity=filled,
                    cost=notional, position_id=position.position_id, order_id=row.order_id, fill_id=fill_id)
                self._journal(session, f"fee:{fill_id}", "FEE", cash=-fee, cost=fee,
                    position_id=position.position_id, order_id=row.order_id, fill_id=fill_id)
                await self._release(session, row)
                if payload["stop_loss"]:
                    await self._create_plan(session, position, Decimal(payload["stop_loss"]), [Decimal(t) for t in payload["targets"]], step,
                        strategy_id=payload.get('strategy_id','ensemble-v3.4'),holding_hours=payload.get('holding_hours',24),
                        holding_seconds=payload.get("holding_seconds"))
            else:
                if position is None or filled > position.quantity:
                    raise ValueError("Exit would oversell; transaction rolled back.")
                posting = closing_posting(position.quantity, position.cost_basis, filled, notional, fee)
                released_basis = posting.released_basis
                position.quantity = posting.remaining_quantity
                position.cost_basis = posting.remaining_basis
                pnl = posting.realized_pnl
                position.realized_pnl += pnl
                balance.available += posting.cash_credit
                self._journal(session, f"sell:{fill_id}", "SELL_FILL", cash=notional, quantity=-filled,
                    cost=-released_basis, pnl=notional - released_basis, position_id=position.position_id, order_id=row.order_id, fill_id=fill_id)
                self._journal(session, f"fee:{fill_id}", "FEE", cash=-fee, pnl=-fee,
                    position_id=position.position_id, order_id=row.order_id, fill_id=fill_id)
                await self._release(session, row)
                if row.exit_target_id:
                    target = await session.get(ExitTargetModel, row.exit_target_id, with_for_update=True)
                    target.filled_quantity += filled
                    target.remaining_quantity = target.original_planned_quantity - target.filled_quantity
                    target.status = "COMPLETED" if target.remaining_quantity == 0 else "PARTIAL"
                    setattr(position, f"target_{target.target_number}_filled_quantity", target.filled_quantity)
                    failpoint("during_target_completion")
                if position.quantity == 0:
                    position.state, position.closed_at = "CLOSED", utc_now()
                    plan=await session.scalar(select(ExitPlanModel).where(ExitPlanModel.position_id==position.position_id))
                    strategy=plan.strategy_id if plan else 'ensemble-v3.4'
                    cooldown = await session.get(CooldownModel, row.symbol)
                    if cooldown is None:
                        session.add(CooldownModel(symbol=row.symbol, expires_at=utc_now() + timedelta(minutes=30), strategy_id=strategy))
                    else:
                        cooldown.expires_at = utc_now() + timedelta(minutes=30)
                        cooldown.strategy_id=strategy
                    key=self.strategy_cooldown_key(strategy)
                    strategy_cooldown=await session.get(CooldownModel,key)
                    if strategy_cooldown:
                        strategy_cooldown.expires_at=utc_now()+timedelta(minutes=5)
                    else:
                        session.add(CooldownModel(symbol=key,strategy_id=strategy,expires_at=utc_now()+timedelta(minutes=5)))
                if row.exit_intent_id:
                    intent = await session.get(ExitIntentModel, row.exit_intent_id)
                    if intent.reason == "STOP":
                        failpoint("during_protective_stop_processing")
            row.filled_quantity = filled
            row.average_fill_price = price
            row.status = "FILLED" if filled >= row.quantity else "PARTIALLY_FILLED"
            await self._mark(session, book)
            self._transition(session, row.order_id, OrderStatus.ACCEPTED, OrderStatus(row.status), "confirmed_paper_fill_ioc")
            await session.flush()
            failpoint("after_fill_and_ledger_flush")
            result = self._domain_order(row)
        failpoint("after_ledger_commit")
        return result

    async def _release(self, session: Any, row: OrderModel) -> None:
        if row.side == "BUY":
            reservation = await session.scalar(select(CapitalReservationModel).where(CapitalReservationModel.order_id == row.order_id, CapitalReservationModel.status == "OPEN"))
            if reservation:
                balance = await session.get(BalanceModel, self.quote_asset, with_for_update=True)
                balance.reserved -= reservation.amount
                balance.available += reservation.amount
                reservation.status = "RELEASED"
                self._journal(session, f"release:{row.order_id}", "RESERVATION_RELEASE", reserved=-reservation.amount, order_id=row.order_id)
        elif row.exit_intent_id:
            intent = await session.get(ExitIntentModel, row.exit_intent_id)
            if intent and intent.status == "OPEN":
                if intent.exit_target_id:
                    target = await session.get(ExitTargetModel, intent.exit_target_id)
                    target.reserved_quantity -= intent.reserved_quantity
                intent.reserved_quantity, intent.status = ZERO, "CLOSED"

    async def _position_consistent(self,session:Any,p:PositionModel)->bool:
        rows=(await session.scalars(select(FillModel).where(FillModel.position_id==p.position_id,FillModel.attribution_status=='CONFIRMED'))).all()
        actual=sum((f.quantity if f.side=='BUY' else -f.quantity for f in rows),ZERO)
        basis=await session.scalar(select(func.sum(JournalEventModel.cost_basis_delta)).where(JournalEventModel.position_id==p.position_id)) or ZERO
        return bool(p.account_id==self.account_id and p.quantity==actual and actual>=0 and abs(p.cost_basis-basis)<=SCALE)

    async def _cancel(self, session: Any, row: OrderModel, reason: str) -> None:
        if row.status in TERMINAL:
            return
        failpoint("during_cancellation")
        previous = OrderStatus(row.status)
        await self._release(session, row)
        row.status = "CANCELLED"
        payload=json.loads(row.execution_json)
        payload['rejection_reason']=reason
        row.execution_json=json.dumps(payload)
        if row.side == "BUY" and row.position_id:
            p = await session.get(PositionModel, row.position_id)
            if p and p.state == "PENDING":
                p.state, p.closed_at = "CANCELLED", utc_now()
        self._transition(session, row.order_id, previous, OrderStatus.CANCELLED, reason)

    async def recover_pending_orders(self) -> list[str]:
        async with self.session_factory() as session:
            ids = list((await session.scalars(select(OrderModel.order_id).where(OrderModel.account_id==self.account_id,OrderModel.position_id.is_not(None),OrderModel.status.in_(["PENDING", "ACCEPTED"])).order_by(OrderModel.created_at))).all())
        for order_id in ids:
            await self.dispatch_order(order_id)
        return ids

    async def _create_plan(self, session: Any, p: PositionModel, stop: Decimal | None,
                           targets: list[Decimal], step: Decimal,*,strategy_id:str='ensemble-v3.4',holding_hours:int=24,
                           holding_seconds:int|None=None) -> None:
        existing = await session.scalar(select(ExitPlanModel).where(ExitPlanModel.position_id == p.position_id))
        if existing and await session.scalar(select(func.count()).select_from(ExitTargetModel).where(ExitTargetModel.exit_plan_id == existing.exit_plan_id)):
            return
        p.protective_stop, p.initial_stop = stop, stop
        plan = existing or ExitPlanModel(exit_plan_id=new_id("plan"), position_id=p.position_id,
            strategy_id=strategy_id, settings_json=json.dumps({"holding_hours": holding_hours,
                "holding_seconds": holding_seconds or holding_hours*3600, "cooldown_minutes": 30, "stop_priority": True,
                "trailing_policy":"v4-volatility-bid-trailing-1"}))
        session.add(plan)
        await session.flush()
        from autotrader.persistence.repository import _default_target_quantities
        quantities = _default_target_quantities(p.original_quantity or p.quantity, step, len(targets[:3]))
        for number, (price, qty) in enumerate(zip(targets[:3], quantities, strict=True), 1):
            session.add(ExitTargetModel(target_id=new_id("tp"), position_id=p.position_id,
                exit_plan_id=plan.exit_plan_id, target_number=number, target_price=price,
                original_planned_quantity=qty, filled_quantity=ZERO, reserved_quantity=ZERO,
                remaining_quantity=qty, status="PENDING"))
            setattr(p, f"target_{number}", price)
            setattr(p, f"target_{number}_quantity", qty)
            setattr(p, f"target_{number}_filled_quantity", ZERO)

    async def set_position_exit_plan(self, symbol: str, stop_loss: Decimal | None,
                                     targets: list[Decimal], quantity_step: Decimal = Decimal("0.00000001")) -> None:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            p = await session.scalar(select(PositionModel).where(PositionModel.symbol == symbol, PositionModel.state == "OPEN").with_for_update())
            if p:
                await self._create_plan(session, p, stop_loss, targets, quantity_step)

    async def list_targets(self, position_id: str | None = None) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            stmt = select(ExitTargetModel).order_by(ExitTargetModel.created_at, ExitTargetModel.target_number)
            if position_id:
                stmt = stmt.where(ExitTargetModel.position_id == position_id)
            rows = (await session.scalars(stmt)).all()
            return [{c.name: str(getattr(row, c.name)) for c in ExitTargetModel.__table__.columns} for row in rows]

    async def list_positions(self) -> list[Position]:
        async with self.session_factory() as session:
            rows = (await session.scalars(select(PositionModel).where(PositionModel.state.in_(["OPEN", "CLOSED"])).order_by(PositionModel.created_at))).all()
            result = []
            for p in rows:
                targets = list((await session.scalars(select(ExitTargetModel).where(ExitTargetModel.position_id == p.position_id).order_by(ExitTargetModel.target_number))).all())
                active = [t for t in targets if t.remaining_quantity > 0]
                plan = await session.scalar(select(ExitPlanModel).where(ExitPlanModel.position_id == p.position_id))
                result.append(Position(position_id=p.position_id, symbol=p.symbol, quantity=p.quantity,
                    average_entry_price=p.average_entry_price, opened_at=p.opened_at, realized_pnl=p.realized_pnl,
                    protective_stop=p.protective_stop, take_profit_targets=[t.target_price for t in active],
                    original_quantity=p.original_quantity, target_quantities=[t.original_planned_quantity for t in active],
                    target_filled_quantities=[t.filled_quantity for t in active], target_ids=[t.target_id for t in active],
                    exit_plan_id=plan.exit_plan_id if plan else None, cost_basis=p.cost_basis, highest_price=p.highest_price,
                    initial_stop=p.initial_stop, trailing_distance=p.trailing_distance, expires_at=p.expires_at,
                    last_monitored_at=p.last_monitored_at, closed_at=p.closed_at, account_id=p.account_id))
            return result

    async def sync_exit_plan_from_fills(self, symbol: str) -> None:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            targets = (await session.scalars(select(ExitTargetModel).join(PositionModel, PositionModel.position_id == ExitTargetModel.position_id).where(PositionModel.symbol == symbol))).all()
            for target in targets:
                filled = await session.scalar(select(func.sum(FillModel.quantity)).where(
                    FillModel.exit_target_id == target.target_id, FillModel.position_id == target.position_id,
                    FillModel.side == "SELL", FillModel.attribution_status == "CONFIRMED")) or ZERO
                if filled > target.original_planned_quantity:
                    raise ValueError("Target overfilled.")
                target.filled_quantity = filled
                target.remaining_quantity = target.original_planned_quantity - filled
                target.status = "COMPLETED" if target.remaining_quantity == 0 else ("PARTIAL" if filled else "PENDING")
                p = await session.get(PositionModel, target.position_id)
                setattr(p, f"target_{target.target_number}_filled_quantity", filled)

    async def advance_position_target(self, symbol: str, hit_target: Decimal) -> None:
        # Compatibility: only confirmed target-linked fills may advance progress.
        await self.sync_exit_plan_from_fills(symbol)

    async def protection_watch(self, position_id: str, reason: str | None) -> None:
        """Persist inability to monitor protection; never invent an executable quote."""
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            p = await session.get(PositionModel, position_id)
            if p is None or p.state != "OPEN":
                return
            key = "protect:" + position_id
            row = await session.get(SystemStateModel, key)
            state = "WAITING_FOR_DATA" if reason else "MONITORING"
            if row and row.state == state and row.reason == (reason or "fresh_executable_book"):
                return
            payload = json.dumps({"position_id": position_id, "symbol": p.symbol,
                "quantity": str(p.quantity), "protective_stop": str(p.protective_stop),
                "observed_at": utc_now().isoformat()})
            if row is None:
                row = SystemStateModel(key=key, state=state, reason=reason or "fresh_executable_book", payload_json=payload)
                session.add(row)
            else:
                row.state, row.reason, row.payload_json = state, reason or "fresh_executable_book", payload
            if reason:
                session.add(SystemIncidentModel(incident_id=new_id("inc"), severity="CRITICAL",
                    status="WAITING_FOR_DATA", message="protection_data_unavailable:" + reason, payload_json=payload))
                await self._health(session, RuntimeHealth.DATA_DEGRADED, "protection_data_unavailable:" + p.symbol)

    async def update_position_monitor(self, position_id: str, price: Decimal, *,
                                      fee_bps: Decimal = Decimal(10), slippage_bps: Decimal = Decimal(8)) -> None:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            p = await session.get(PositionModel, position_id, with_for_update=True)
            if p is None or p.state != "OPEN":
                return
            p.highest_price = max(p.highest_price or price, price)
            p.last_monitored_at = utc_now()
            target1 = await session.scalar(select(ExitTargetModel).where(ExitTargetModel.position_id == position_id, ExitTargetModel.target_number == 1))
            if target1 and target1.status == "COMPLETED":
                previous_stop = p.protective_stop
                feature = await session.scalar(select(MarketFeature).where(MarketFeature.symbol == p.symbol,
                    MarketFeature.timestamp <= utc_now()).order_by(MarketFeature.timestamp.desc()).limit(1))
                atr = None
                if feature and feature.data_quality == "GOOD" and (utc_now() - aware(feature.timestamp)).total_seconds() <= 900:
                    raw_atr = json.loads(feature.payload_json).get("atr")
                    atr = Decimal(raw_atr) if raw_atr else None
                distance = p.trailing_distance or max(p.average_entry_price - (p.initial_stop or p.average_entry_price),
                    p.average_entry_price * Decimal(".005"))
                update = trailing_update(previous_stop=p.protective_stop or ZERO, highest_bid=p.highest_price,
                    basis=p.cost_basis, quantity=p.quantity, distance=distance, atr=atr,
                    fee_bps=fee_bps, slippage_bps=slippage_bps)
                p.trailing_distance, p.protective_stop = update.distance, update.stop
                if previous_stop != p.protective_stop:
                    session.add(SystemIncidentModel(incident_id=new_id("inc"), severity="INFO",
                        status="STOP_UPDATED", message="monotonic_bid_trailing_stop",
                        payload_json=json.dumps({"position_id": position_id, "old_stop": str(previous_stop),
                            "new_stop": str(p.protective_stop), "executable_bid": str(price),
                            "distance": str(update.distance), "observed_atr": str(atr),
                            "breakeven_bid": str(update.breakeven_bid), "fee_bps": str(fee_bps),
                            "slippage_bps": str(slippage_bps), "policy": "v4-volatility-bid-trailing-1"})))

    async def realized_pnl_since(self, since: datetime) -> Decimal:
        async with self.session_factory() as session:
            return await session.scalar(select(func.sum(JournalEventModel.realized_pnl_delta)).where(JournalEventModel.created_at >= since)) or ZERO

    async def verify_invariants(self, initial_cash: Decimal) -> list[str]:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            return await self._verify(session, initial_cash)

    async def _verify(self, session: Any, initial_cash: Decimal) -> list[str]:
        problems: list[str] = []
        balance = await session.get(BalanceModel, self.quote_asset)
        if balance is None:
            return ["missing_quote_balance"]
        fills = list((await session.scalars(select(FillModel))).all())
        events = list((await session.scalars(select(JournalEventModel))).all())
        if any(f.attribution_status != "CONFIRMED" or not f.position_id for f in fills):
            problems.append("unresolved_legacy_fill_attribution")
        funding = sum((e.cash_delta for e in events if e.event_type == "INITIAL_FUNDING"), ZERO)
        if funding != initial_cash:
            problems.append("missing_or_incorrect_initial_funding")
        cash = sum((e.cash_delta for e in events), ZERO)
        reserved = sum((e.reserved_delta for e in events), ZERO)
        if abs(balance.available + balance.reserved - cash) > SCALE:
            problems.append("cash_balance_does_not_match_journal_replay")
        if reserved != balance.reserved:
            problems.append("reserved_cash_does_not_match_journal_replay")
        if balance.available < 0 or balance.reserved < 0:
            problems.append("negative_cash")
        open_reserved = await session.scalar(select(func.sum(CapitalReservationModel.amount)).where(CapitalReservationModel.status == "OPEN")) or ZERO
        if open_reserved != reserved:
            problems.append("reserved_cash_does_not_match_open_reservations")
        for p in (await session.scalars(select(PositionModel))).all():
            pf = [f for f in fills if f.position_id == p.position_id]
            qty = sum((f.quantity if f.side == "BUY" else -f.quantity for f in pf), ZERO)
            journal_qty = sum((e.quantity_delta for e in events if e.position_id == p.position_id), ZERO)
            basis = sum((e.cost_basis_delta for e in events if e.position_id == p.position_id), ZERO)
            pnl = sum((e.realized_pnl_delta for e in events if e.position_id == p.position_id), ZERO)
            if p.quantity < 0 or p.quantity != qty or qty != journal_qty:
                problems.append(f"position_quantity_does_not_match_fill_replay:{p.position_id}")
            if abs(p.cost_basis - basis) > SCALE or abs(p.realized_pnl - pnl) > SCALE:
                problems.append(f"position_cost_or_pnl_does_not_match_journal:{p.position_id}")
            exit_reserved = await session.scalar(select(func.sum(ExitIntentModel.reserved_quantity)).where(ExitIntentModel.position_id == p.position_id, ExitIntentModel.status == "OPEN")) or ZERO
            if exit_reserved > p.quantity or exit_reserved < 0:
                problems.append(f"invalid_exit_reservations:{p.position_id}")
        for fill in fills:
            linked = [e for e in events if e.fill_id == fill.fill_id]
            expected = exact(fill.quantity * fill.price) * (-1 if fill.side == "BUY" else 1) - fill.fee
            if sum((e.cash_delta for e in linked), ZERO) != expected:
                problems.append(f"fill_cash_does_not_match_journal:{fill.fill_id}")
            if fill.side == "SELL" and fill.attribution_status == "CONFIRMED":
                intent = await session.get(ExitIntentModel, fill.exit_intent_id) if fill.exit_intent_id else None
                if intent is None or intent.position_id != fill.position_id or intent.exit_target_id != fill.exit_target_id:
                    problems.append(f"invalid_exit_identity:{fill.fill_id}")
        for target in (await session.scalars(select(ExitTargetModel))).all():
            actual = sum((f.quantity for f in fills if f.exit_target_id == target.target_id and f.position_id == target.position_id and f.attribution_status == "CONFIRMED"), ZERO)
            if actual != target.filled_quantity or target.remaining_quantity != target.original_planned_quantity - actual:
                problems.append(f"target_progress_does_not_match_linked_fills:{target.target_id}")
        return problems

    async def set_control(self, action: str) -> str:
        values = {"start": "RUNNING", "resume": "RUNNING", "pause": "PAUSED", "stop": "STOPPED", "emergency": "EMERGENCY"}
        if action not in values:
            raise ValueError("Unknown control.")
        async with self.session_factory() as session, session.begin():
            account = await self._lock_account(session)
            if action in {"start", "resume"}:
                if await self._verify(session, account.initial_cash):
                    raise ValueError("Reconciliation required.")
                valuation = await self._valuation(session, persist=True)
                health = await session.get(SystemStateModel, self.RUNTIME_STATE_KEY)
                if health and health.state not in {"HEALTHY", "STOPPED"}:
                    raise ValueError("Explicit risk recovery required: " + health.state)
                if valuation["valuation_degraded"] == "true":
                    raise ValueError("Fresh valuation required.")
                if health and health.state == "STOPPED":
                    health.state, health.reason = "HEALTHY", "operator_resume"
            account.control = values[action]
            if action in {"stop", "emergency"}:
                await self._health(session, RuntimeHealth.STOPPED, "operator_" + action)
            if action in {"pause", "stop", "emergency"}:
                for order in (await session.scalars(select(OrderModel).where(OrderModel.side == "BUY", OrderModel.status.in_(["PENDING", "ACCEPTED"])))).all():
                    await self._cancel(session, order, "operator_" + action)
            return account.control

    # Supplied by the repository; declarations provide static typing for the mixin.
    def _transition(self, session: Any, order_id: str, from_status: OrderStatus | None, to_status: OrderStatus, reason: str) -> None:
        raise NotImplementedError

    def _domain_order(self, order: OrderModel) -> Order:
        raise NotImplementedError
