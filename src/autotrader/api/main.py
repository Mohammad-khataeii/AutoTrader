from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from autotrader.ai import make_ai_provider
from autotrader.config import Settings, get_settings
from autotrader.decision import DecisionEngine
from autotrader.execution_gateway import PaperExecutionGateway
from autotrader.market_data.revolut import RevolutXPublicClient
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.database import (
    check_schema,
    create_schema,
    make_engine,
    make_session_factory,
)
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.risk import RiskEngine, RiskLimits
from autotrader.scanner import MarketScanner, ScanCandidate, ScanResult
from autotrader.strategies import BreakoutStrategyEngine

security = HTTPBasic()


def _settings() -> Settings:
    return get_settings()


def require_user(credentials: HTTPBasicCredentials = Depends(security), settings: Settings = Depends(_settings)) -> str:
    password = settings.dashboard_password.get_secret_value()
    ok = secrets.compare_digest(credentials.username, settings.dashboard_username) and secrets.compare_digest(credentials.password, password)
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})
    return credentials.username


def create_app() -> FastAPI:
    settings = get_settings()
    engine = make_engine(settings)
    repository = PersistentTradingRepository(make_session_factory(engine))
    risk = RiskEngine(
        RiskLimits(
            max_allocated_capital=settings.max_allocated_capital_eur,
            max_total_open_exposure=settings.max_total_open_exposure_eur,
            min_uncommitted_reserve=settings.min_uncommitted_reserve_eur,
            max_position_size=settings.max_position_size_eur,
            max_simultaneous_positions=settings.max_simultaneous_positions,
            max_planned_loss_per_trade=settings.max_planned_loss_per_trade_eur,
            daily_loss_threshold=settings.daily_loss_threshold_eur,
            weekly_loss_threshold=settings.weekly_loss_threshold_eur,
            max_new_entries_per_day=settings.max_new_entries_per_day,
        )
    )
    decision_engine = DecisionEngine(risk)
    strategy_engine = BreakoutStrategyEngine()
    ai_provider = make_ai_provider(settings, repository)
    market_client = RevolutXPublicClient(
        base_url=settings.revolut_x_base_url,
        region=settings.revolut_x_region,
        timeout=float(settings.market_data_timeout_seconds),
    )
    market_data = MarketDataService(market_client, max_staleness_seconds=settings.market_data_max_staleness_seconds)
    gateway = PaperExecutionGateway(
        repository,
        market_data=market_data,
        risk_engine=risk,
        initial_cash=settings.initial_cash_eur,
        fee_bps=settings.default_fee_bps,
        slippage_bps=settings.default_slippage_bps,
    )
    scanner_service = MarketScanner(
        market_data=market_data,
        repository=repository,
        strategy_engine=strategy_engine,
        decision_engine=decision_engine,
        ai_provider=ai_provider,
        initial_cash=settings.initial_cash_eur,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await create_schema(engine)
        await repository.initialize_portfolio(settings.initial_cash_eur)
        yield
        await market_data.close()
        await engine.dispose()

    app = FastAPI(title=settings.app_name, version="3.4.0", lifespan=lifespan)
    app.state.repository = repository
    app.state.engine = engine
    app.state.market_data = market_data
    app.state.scanner = scanner_service
    app.state.execution_gateway = gateway

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "mode": "paper"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str | bool]:
        try:
            await check_schema(engine)
        except Exception:
            raise HTTPException(status_code=503, detail="Schema unavailable or incompatible") from None
        return {"ready": True, "live_trading_enabled": settings.live_trading_enabled}

    @app.get("/metrics", dependencies=[Depends(require_user)])
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/overview", dependencies=[Depends(require_user)])
    async def overview() -> dict[str, object]:
        snapshot = await repository.snapshot()
        return {
            "portfolio": snapshot,
            "health": {
                "api": "ok",
                "risk": snapshot.get("risk_state", "UNKNOWN"),
                "ai_provider": settings.ai_provider,
                "market_data": "revolut-x-public",
                "mode": "paper",
            },
            "orders": await repository.list_orders(),
            "fills": await repository.list_fills(),
            "positions": [_jsonable(position) for position in await repository.list_positions()],
            "targets": await repository.list_targets(),
        }

    @app.post("/api/controls/{action}", dependencies=[Depends(require_user)])
    async def paper_control(action: str) -> dict[str, str]:
        try:
            return {"control": await repository.set_control(action), "mode": "paper"}
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/api/risk/recover", dependencies=[Depends(require_user)])
    async def recover_risk() -> dict[str, str]:
        problems = await repository.reset_runtime_health_after_reconciliation(settings.initial_cash_eur)
        if problems:
            raise HTTPException(status_code=409, detail=problems)
        return {"risk_state": (await repository.get_runtime_health()).value}

    @app.get("/api/history", dependencies=[Depends(require_user)])
    async def history() -> dict[str, object]:
        return await repository.history()

    @app.get("/api/system", dependencies=[Depends(require_user)])
    async def system_health() -> dict[str, object]:
        health = await repository.operational_health()
        try:
            from redis.asyncio import Redis
            async with Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1) as redis:
                health["redis"] = "ok" if await redis.ping() else "unavailable"
        except Exception:
            health["redis"] = "unavailable"
        return health

    @app.get("/api/scanner", dependencies=[Depends(require_user)])
    async def scanner() -> dict[str, object]:
        result = await app.state.scanner.scan_once(settings.scanner_max_pairs)
        return _scan_response(result)

    @app.post("/api/paper/orders", dependencies=[Depends(require_user)])
    async def create_paper_order() -> Any:
        result = await app.state.scanner.scan_once(settings.scanner_max_pairs)
        candidate = result.best
        if candidate is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_scan_response(result))
        execution = await app.state.execution_gateway.execute_entry_decision(
            candidate.market.pair,
            candidate.decision,
            candidate.market.order_book,
            candidate.decision.decision_id,
        )
        if not execution.accepted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"status": "REJECTED", "reason": execution.reason, "scanner": _scan_response(result)},
            )
        return {"status": "ACCEPTED", "reason": execution.reason, "order": _jsonable(execution.order)}

    return app


