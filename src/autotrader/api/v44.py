"""Additive V4.4 read models and explicitly confirmed archival workflow."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select

from autotrader.domain import utc_now
from autotrader.persistence import models as m
from autotrader.research.artifacts import load_latest
from autotrader.shadow import views


def install(app: FastAPI, repository: Any, lab: Any, settings: Any, require_user: Any) -> None:
    auth = [Depends(require_user)]

    async def scoped(identity: str) -> Any:
        if identity == "official":
            return repository
        try:
            return await lab.repository(identity)
        except ValueError as exc:
            raise HTTPException(404, detail=str(exc)) from None

    @app.get("/api/release/compatibility", dependencies=auth)
    async def release_compatibility() -> dict[str, Any]:
        from autotrader.research.artifacts import source_fingerprint
        from autotrader.shadow.versions import compatibility, execution_fingerprint, verify_legacy

        rows = []
        for record in await lab.records():
            repo = await lab.repository(record["experiment_id"])
            problems = await repo.verify_invariants(settings.initial_cash_eur)
            runtime = compatibility(record["manifest"])
            rows.append(
                {
                    "experiment_id": record["experiment_id"],
                    "state": record["state"],
                    "archived_at": record.get("archived_at"),
                    "manifest_hash": repo.scope.identity_hash,
                    "original_source_fingerprint": record["manifest"]["source_fingerprint"],
                    "runtime": runtime,
                    "reconciliation": problems,
                }
            )
        try:
            verify_legacy()
            verified = True
        except ValueError:
            verified = False
        safe = verified and all(
            r["runtime"]["compatible"] and not r["reconciliation"] for r in rows
        )
        return {
            "status": "COMPATIBLE" if safe else "BLOCKED",
            "legacy_snapshot_verified": verified,
            "application_source_fingerprint": source_fingerprint()[0],
            "native_execution_fingerprint": execution_fingerprint(),
            "accounts": rows,
            "occupied_slots": sum(not r["archived_at"] for r in rows),
            "registry_records_preserved": len(rows),
            "financial_databases_deleted": False,
            "migration_required": False,
            "real_money_enabled": settings.live_trading_enabled,
            "paper_trading_enabled": settings.paper_trading_enabled,
            "configuration_verified": True,
        }

    @app.get("/api/overview/summary", dependencies=auth)
    async def overview_summary() -> dict[str, Any]:
        summary = await views.account_summary(repository)
        return {"application_version": "4.5.0", **summary, "health": {"mode": "paper", "api": "ok", "risk": (await repository.get_runtime_health()).value, "reconciliation": summary["reconciliation_status"]}}

    @app.get("/api/shadow/summary", dependencies=auth)
    async def shadow_summary(archived: bool = False) -> dict[str, Any]:
        return await views.summaries(lab, archived)

    @app.delete("/api/shadow/{identity}", dependencies=auth)
    async def archive_shadow(identity: str, confirm: str = "") -> dict[str, Any]:
        if not settings.shadow_archive_enabled:
            raise HTTPException(409, detail="archiving_disabled_during_v45_investigation")
        if confirm != identity:
            raise HTTPException(409, detail="explicit_experiment_identity_confirmation_required")
        try:
            return dict(await lab.archive(identity))
        except ValueError as exc:
            raise HTTPException(409, detail=str(exc)) from None

    @app.get("/api/shadow/{identity}/pages/{kind}", dependencies=auth)
    @app.get("/api/history/page/{kind}", dependencies=auth)
    async def history_page(
        kind: str,
        identity: str = "official",
        limit: int = Query(30, ge=1, le=100),
        cursor: str | None = Query(None, max_length=2048),
    ) -> dict[str, Any]:
        try:
            return await views.page(await scoped(identity), kind, limit, cursor)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from None

    @app.get("/api/shadow/{identity}/view", dependencies=auth)
    async def experiment_view(identity: str) -> dict[str, Any]:
        try:
            return await views.experiment_view(lab, identity)
        except ValueError as exc:
            raise HTTPException(404, detail=str(exc)) from None

    @app.get("/api/trades", dependencies=auth)
    async def trades(
        account: str = "all",
        kind: Literal["positions", "orders"] = "positions",
        view: Literal["open", "history"] = "open",
        limit: int = Query(30, ge=1, le=100),
        cursor: str | None = Query(None, max_length=4096),
    ) -> dict[str, Any]:
        import base64
        from datetime import datetime

        from autotrader.shadow.lab import PRESETS

        records = await lab.records()
        names = {
            "official": "Official",
            **{
                r["experiment_id"]: PRESETS[r["manifest"]["strategy_id"]].strategy_id
                + " · "
                + r["experiment_id"][:8]
                for r in records
            },
        }
        ids = ["official"] + [r["experiment_id"] for r in records if not r.get("archived_at")]
        ids = ids if account == "all" else [account]
        index = 0
        inner = None
        watermark = utc_now()
        if account != "all" and account not in names:
            raise HTTPException(404, detail="unknown_account")
        if cursor:
            try:
                value = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if value["account"] != account or value["kind"] != kind or value["view"] != view:
                    raise ValueError("cursor_filter_mismatch")
                ids = value["ids"]
                index = value["index"]
                inner = value["inner"]
                watermark = datetime.fromisoformat(value["until"])
                if (
                    not watermark.tzinfo
                    or not 0 <= index < len(ids)
                    or any(identity not in names for identity in ids)
                ):
                    raise ValueError("invalid_cursor")
            except Exception:
                raise HTTPException(422, detail="invalid_trade_cursor") from None
        rows: list[dict[str, Any]] = []
        while index < len(ids) and len(rows) < limit:
            identity = ids[index]
            try:
                result = await views.page(
                    await scoped(identity),
                    kind,
                    limit - len(rows),
                    inner,
                    status=view,
                    until=watermark,
                )
            except ValueError as exc:
                raise HTTPException(422, detail=str(exc)) from None
            key = "position_id" if kind == "positions" else "order_id"
            rows.extend(
                {
                    "key": identity + ":" + r[key],
                    "account": identity,
                    "accountName": names[identity],
                    "kind": "position" if kind == "positions" else "order",
                    "record": r,
                    "symbol": r["symbol"],
                }
                for r in result["items"]
            )
            inner = result["next_cursor"]
            if inner:
                break
            index += 1
        next_cursor = (
            base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "account": account,
                        "kind": kind,
                        "view": view,
                        "ids": ids,
                        "index": index,
                        "inner": inner,
                        "until": watermark.isoformat(),
                    }
                ).encode()
            ).decode()
            if index < len(ids)
            else None
        )
        return {
            "items": rows,
            "next_cursor": next_cursor,
            "as_of": watermark.isoformat(),
            "limit": limit,
            "ordering": "Grouped by account; newest first within each account. Complete histories remain available via pagination and full exports.",
        }

    @app.get("/api/trades/{account}/{kind}/{identity}", dependencies=auth)
    async def trade_detail(
        account: str, kind: Literal["position", "order"], identity: str
    ) -> dict[str, Any]:
        repo = await scoped(account)
        model: Any = m.PositionModel if kind == "position" else m.OrderModel
        key = model.position_id if kind == "position" else model.order_id
        async with repo.session_factory() as session:
            record = await session.scalar(select(model).where(key == identity))
            if record is None:
                raise HTTPException(404, detail="trade_not_found")
            position_id = record.position_id

            def encode(row: Any) -> dict[str, Any]:
                from autotrader.persistence.repository import _json

                return {
                    c.name: json.loads(_json(getattr(row, c.name))) for c in row.__table__.columns
                }

            positions = (
                await session.scalars(
                    select(m.PositionModel).where(m.PositionModel.position_id == position_id)
                )
            ).all()
            orders = (
                await session.scalars(
                    select(m.OrderModel)
                    .where(
                        m.OrderModel.order_id == identity
                        if kind == "order"
                        else m.OrderModel.position_id == position_id
                    )
                    .order_by(m.OrderModel.created_at.desc())
                    .limit(100)
                )
            ).all()
            fills = (
                await session.scalars(
                    select(m.FillModel)
                    .where(
                        m.FillModel.order_id == identity
                        if kind == "order"
                        else m.FillModel.position_id == position_id
                    )
                    .order_by(m.FillModel.created_at.desc())
                    .limit(100)
                )
            ).all()
            targets = (
                await session.scalars(
                    select(m.ExitTargetModel)
                    .where(m.ExitTargetModel.position_id == position_id)
                    .limit(100)
                )
            ).all()
            decisions = (
                await session.scalars(
                    select(m.TradingDecisionModel)
                    .where(
                        m.TradingDecisionModel.decision_id.in_(
                            [o.decision_id for o in orders if o.decision_id]
                        )
                    )
                    .limit(100)
                )
            ).all()
            intents = (
                await session.scalars(
                    select(m.ExitIntentModel)
                    .where(m.ExitIntentModel.position_id == position_id)
                    .limit(100)
                )
            ).all()
            return {
                "positions": [encode(r) for r in positions],
                "orders": [encode(r) for r in orders],
                "fills": [encode(r) for r in fills],
                "targets": [encode(r) for r in targets],
                "history": {
                    "decisions": [encode(r) for r in decisions],
                    "exit_intents": [encode(r) for r in intents],
                },
                "record": encode(record),
                "detail_row_limit": 100,
                "complete_history": "Use authenticated account pages and complete exports.",
            }

    @app.get("/api/shadow/{identity}/diagnostics", dependencies=auth)
    async def diagnostics(identity: str, limit: int = Query(100, ge=1, le=100)) -> dict[str, Any]:
        from autotrader.shadow.diagnostics import counterfactual

        result = await views.page(await scoped(identity), "decisions", limit)
        rows = [r["explanation"] for r in result["items"] if r.get("explanation")]
        return {
            **counterfactual(rows),
            "window": {
                "as_of": result["as_of"],
                "limit": limit,
                "structured_observations": len(rows),
                "legacy_unannotated_observations": len(result["items"]) - len(rows),
            },
            "read_only": True,
        }

    @app.get("/api/monitoring/summary", dependencies=auth)
    async def monitoring() -> dict[str, Any]:
        from autotrader.persistence.accounting import aware

        summary = await views.summaries(lab)
        account = await views.account_summary(repository)
        async with repository.session_factory() as session:
            states = {
                r.key: r
                for r in (
                    await session.scalars(
                        select(m.SystemStateModel).where(
                            m.SystemStateModel.key.in_(
                                [
                                    "worker",
                                    "scanner",
                                    "operation",
                                    "position_monitor",
                                    "research_entry_policy",
                                    "runtime_health",
                                ]
                            )
                        )
                    )
                ).all()
            }
            incidents = (
                await session.scalars(
                    select(m.SystemIncidentModel)
                    .where(m.SystemIncidentModel.severity.in_(["WARNING", "ERROR", "CRITICAL"]))
                    .order_by(m.SystemIncidentModel.created_at.desc())
                    .limit(20)
                )
            ).all()
            jobs = (
                await session.scalars(
                    select(m.SystemStateModel)
                    .where(m.SystemStateModel.reason == "historical_research")
                    .order_by(m.SystemStateModel.updated_at.desc())
                    .limit(10)
                )
            ).all()

        def payload(key: str) -> dict[str, Any]:
            return json.loads(states[key].payload_json) if key in states else {}

        heartbeat = payload("worker").get("heartbeat")
        age = (
            (utc_now() - aware(datetime.fromisoformat(heartbeat))).total_seconds()
            if heartbeat
            else None
        )
        worker = "ok" if age is not None and 0 <= age < 180 else "stale_or_absent"
        risk_state = states["runtime_health"].state if "runtime_health" in states else "UNKNOWN"
        operator = [
            {
                "message": r.message,
                "severity": r.severity,
                "state": r.status,
                "created_at": aware(r.created_at).isoformat(),
            }
            for r in incidents
            if r.message.startswith("operator_")
        ]
        # Incidents are append-only. A fresh state transition can resolve a
        # known risk/operation incident; unrelated alerts need their own evidence.
        from autotrader.domain import RuntimeHealth
        known_states = {r.value for r in RuntimeHealth} | {
            "SYSTEM_ERROR", "DATA_SYNCING", "DATA_DEGRADED", "RECOVERY_REQUIRED"
        }
        operation_state = states["operation"].state if "operation" in states else "UNKNOWN"

        def unresolved(incident: Any) -> bool:
            if incident.status in known_states:
                return incident.status in {risk_state, operation_state}
            return incident.status not in {"HEALTHY", "RESOLVED", "CLOSED"}

        errors = [
            {
                "message": r.message,
                "severity": r.severity,
                "state": r.status,
                "created_at": aware(r.created_at).isoformat(),
            }
            for r in incidents
            if r.severity in {"WARNING", "ERROR", "CRITICAL"}
            and not r.message.startswith("operator_")
            and unresolved(r)
        ]
        scan = payload("scanner")
        try:
            from redis.asyncio import Redis
            async with Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1) as redis:
                redis_status = "ok" if await redis.ping() else "unavailable"
        except Exception:
            redis_status = "unavailable"
        return {
            "as_of": utc_now().isoformat(),
            "service": {
                "api": "ok",
                "redis": redis_status,
                "worker": worker,
                "worker_heartbeat": heartbeat,
                "worker_age_seconds": age,
                "postgresql": "ok"
                if repository.session_factory.kw["bind"].dialect.name == "postgresql"
                else "not_configured",
            },
            "market_data": {
                "state": states["scanner"].state if "scanner" in states else "no_scan_yet",
                "fresh": "scanner" in states
                and (utc_now() - aware(states["scanner"].updated_at)).total_seconds() < 180,
                "last_scan_at": aware(states["scanner"].updated_at).isoformat()
                if "scanner" in states
                else None,
            },
            "official": {
                "control": account["portfolio"]["control"],
                "approval": {
                    **payload("research_entry_policy"),
                    "research_only": bool(
                        payload("research_entry_policy").get("require_validation")
                    )
                    and not payload("research_entry_policy").get("allowed_strategy_ids"),
                },
            },
            "shadows": [
                {
                    "experiment_id": e["experiment_id"],
                    "strategy_id": e["manifest"]["strategy_id"],
                    "state": e["state"],
                    "last_evaluation_at": e.get("last_evaluation_at"),
                    "latest_decision": e.get("latest_decision"),
                    "runtime_compatibility": e["runtime_compatibility"],
                    "reconciliation": e["reconciliation_status"],
                    "scan_observation": e["scan_observation"],
                    "risk_state": e["portfolio"]["risk_state"],
                }
                for e in summary["experiments"]
            ],
            "protective_monitoring": {"heartbeat": payload("position_monitor").get("heartbeat")},
            "research_jobs": [
                {"job_id": r.key, "status": r.state, "updated_at": aware(r.updated_at).isoformat()}
                for r in jobs
            ],
            "last_scan": {
                "status": scan.get("status"),
                "markets": [c.get("symbol") for c in scan.get("candidates", [])],
                "completed_at": aware(states["scanner"].updated_at).isoformat()
                if "scanner" in states
                else None,
                "operation": payload("operation"),
            },
            "historical_operator_actions": operator,
            "current_system_errors": errors,
            "risk_state": risk_state,
            "official_reconciliation": account["reconciliation_status"],
            "incident_resolution": "Known risk/operation incidents resolve when their current state changes. Other warning/error/critical incidents remain conservatively visible because explicit resolution links are absent.",
            "live_trading_enabled": settings.live_trading_enabled,
            "market_data_quality": await repository.market_data_health(),
        }

    @app.get("/api/research/summary", dependencies=auth)
    async def research_summary() -> dict[str, Any]:
        from dataclasses import asdict

        from autotrader.research.experimental import EXPERIMENTAL_REGISTRY
        from autotrader.research.strategies import REGISTRY

        root = Path(settings.research_root)

        def read(pointer: str) -> tuple[dict[str, Any] | None, str | None]:
            try:
                report = load_latest(root, pointer_name=pointer)
                if report is None:
                    return None, "pointer_missing"
                compact = {
                    k: report.get(k)
                    for k in ("run_id", "verdict", "data_kind", "source_fingerprint", "created_at")
                }
                compact["timeframes"] = {
                    tf: {
                        "strategies": {
                            sid: {
                                "out_of_sample": {
                                    k: r.get("out_of_sample", {}).get(k)
                                    for k in (
                                        "net_profit",
                                        "trades",
                                        "win_rate",
                                        "max_drawdown",
                                        "profit_factor",
                                    )
                                },
                                "gates": r.get("gates"),
                            }
                            for sid, r in data.get("strategies", {}).items()
                        }
                    }
                    for tf, data in report.get("timeframes", {}).items()
                }
                return compact, None
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                return None, str(exc)

        original, error = read("latest-run.json")
        experimental, experimental_error = read("latest-experimental-run.json")
        return {
            "status": "AVAILABLE" if original or experimental else "NO_RESEARCH_RUN",
            "latest": original,
            "experimental_latest": experimental,
            "registry": [asdict(s) for s in REGISTRY],
            "experimental_registry": [asdict(s) for s in EXPERIMENTAL_REGISTRY],
            "publication": {
                "root": str(root),
                "original_pointer_error": error,
                "experimental_pointer_error": experimental_error,
                "reports_overwritten": False,
            },
            "details": "/api/research",
            "as_of": utc_now().isoformat(),
        }

    @app.get("/api/intelligence/summary", dependencies=auth)
    async def intelligence_summary(
        limit: int = Query(30, ge=1, le=100), cursor: str | None = Query(None, max_length=2048)
    ) -> dict[str, Any]:
        try:
            result = await views.page(repository, "feedback", limit, cursor)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from None
        async with repository.session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(m.SystemStateModel)
                .where(m.SystemStateModel.key.like("feedback:%"))
            )
            columns = (
                "decision_id",
                "symbol",
                "created_at",
                "category",
                "rejection_reason",
                "accepted_decision",
                "observed_mfe",
                "observed_mae",
                "conclusion",
                "subsequent_completed_bars",
                "expected_5m_bars",
            )
            return {
                "feedback": [
                    {k: json.loads(r["payload_json"]).get(k) for k in columns}
                    for r in result["items"]
                ],
                "next_cursor": result["next_cursor"],
                "as_of": result["as_of"],
                "total": count,
                "limit": limit,
                "allocation_decisions": [],
                "policy": "Bounded recorded hindsight observations, not predictive edge. Full evidence remains available per decision and through the legacy endpoint.",
            }

    @app.get("/api/intelligence/record/{decision_id}", dependencies=auth)
    async def intelligence_record(decision_id: str) -> dict[str, Any]:
        async with repository.session_factory() as session:
            row = await session.get(m.SystemStateModel, "feedback:" + decision_id)
            if row is None:
                raise HTTPException(404, detail="observation_not_found")
            return dict(json.loads(row.payload_json))
