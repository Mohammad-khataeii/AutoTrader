from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from autotrader.domain import OrderBook, OrderBookLevel, Side, utc_now
from autotrader.execution.pricing import observation_key, quote_execution
from autotrader.persistence.accounting import aware
from autotrader.persistence.models import (
    MarketCandle,
    MarketFeature,
    OrderModel,
    PositionModel,
    StrategySignalModel,
    SystemStateModel,
    TradingDecisionModel,
)


class AnalyticsMixin:
    session_factory: Any
    _lock_account: Any
    _valuation: Any

    async def execution_analytics(self, fee_bps: Decimal, slippage_bps: Decimal) -> dict[str, Any]:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            valuation = await self._valuation(session)
            orders = (await session.scalars(select(OrderModel).order_by(OrderModel.created_at.desc()).limit(200))).all()
            positions = (await session.scalars(select(PositionModel).where(PositionModel.state == "OPEN"))).all()
            rows = []
            total = Decimal(0)
            complete = True
            for p in positions:
                row: dict[str, Any] = {"position_id": p.position_id, "symbol": p.symbol, "quantity": str(p.quantity)}
                observation = await session.get(SystemStateModel, "book:" + p.symbol)
                try:
                    if observation is None:
                        raise ValueError("no_persisted_executable_book")
                    raw = json.loads(observation.payload_json)
                    book = OrderBook(p.symbol, datetime.fromisoformat(raw["timestamp"]),
                        tuple(OrderBookLevel(Decimal(price), Decimal(qty)) for price, qty in raw["bids"]),
                        tuple(OrderBookLevel(Decimal(price), Decimal(qty)) for price, qty in raw["asks"]), raw["source"])
                    used = await session.get(SystemStateModel, observation_key(book))
                    consumed = {int(k): Decimal(v) for k, v in json.loads(used.payload_json)["SELL"].items()} if used else {}
                    quote = quote_execution(book, Side.SELL, p.quantity, fee_bps=fee_bps, slippage_bps=slippage_bps, consumed=consumed)
                    row.update(quote.payload())
                    total += quote.net_cash_change
                    complete = complete and quote.fillable_quantity == p.quantity
                except ValueError as exc:
                    complete = False
                    row["unavailable_reason"] = str(exc)
                rows.append(row)
            watches = (await session.scalars(select(SystemStateModel).where(SystemStateModel.key.like("protect:%")))).all()
            policy = await session.get(SystemStateModel, "research_entry_policy")
            return {"orders": [{"order_id": o.order_id, "position_id": o.position_id, "symbol": o.symbol,
                "side": o.side, "status": o.status, "created_at": o.created_at.isoformat(),
                "admission_quality": json.loads(o.execution_json).get("admission_quality"),
                "execution_quality": json.loads(o.execution_json).get("execution_quality"),
                "rejection_reason": json.loads(o.execution_json).get("rejection_reason")} for o in orders],
                "positions": rows, "mark_equity": valuation["equity"],
                "executable_bid_equity_after_exit_costs": str(Decimal(valuation["cash"]) + total) if complete else None,
                "executable_valuation_complete": complete, "observed_partial_net_proceeds": str(total),
                "protection_watches": [{"state": w.state, "reason": w.reason, **json.loads(w.payload_json)} for w in watches],
                "entry_policy": json.loads(policy.payload_json) if policy else None,
                "quote_policy": "Current finite persisted depth after prior consumption, fees and adverse slippage; stale or partial books do not imply full liquidation value"}

    async def refresh_opportunity_feedback(self, limit: int = 50) -> None:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            stmt = select(TradingDecisionModel).outerjoin(SystemStateModel,
                SystemStateModel.key == "feedback:" + TradingDecisionModel.decision_id).where(
                TradingDecisionModel.created_at <= utc_now() - timedelta(hours=6),
                SystemStateModel.key.is_(None)).order_by(TradingDecisionModel.created_at).limit(limit)
            for decision in (await session.scalars(stmt)).all():
                payload = json.loads(decision.payload_json)
                orders = (await session.scalars(select(OrderModel).where(OrderModel.decision_id == decision.decision_id))).all()
                signals = (await session.scalars(select(StrategySignalModel).where(StrategySignalModel.signal_id.in_(payload.get("signal_ids", []))))).all()
                end = aware(decision.created_at) + timedelta(hours=6)
                candles = (await session.scalars(select(MarketCandle).where(MarketCandle.symbol == decision.symbol,
                    MarketCandle.timeframe == "5m", MarketCandle.timestamp >= decision.created_at,
                    MarketCandle.timestamp <= end - timedelta(minutes=5)).order_by(MarketCandle.timestamp))).all()
                price = Decimal(str(payload.get("entry_price") or 0))
                reason = ",".join(str(json.loads(o.execution_json).get("rejection_reason") or "") for o in orders) or decision.rejected_reason or ""
                evidence = [json.loads(s.payload_json).get("evidence", {}) for s in signals]
                feature = await session.scalar(select(MarketFeature).where(MarketFeature.symbol == decision.symbol,
                    MarketFeature.timestamp <= decision.created_at, MarketFeature.created_at <= decision.created_at).order_by(MarketFeature.timestamp.desc()).limit(1))
                category = "NO_PREDICTIVE_EVIDENCE"
                if not candles or price <= 0:
                    category = "DATA_BLOCKED"
                elif "cost" in reason or "execution_quality" in reason:
                    category = "COST_REJECTED"
                elif "liquidity" in reason or "depth" in reason or "ioc" in reason:
                    category = "LIQUIDITY_REJECTED"
                elif "risk" in reason or "cash" in reason or "reserve" in reason:
                    category = "RISK_REJECTED"
                elif any(e.get("veto") for e in evidence):
                    category = "REGIME_BLOCKED"
                elif not any(e.get("entry_eligible") for e in evidence):
                    category = "NO_QUALIFYING_SIGNAL"
                result = {"decision_id": decision.decision_id, "symbol": decision.symbol,
                    "created_at": aware(decision.created_at).isoformat(), "category": category,
                    "rejection_reason": reason, "accepted_decision": decision.accepted,
                    "order_ids": [o.order_id for o in orders], "signal_evidence": evidence,
                    "signal_ids":payload.get("signal_ids", []),
                    "features":json.loads(feature.payload_json) if feature else None,
                    "ai_assessment_id": payload.get("ai_assessment_id"), "horizon_hours": 6,
                    "subsequent_completed_bars": len(candles), "expected_5m_bars": 72,
                    "observed_mfe": str(max(Decimal(0), max(c.high for c in candles) / price - 1)) if candles and price > 0 else None,
                    "observed_mae": str(min(Decimal(0), min(c.low for c in candles) / price - 1)) if candles and price > 0 else None,
                    "conclusion": "Hindsight observations do not establish a false negative or predictive opportunity; no automatic promotion"}
                session.add(SystemStateModel(key="feedback:" + decision.decision_id, state="OBSERVED", reason=category, payload_json=json.dumps(result)))

    async def opportunity_analytics(self) -> dict[str, Any]:
        async with self.session_factory() as session:
            rows = (await session.scalars(select(SystemStateModel).where(SystemStateModel.key.like("feedback:%")).order_by(SystemStateModel.created_at.desc()).limit(200))).all()
            allocations = (await session.scalars(select(SystemStateModel).where(SystemStateModel.key.like("alloc:%")).order_by(SystemStateModel.created_at.desc()).limit(100))).all()
            mature = await session.scalar(select(func.count()).select_from(TradingDecisionModel).outerjoin(SystemStateModel,
                SystemStateModel.key == "feedback:" + TradingDecisionModel.decision_id).where(
                TradingDecisionModel.created_at <= utc_now() - timedelta(hours=6), SystemStateModel.key.is_(None)))
            return {"feedback": [json.loads(row.payload_json) for row in rows],
                "allocation_decisions": [json.loads(row.payload_json) for row in allocations],
                "mature_feedback_backlog": mature, "policy": "Six-hour completed-candle observations; insufficient history is explicit; feedback cannot deploy strategies"}
