from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from autotrader.domain import (
    AIAssessment,
    Order,
    OrderStatus,
    OrderType,
    RiskEvaluation,
    RuntimeHealth,
    Side,
    StrategySignal,
    TradingDecision,
    new_id,
    quantize_down,
    utc_now,
)
from autotrader.persistence.accounting import AccountingRepositoryMixin
from autotrader.persistence.ai_budget import AIBudgetRepositoryMixin
from autotrader.persistence.models import (
    AccountModel,
    AIAssessmentModel,
    EquitySnapshotModel,
    ExitIntentModel,
    FillModel,
    JournalEventModel,
    MarketCandle,
    MarketFeature,
    NewsEvent,
    OrderModel,
    OrderTransitionModel,
    PositionModel,
    RiskEvaluationModel,
    StrategySignalModel,
    StrategyVersionModel,
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


class PersistentTradingRepository(AccountingRepositoryMixin, AIBudgetRepositoryMixin):
    RUNTIME_STATE_KEY = "runtime_health"

    def __init__(self, session_factory: async_sessionmaker[Any], quote_asset: str = "EUR") -> None:
        self.session_factory = session_factory
        self.quote_asset = quote_asset

    async def worker_heartbeat(self, frame_id: str | None = None,*,key:str="worker") -> None:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            row = await session.get(SystemStateModel, key)
            import os
            payload = _json({"frame_id": frame_id, "heartbeat": utc_now().isoformat(),
                'process_id':os.getpid(),'parent_process_id':os.getppid()})
            if row is None:
                session.add(SystemStateModel(key=key, state="RUNNING", reason="cycle_completed", payload_json=payload))
            else:
                row.payload_json = payload
                row.updated_at = utc_now()

    async def last_worker_frame(self) -> str | None:
        async with self.session_factory() as session:
            row = await session.get(SystemStateModel, "worker")
            return json.loads(row.payload_json).get("frame_id") if row else None

    async def reserve_public_request(self,family:str)->float:
        from datetime import timedelta

        from autotrader.persistence.accounting import aware
        key='public_rate:'+sha256(family.encode()).hexdigest()[:24]
        async with self.session_factory() as session,session.begin():
            await self._lock_account(session)
            row=await session.get(SystemStateModel,key)
            now=utc_now()
            if row:
                next_at=aware(datetime.fromisoformat(json.loads(row.payload_json)['next_at']))
                delay=(next_at-now).total_seconds()
                if delay>0:
                    return delay
                row.payload_json=_json({'next_at':(now+timedelta(seconds=1)).isoformat()})
            else:
                session.add(SystemStateModel(key=key,state='RATE_LIMIT',reason='one_public_request_per_second',
                    payload_json=_json({'next_at':(now+timedelta(seconds=1)).isoformat()})))
            return 0.0

    async def store_scan(self, result: Any) -> None:
        best=result.best
        payload={"status":result.status,"scanned":result.scanned,"duration_ms":str(result.duration_ms),
            "rejected":result.rejected,"provider_errors":result.provider_errors,
            "candidates":[{"symbol":c.market.pair.symbol,"score":str(c.score),"decision":c.decision,"signals":c.signals,"market":c.market.metrics} for c in result.candidates],
            "features":best.features if best else {},"signals":best.signals if best else [],
            "ai":best.ai_assessment if best else {},"decision":best.decision if best else {"action":"WAIT","accepted":False,"explanation":result.status}}
        async with self.session_factory() as session,session.begin():
            await self._lock_account(session)
            row=await session.get(SystemStateModel,"scanner")
            if row:
                row.state,row.payload_json,row.updated_at=result.status,_json(payload),utc_now()
            else:
                session.add(SystemStateModel(key="scanner",state=result.status,reason="worker_scan",payload_json=_json(payload)))

    async def read_scan(self) -> dict[str, Any]:
        async with self.session_factory() as session:
            row=await session.get(SystemStateModel,"scanner")
            if row:
                return dict(json.loads(row.payload_json))
            return {"status":"WAITING_FOR_WORKER","scanned":0,"duration_ms":"0","rejected":[],"provider_errors":[],"candidates":[],"features":{},"signals":[],"ai":{},"decision":{"action":"WAIT","accepted":False,"explanation":"No persisted worker scan yet."}}

    async def store_market_analysis(self, candles: list[Any], features: Any, book: Any) -> None:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            keys = [sha256(f"{c.symbol}:{c.timeframe}:{c.timestamp.isoformat()}".encode()).hexdigest() for c in candles]
            existing = set((await session.scalars(select(MarketCandle.observation_key).where(MarketCandle.observation_key.in_(keys)))).all())
            for key, c in zip(keys, candles, strict=True):
                if key not in existing:
                    session.add(MarketCandle(observation_key=key, symbol=c.symbol, timeframe=c.timeframe,
                        timestamp=c.timestamp, open=c.open, high=c.high, low=c.low, close=c.close,
                        volume=c.volume, source=c.source))
                    existing.add(key)
            key = sha256(f"{features.symbol}:{features.timestamp.isoformat()}:{book.timestamp.isoformat()}".encode()).hexdigest()
            if await session.get(MarketFeature, key) is None:
                session.add(MarketFeature(feature_id=key, symbol=features.symbol, timestamp=features.timestamp,
                    timeframe=features.timeframe, data_quality=features.data_quality.value, payload_json=_json(features)))
            await self._mark(session, book)

    async def control_state(self) -> str:
        async with self.session_factory() as session:
            account = await session.get(AccountModel, self.account_id)
            return str(account.control) if account else "STOPPED"

    async def record_news(self,event_id:str,symbol:str,timestamp:datetime,title:str,body:str,url:str,source:str)->None:
        async with self.session_factory() as session,session.begin():
            await self._lock_account(session)
            payload=_json({'body':body,'url':url,'verification':'unverified_external_context'})
            existing=await session.get(NewsEvent,event_id)
            if existing:
                if existing.symbol!=symbol or existing.title!=title or existing.payload_json!=payload:
                    raise ValueError('News identity already refers to another observation.')
                return
            session.add(NewsEvent(event_id=event_id,symbol=symbol,timestamp=timestamp,title=title,
                source=source,payload_json=payload))

    async def news_context(self,symbol:str)->list[dict[str,str]]:
        from datetime import timedelta
        async with self.session_factory() as session:
            rows=(await session.scalars(select(NewsEvent).where(NewsEvent.symbol==symbol,
                NewsEvent.timestamp>=utc_now()-timedelta(hours=48),NewsEvent.timestamp<=utc_now()).order_by(NewsEvent.timestamp.desc()).limit(3))).all()
            return [{'title':r.title,'source':r.source,'timestamp':r.timestamp.isoformat(),
                **json.loads(r.payload_json)} for r in rows]

    async def history(self) -> dict[str, object]:
        async with self.session_factory() as session:
            result: dict[str, object] = {}
            for key, model in (("decisions", TradingDecisionModel), ("signals", StrategySignalModel),
                    ("journal", JournalEventModel), ("incidents", SystemIncidentModel),
                    ("equity", EquitySnapshotModel), ("exit_intents", ExitIntentModel),
                    ("transitions", OrderTransitionModel)):
                rows = (await session.scalars(select(model).order_by(model.created_at.desc()).limit(500))).all()
                result[key] = [{c.name: json.loads(_json(getattr(row, c.name))) for c in model.__table__.columns} for row in rows]
            return result

    async def operational_health(self) -> dict[str, object]:
        async with self.session_factory() as session:
            from autotrader.persistence.accounting import aware
            worker = await session.get(SystemStateModel, "worker")
            heartbeat = json.loads(worker.payload_json).get("heartbeat") if worker else None
            age = (utc_now() - aware(datetime.fromisoformat(heartbeat))).total_seconds() if heartbeat else None
            incidents = (await session.scalars(select(SystemIncidentModel).order_by(SystemIncidentModel.created_at.desc()).limit(20))).all()
            pending = await session.scalar(select(func.count()).select_from(OrderModel).where(OrderModel.status.in_(["PENDING", "ACCEPTED"])))
            scanner=await session.get(SystemStateModel,"scanner")
            monitor=await session.get(SystemStateModel,"position_monitor")
            monitor_time=json.loads(monitor.payload_json).get('heartbeat') if monitor else None
            from autotrader.persistence.models import MarketMarkModel
            marks=(await session.scalars(select(MarketMarkModel))).all()
            freshness=[{'symbol':m.symbol,'source':m.source,'timestamp':m.timestamp.isoformat(),
                'age_seconds':(utc_now()-aware(m.timestamp)).total_seconds()} for m in marks]
            dialect=session.bind.dialect.name
        problems = await self.verify_invariants(Decimal("500"))
        return {"postgresql": "ok" if dialect=='postgresql' else 'not_configured',"database_engine":dialect,
            "exchange_data":scanner.state if scanner else 'no_scan_yet',"data_freshness":freshness,
            "position_monitor_heartbeat":monitor_time,"worker": "ok" if age is not None and age < 180 else "stale_or_absent",
            "worker_heartbeat": heartbeat, "worker_age_seconds": age, "pending_intents": pending,
            "reconciliation": {"checked_at": utc_now().isoformat(), "problems": problems},
            "risk_state": (await self.get_runtime_health()).value,
            "incidents": [{"message": r.message, "severity": r.severity, "state": r.status, "created_at": r.created_at.isoformat()} for r in incidents]}

    async def market_risk_off(self, symbol: str) -> bool:
        async with self.session_factory() as session:
            row = await session.scalar(select(MarketFeature).where(MarketFeature.symbol == symbol).order_by(MarketFeature.timestamp.desc()).limit(1))
            if row is None:
                return False
            from autotrader.persistence.accounting import aware
            if (utc_now() - aware(row.timestamp)).total_seconds() > 900:
                return False
            f = json.loads(row.payload_json)
            return bool(f.get("ema_21") and f.get("ema_50") and f.get("momentum") and Decimal(f["ema_21"]) < Decimal(f["ema_50"]) and Decimal(f["momentum"]) < Decimal("-0.01"))


    async def store_analysis(
        self,
        signals: list[StrategySignal],
        ai_assessment: AIAssessment | None,
        decision: TradingDecision,
        risk_evaluation: RiskEvaluation | None = None,
    ) -> None:
        async with self.session_factory() as session, session.begin():
            for signal in signals:
                version_id=signal.strategy_id+':3.4.0'
                if await session.get(StrategyVersionModel,version_id) is None:
                    session.add(StrategyVersionModel(version_id=version_id,strategy_id=signal.strategy_id,
                        version='3.4.0',active=True,payload_json='{"calibrated_predictive_edge":false}'))
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
            await self._lock_account(session)
            await self._health(session, state, reason)

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
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            problems = await self._verify(session, initial_cash)
            if problems:
                await self._health(session, RuntimeHealth.RECONCILIATION_REQUIRED, "operator_recovery_reconciliation_failed")
                return problems
            valuation = await self._valuation(session, persist=True)
            if valuation["valuation_degraded"] == "true":
                return ["fresh_valuation_required"]
            if Decimal(valuation["daily_equity_change"]) <= -15 or Decimal(valuation["weekly_equity_change"]) <= -35:
                return ["equity_loss_limit_still_breached"]
            row = await session.get(SystemStateModel, self.RUNTIME_STATE_KEY)
            if row:
                row.state, row.reason = "HEALTHY", "authenticated_operator_recovery"
            return []



    async def count_buy_entries_since(self, since: datetime) -> int:
        async with self.session_factory() as session:
            count = await session.scalar(
                select(func.count()).select_from(OrderModel).where(OrderModel.side == Side.BUY.value, OrderModel.created_at >= since)
            )
            return int(count or 0)


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
                    "position_id": fill.position_id or '',
                    "exit_intent_id":fill.exit_intent_id or '',
                    "exit_target_id":fill.exit_target_id or '',
                    "created_at":fill.created_at.isoformat(),
                    "attribution_status":fill.attribution_status,
                    "symbol": fill.symbol,
                    "side": fill.side,
                    "quantity": str(fill.quantity),
                    "price": str(fill.price),
                    "fee": str(fill.fee),
                    "simulated": str(fill.simulated),
                }
                for fill in fills
            ]




    async def filled_quantity_for_order(self, order_id: str) -> Decimal:
        async with self.session_factory() as session:
            filled = await session.scalar(select(func.sum(FillModel.quantity)).where(FillModel.order_id == order_id))
            return filled or Decimal("0")








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
            rejection_reason=json.loads(order.execution_json).get("rejection_reason"),
        )

