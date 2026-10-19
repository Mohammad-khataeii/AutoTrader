"""Idempotent observation journal. Never authorizes, retries or changes a trade."""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select, text

from autotrader.domain import utc_now
from autotrader.persistence.models import (
    ExitPlanModel,
    FillModel,
    OrderModel,
    PositionModel,
    SystemStateModel,
)
from autotrader.persistence.repository import _json
from autotrader.research.data import digest

log = logging.getLogger(__name__)
STAGES = ("SIGNAL_ELIGIBLE", "DECISION_ACCEPTED", "ALLOCATION_ACCEPTED", "ENTRY_PREFLIGHT",
          "PAPER_ORDER_CREATED", "ORDER_FILLED", "POSITION_OPENED", "POSITION_PROTECTED", "POSITION_CLOSED")


async def runtime_incident(repo: Any, phase: str, reason: str) -> None:
    try:
        async with repo.session_factory() as session, session.begin():
            row = await session.get(SystemStateModel, "shadow_runtime_incident")
            body = _json({"phase": phase, "reason": reason, "observed_at": utc_now().isoformat()})
            if row is None:
                session.add(SystemStateModel(key="shadow_runtime_incident", state="ERROR", reason=reason, payload_json=body))
            else:
                row.state, row.reason, row.payload_json = "ERROR", reason, body
    except Exception:
        log.exception("shadow_runtime_incident_write_failed")


def key(decision_id: str) -> str:
    return "trace:" + digest(decision_id.encode())[:56]


def stage_states(trace: dict[str, Any] | None) -> dict[str, str]:
    """A preceding recorded refusal proves unreached stages; missing history does not."""
    result: dict[str, str] = {}
    stopped = False
    for stage in STAGES:
        observations = [e for e in (trace or {}).get("events", {}).values() if e["stage"] == stage]
        statuses = {e["status"] for e in observations}
        if statuses:
            result[stage] = ("SUCCEEDED" if "SUCCEEDED" in statuses else "EXCEPTION" if "EXCEPTION" in statuses
                             else "REJECTED" if "REJECTED" in statuses else "OUTCOME_UNAVAILABLE")
            stopped = stopped or bool(statuses & {"REJECTED", "EXCEPTION"})
        else:
            result[stage] = "NEVER_REACHED" if stopped else "NOT_RECORDED"
    return result


async def event(repo: Any, decision_id: str, stage: str, status: str, *,
                symbol: str | None = None, candle_at: str | None = None,
                reason: str | None = None, related: dict[str, Any] | None = None,
                discriminator: str = "") -> None:
    """ATTEMPTED stays unavailable after a crash; no retrospective gate guesses."""
    if stage not in STAGES or status not in {"ATTEMPTED", "SUCCEEDED", "REJECTED", "EXCEPTION"}:
        raise ValueError("invalid_trace_event")
    try:
        trace_key = key(decision_id)
        now = utc_now().isoformat()
        manifest = repo.scope.manifest
        async with repo.session_factory() as session, session.begin():
            # Cross-process serialization, including first insert and restart replay.
            await session.execute(text("SELECT pg_advisory_xact_lock(:lock)"),
                {"lock": int(digest(trace_key.encode())[:15], 16)})
            row = await session.get(SystemStateModel, trace_key)
            body = json.loads(row.payload_json) if row else {
                "schema": "execution-trace/1", "decision_id": decision_id,
                "experiment_id": manifest["experiment_id"], "strategy_id": manifest["strategy_id"],
                "runtime": getattr(repo, "_diagnostic_runner", "UNKNOWN"),
                "execution_fingerprint": manifest.get("execution_fingerprint"),
                "source_fingerprint": manifest["source_fingerprint"], "symbol": symbol,
                "candle_at": candle_at, "events": {}}
            body["symbol"] = body.get("symbol") or symbol
            body["candle_at"] = body.get("candle_at") or candle_at
            event_key = stage + (":" + discriminator if discriminator else "")
            previous = body["events"].get(event_key)
            # An idempotent replay must not create a new event or regress success.
            if previous and previous["status"] != "ATTEMPTED":
                return
            body["events"][event_key] = {"stage": stage, "status": status,
                "entered_at": previous["entered_at"] if previous else now,
                "completed_at": None if status == "ATTEMPTED" else now,
                "processing_at": now, "reason_code": reason.split(":", 1)[0].split(",", 1)[0] if reason else None,
                "reason": reason, "related": related or {}}
            if row is None:
                session.add(SystemStateModel(key=trace_key, state=status,
                    reason="execution_trace", payload_json=_json(body)))
            else:
                row.state, row.payload_json = status, _json(body)
    except Exception:
        # Trading return values and safeguards are never replaced by telemetry.
        log.exception("execution_trace_write_failed", extra={"decision_id": decision_id, "stage": stage})
        try:
            async with repo.session_factory() as session, session.begin():
                row = await session.get(SystemStateModel, "execution_trace_health")
                if row is None:
                    session.add(SystemStateModel(key="execution_trace_health", state="ERROR",
                        reason="execution_trace_write_failed", payload_json="{}"))
                else:
                    row.state, row.reason = "ERROR", "execution_trace_write_failed"
        except Exception:
            log.exception("execution_trace_incident_write_failed")