def _scan_response(result: ScanResult) -> dict[str, object]:
    best = result.best
    return {
        "status": result.status,
        "scanned": result.scanned,
        "duration_ms": str(result.duration_ms),
        "rejected": _jsonable(result.rejected),
        "provider_errors": result.provider_errors,
        "candidates": [_candidate_json(candidate) for candidate in result.candidates],
        "features": _jsonable(best.features) if best else {},
        "signals": [_jsonable(signal) for signal in best.signals] if best else [],
        "ai": _jsonable(best.ai_assessment) if best else {},
        "decision": _jsonable(best.decision) if best else {"action": "WAIT", "accepted": False, "explanation": result.status},
    }


def _candidate_json(candidate: ScanCandidate) -> dict[str, object]:
    return {
        "symbol": candidate.market.pair.symbol,
        "score": str(candidate.score),
        "quality": candidate.market.quality.value,
        "decision": _jsonable(candidate.decision),
        "signals": [_jsonable(signal) for signal in candidate.signals],
        "market": {
            "best_bid": str(candidate.market.metrics.best_bid),
            "best_ask": str(candidate.market.metrics.best_ask),
            "mid": str(candidate.market.metrics.mid),
            "spread_bps": str(candidate.market.metrics.spread_bps),
            "liquidity_quote": str(candidate.market.metrics.liquidity_quote),
            "order_book_age_seconds": str(candidate.market.metrics.age_seconds),
            "provider_latency_ms": str(candidate.market.metrics.provider_latency_ms),
        },
    }


def _jsonable(value: object) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dict__"):
        return {key: _jsonable(item) for key, item in value.__dict__.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


app = create_app()


def run() -> None:
    uvicorn.run("autotrader.api.main:app", host="0.0.0.0", port=8000, reload=False)
