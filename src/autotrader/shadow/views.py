"""Bounded read models. Complete financial exports remain separate."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta
from decimal import Decimal as D
from typing import Any

from sqlalchemy import and_, func, or_, select

from autotrader.domain import utc_now
from autotrader.persistence import models as m
from autotrader.persistence.accounting import aware
from autotrader.persistence.repository import _json
from autotrader.shadow.versions import compatibility

MODELS: dict[str, tuple[Any, str]] = {
    "decisions": (m.TradingDecisionModel, "decision_id"),
    "feedback": (m.SystemStateModel, "key"),
    "signals": (m.StrategySignalModel, "signal_id"),
    "positions": (m.PositionModel, "position_id"),
    "orders": (m.OrderModel, "order_id"),
    "fills": (m.FillModel, "fill_id"),
    "journal": (m.JournalEventModel, "ledger_event_id"),
    "equity": (m.EquitySnapshotModel, "snapshot_id"),
    "incidents": (m.SystemIncidentModel, "incident_id"),
    "exit_intents": (m.ExitIntentModel, "exit_intent_id"),
    "transitions": (m.OrderTransitionModel, "transition_id"),
}


async def page(
    repo: Any,
    kind: str,
    limit: int = 30,
    cursor: str | None = None,
    status: str | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    if kind not in MODELS or not 1 <= limit <= 100:
        raise ValueError("invalid_history_page")
    model, identity = MODELS[kind]
    column = getattr(model, identity)
    watermark = until or utc_now()
    query = select(model)
    if kind == "feedback":
        query = query.where(model.key.like("feedback:%"))
    if kind == "positions" and status:
        query = query.where(
            model.quantity > 0 if status == "open" else model.closed_at.is_not(None)
        )
    if kind == "orders" and status:
        active = model.status.in_(["PENDING", "ACCEPTED"])
        query = query.where(active if status == "open" else ~active)
    if cursor:
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if (
                value["kind"] != kind
                or value["account"] != repo.account_id
                or value.get("status") != status
            ):
                raise ValueError("cursor_scope_mismatch")
            watermark = datetime.fromisoformat(value["until"])
            stamp = datetime.fromisoformat(value["time"])
            if not watermark.tzinfo or not stamp.tzinfo or len(value["id"]) > 128:
                raise ValueError("invalid_cursor")
            query = query.where(
                or_(model.created_at < stamp, and_(model.created_at == stamp, column < value["id"]))
            )
        except Exception as exc:
            raise ValueError("invalid_or_cross_account_cursor") from exc
    query = (
        query.where(model.created_at <= watermark)
        .order_by(model.created_at.desc(), column.desc())
        .limit(limit + 1)
    )
    async with repo.session_factory() as session:
        records = list((await session.scalars(query)).all())
        rows = [
            {c.name: json.loads(_json(getattr(row, c.name))) for c in model.__table__.columns}
            for row in records[:limit]
        ]
        if kind == "decisions" and rows:
            keys = ["shadow_explanation:" + r["decision_id"] for r in rows]
            explanations = {
                r.key.removeprefix("shadow_explanation:"): json.loads(r.payload_json)
                for r in (
                    await session.scalars(
                        select(m.SystemStateModel).where(m.SystemStateModel.key.in_(keys))
                    )
                ).all()
            }
            for row in rows:
                row["explanation"] = explanations.get(row["decision_id"])
    next_cursor = None
    if len(records) > limit:
        last = records[limit - 1]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "kind": kind,
                    "status": status,
                    "account": repo.account_id,
                    "until": watermark.isoformat(),
                    "time": aware(last.created_at).isoformat(),
                    "id": getattr(last, identity),
                }
            ).encode()
        ).decode()
    return {
        "items": rows,
        "next_cursor": next_cursor,
        "limit": limit,
        "as_of": watermark.isoformat(),
        "complete": next_cursor is None,
        "ordering": "created_at DESC, immutable ID DESC; insertion watermark; mutable records show current state",
    }


async def record_reconciliation(repo: Any) -> None:
    async with repo.session_factory() as session:
        old = await session.get(m.SystemStateModel, "shadow_reconciliation")
        if old and (utc_now() - aware(old.updated_at)).total_seconds() < 60:
            return
    problems = await repo.verify_invariants(D(500))
    async with repo.session_factory() as session, session.begin():
        row = await session.get(m.SystemStateModel, "shadow_reconciliation")
        payload = _json({"checked_at": utc_now().isoformat(), "problems": problems})
        if row:
            row.state, row.payload_json, row.updated_at = (
                "INCONSISTENT" if problems else "CONSISTENT",
                payload,
                utc_now(),
            )
        else:
            session.add(
                m.SystemStateModel(
                    key="shadow_reconciliation",
                    state="INCONSISTENT" if problems else "CONSISTENT",
                    reason="actual_full_ledger_reconciliation",
                    payload_json=payload,
                )
            )


async def account_summary(repo: Any) -> dict[str, Any]:
    async with repo.session_factory() as session:
        # Financial aggregates must observe a single committed snapshot even
        # when the worker commits fills between these read queries.
        if session.bind.dialect.name == "postgresql":
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        balance = await session.get(m.BalanceModel, "EUR")
        account = await session.get(m.AccountModel, repo.account_id)
        positions = (
            await session.execute(
                select(m.PositionModel, m.MarketMarkModel)
                .outerjoin(m.MarketMarkModel, m.PositionModel.symbol == m.MarketMarkModel.symbol)
                .where(m.PositionModel.quantity > 0)
            )
        ).all()
        cash = balance.available + balance.reserved if balance else None
        missing = [
            p.symbol
            for p, mark in positions
            if not mark
            or not 0
            <= (utc_now() - aware(mark.timestamp)).total_seconds()
            <= repo.mark_max_age_seconds
        ]
        equity = (
            cash + sum((p.quantity * mark.price for p, mark in positions if mark), D(0))
            if cash is not None and not missing
            else None
        )
        closed = await session.scalar(
            select(func.count())
            .select_from(m.PositionModel)
            .where(m.PositionModel.closed_at.is_not(None))
        )
        fees = await session.scalar(select(func.coalesce(func.sum(m.FillModel.fee), 0)))
        realized = await session.scalar(select(func.coalesce(func.sum(m.JournalEventModel.realized_pnl_delta), 0)))
        exposure = sum((p.quantity * mark.price for p, mark in positions if mark), D(0)) if not missing else None
        basis = sum((p.cost_basis for p, _ in positions), D(0))
        last = await session.scalar(
            select(m.TradingDecisionModel)
            .order_by(
                m.TradingDecisionModel.created_at.desc(), m.TradingDecisionModel.decision_id.desc()
            )
            .limit(1)
        )
        explanation = (
            await session.get(m.SystemStateModel, "shadow_explanation:" + last.decision_id)
            if last
            else None
        )
        reconciliation = await session.get(m.SystemStateModel, "shadow_reconciliation")
        health = await session.get(m.SystemStateModel, "runtime_health")
        scan_observation = await session.get(m.SystemStateModel, "shadow_scan_observation")
        incident_rows = (await session.scalars(select(m.SystemStateModel).where(
            m.SystemStateModel.key.in_(["shadow_runtime_incident", "execution_trace_health"]),
            m.SystemStateModel.state == "ERROR"))).all()
        return {
            "portfolio": {
                "equity": str(equity) if equity is not None else "",
                "cash": str(cash) if cash is not None else "",
                "available_cash": str(balance.available) if balance else "",
                "reserved_cash": str(balance.reserved) if balance else "",
                "open_exposure": str(exposure) if exposure is not None else "",
                "realized_pnl": str(realized),
                "unrealized_pnl": str(exposure - basis) if exposure is not None else "",
                "total_net_pnl": str(equity - 500) if equity is not None else "",
                "positions": str(len(positions)),
                "valuation_degraded": str(bool(missing)).lower(),
                "control": account.control if account else None,
                "risk_state": health.state if health else "UNKNOWN",
            },
            "performance": {
                "net_pnl": str(equity - 500) if equity is not None else "",
                "closed_trades": closed,
                "fees": str(fees),
            },
            "scan_observation": json.loads(scan_observation.payload_json) if scan_observation else None,
            "runtime_incidents": [{"state": r.state, "reason": r.reason, "detail": json.loads(r.payload_json)} for r in incident_rows],
            "last_evaluation_at": aware(last.created_at).isoformat() if last else None,
            "latest_decision": json.loads(explanation.payload_json)
            if explanation
            else {
                "decision_id": last.decision_id,
                "symbol": last.symbol,
                "evaluated_at": aware(last.created_at).isoformat(),
                "reason": last.rejected_reason,
                "decision_accepted": last.accepted,
                "structured_evidence_available": False,
            }
            if last
            else None,
            "reconciliation_status": {
                "status": reconciliation.state,
                "observed": json.loads(reconciliation.payload_json),
                "stale": (utc_now() - aware(reconciliation.updated_at)) > timedelta(seconds=180),
            }
            if reconciliation
            else {"status": "NOT_CHECKED", "observed": None, "stale": True},
        }


async def summaries(lab: Any, archived: bool = False) -> dict[str, Any]:
    from autotrader.shadow.lab import MAX_EXPERIMENTS, PRESETS

    records = await lab.records()
    result = []
    for record in records:
        if bool(record.get("archived_at")) != archived:
            continue
        manifest = record["manifest"]
        compatible = compatibility(manifest)
        result.append(
            {
                **{k: v for k, v in record.items() if k != "manifest"},
                "manifest": {
                    k: manifest.get(k)
                    for k in ("strategy_id", "strategy_version", "source_fingerprint", "data_kind")
                },
                "archive_enabled": lab.settings.shadow_archive_enabled,
                "runtime_compatibility": compatible,
                "source_matches": compatible["compatible"],
                **(
                    await account_summary(await lab.repository(record["experiment_id"]))
                    if record["state"] != "CREATING"
                    else {}
                ),
            }
        )
    return {
        "enabled": lab.settings.shadow_enabled,
        "experiments": result,
        "maximum_experiments": MAX_EXPERIMENTS,
        "occupied_slots": sum(not r.get("archived_at") for r in records),
        "archived_count": sum(bool(r.get("archived_at")) for r in records),
        "presets": [
            {"strategy_id": s.strategy_id, "version": s.version, "hypothesis": s.hypothesis}
            for s in PRESETS.values()
        ],
        "as_of": utc_now().isoformat(),
        "history_included": False,
        "archive_enabled": lab.settings.shadow_archive_enabled,
        "archive_policy": "Archiving requires separately approved configuration. Deleting a paused/stopped flat account archives all history and releases a workspace slot; identity, database and funding are retained, never reused.",
    }


async def experiment_view(lab: Any, identity: str) -> dict[str, Any]:
    record = next((r for r in await lab.records() if r["experiment_id"] == identity), None)
    if record is None:
        raise ValueError("unknown_shadow_experiment")
    repo = await lab.repository(identity)
    summary = await account_summary(repo)
    pages = {
        kind: await page(repo, kind, 30)
        for kind in ("positions", "orders", "fills", "decisions", "equity", "exit_intents")
    }
    async with repo.session_factory() as session:
        targets = (
            await session.scalars(
                select(m.ExitTargetModel).order_by(m.ExitTargetModel.created_at.desc()).limit(100)
            )
        ).all()
        pnl = (
            await session.execute(
                select(
                    func.count(),
                    func.sum(m.PositionModel.realized_pnl),
                    func.sum(m.PositionModel.realized_pnl),
                ).where(m.PositionModel.closed_at.is_not(None))
            )
        ).first()
        # These aggregate results cover the complete account, independent of page windows.
        wins = (
            await session.execute(
                select(func.count(), func.sum(m.PositionModel.realized_pnl)).where(
                    m.PositionModel.closed_at.is_not(None), m.PositionModel.realized_pnl > 0
                )
            )
        ).first()
        losses = (
            await session.execute(
                select(func.count(), func.sum(m.PositionModel.realized_pnl)).where(
                    m.PositionModel.closed_at.is_not(None), m.PositionModel.realized_pnl < 0
                )
            )
        ).first()
        from sqlalchemy import text

        drawdown = await session.scalar(
            text(
                "SELECT COALESCE(MAX((peak-equity)/NULLIF(peak,0)),0) FROM (SELECT equity, MAX(equity) OVER (ORDER BY timestamp,created_at,snapshot_id ROWS UNBOUNDED PRECEDING) AS peak FROM equity_snapshots WHERE degraded=false) s"
            )
        )
    performance = summary["performance"]
    performance.update(
        win_rate=wins[0] / pnl[0] if pnl[0] else None,
        profit_factor=str(wins[1] / -losses[1]) if losses[1] else None,
        expectancy=str(pnl[1] / pnl[0]) if pnl[0] else None,
        max_drawdown=str(drawdown),
    )
    reconciliation = summary["reconciliation_status"]
    return {
        **record,
        "archive_enabled": lab.settings.shadow_archive_enabled,
        **summary,
        "source_matches": compatibility(record["manifest"])["compatible"],
        "runtime_compatibility": compatibility(record["manifest"]),
        "positions": pages["positions"]["items"],
        "orders": pages["orders"]["items"],
        "fills": pages["fills"]["items"],
        "history": {k: pages[k]["items"] for k in ("decisions", "equity", "exit_intents")},
        "targets": [
            {
                c.name: json.loads(_json(getattr(row, c.name)))
                for c in m.ExitTargetModel.__table__.columns
            }
            for row in targets
        ],
        "reconciliation": reconciliation.get("observed", {}).get("problems")
        if reconciliation.get("observed")
        else None,
        "history_window_limit": 30,
        "next_cursors": {k: v["next_cursor"] for k, v in pages.items()},
        "performance": performance,
    }