async def observe_order(repo: Any, order_id: str) -> None:
    """Confirm committed facts by IDs; never infer a preflight refusal from price."""
    try:
        async with repo.session_factory() as session:
            order = await session.get(OrderModel, order_id)
            if order is None:
                return
            decision_id = order.decision_id
            if not decision_id and order.position_id:
                decision_id = await session.scalar(select(OrderModel.decision_id).where(
                    OrderModel.position_id == order.position_id, OrderModel.side == "BUY").limit(1))
            if not decision_id:
                return
            fills = list((await session.scalars(select(FillModel).where(FillModel.order_id == order_id))).all())
            position = await session.get(PositionModel, order.position_id) if order.position_id else None
            plan = await session.scalar(select(ExitPlanModel).where(ExitPlanModel.position_id == order.position_id)) if position else None
        related = {"order_id": order_id, "position_id": order.position_id,
                   "fill_ids": [f.fill_id for f in fills]}
        await event(repo, decision_id, "PAPER_ORDER_CREATED", "SUCCEEDED", symbol=order.symbol,
                    related=related, discriminator=order_id)
        if fills:
            await event(repo, decision_id, "ORDER_FILLED", "SUCCEEDED", related=related, discriminator=order_id)
        if position and fills and order.side == "BUY":
            await event(repo, decision_id, "POSITION_OPENED", "SUCCEEDED", related=related)
            if plan and position.protective_stop is not None:
                await event(repo, decision_id, "POSITION_PROTECTED", "SUCCEEDED", related={**related, "exit_plan_id": plan.exit_plan_id})
        if position and position.closed_at is not None and position.quantity == 0:
            await event(repo, decision_id, "POSITION_CLOSED", "SUCCEEDED", related=related)
    except Exception:
        log.exception("execution_trace_financial_observation_failed")


async def recover_traces(repo: Any, limit: int = 100) -> None:
    """Recover only already traced decisions; historical missing evidence stays unknown."""
    try:
        async with repo.session_factory() as session:
            # Bounded recovery includes recently closed positions, not just open ones.
            orders = list((await session.scalars(select(OrderModel).order_by(OrderModel.created_at.desc()).limit(limit))).all())
            for order in orders:
                decision = order.decision_id
                if not decision and order.position_id:
                    decision = await session.scalar(select(OrderModel.decision_id).where(
                        OrderModel.position_id == order.position_id, OrderModel.side == "BUY").limit(1))
                if decision and await session.get(SystemStateModel, key(decision)):
                    await observe_order(repo, order.order_id)
    except Exception:
        log.exception("execution_trace_recovery_failed")
