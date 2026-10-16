from __future__ import annotations

import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from sqlalchemy import select
from starlette.responses import Response

from autotrader.ai import make_ai_provider
from autotrader.api.security import AuthenticationThrottle
from autotrader.config import Settings, get_settings
from autotrader.decision import DecisionEngine
from autotrader.domain import Candle, OrderType, new_id, utc_now
from autotrader.execution_gateway import PaperExecutionGateway
from autotrader.market_data.revolut import RevolutXPublicClient
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.database import (
    check_schema,
    create_schema,
    make_engine,
    make_session_factory,
)
from autotrader.persistence.models import BacktestRunModel, MarketCandle
from autotrader.persistence.pilot import pilot_configuration
from autotrader.persistence.repository import PersistentTradingRepository, _json
from autotrader.research.artifacts import load_latest
from autotrader.research.data import ASSETS, TIMEFRAMES
from autotrader.research.strategies import REGISTRY
from autotrader.research.workflow import GRID, STRATEGIES
from autotrader.risk import RiskEngine, RiskLimits
from autotrader.scanner import MarketScanner, ScanCandidate, ScanResult
from autotrader.strategies import BreakoutStrategyEngine

security = HTTPBasic(auto_error=False)
equity_metric=Gauge('autotrader_equity_eur','Validated paper account equity')
cash_metric=Gauge('autotrader_available_cash_eur','Available paper cash')
risk_metric=Gauge('autotrader_risk_halted','Persistent non-healthy runtime state')
reconciliation_metric=Gauge('autotrader_reconciliation_errors','Financial replay mismatches')


class BacktestRequest(BaseModel):
    symbol:str=Field(default="BTC-EUR",pattern=r"^[A-Z0-9]+-EUR$")
    max_bars:int=Field(default=300,ge=51,le=500)
    entry_order_type:OrderType=OrderType.MARKET


class ResearchParametersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relative_volume: Decimal = Field(default=Decimal("1.5"), ge=1, le=4)
    compression_width: Decimal = Field(default=Decimal(".06"), ge=Decimal(".01"), le=Decimal(".2"))
    breakout_buffer: Decimal = Field(default=Decimal(".001"), ge=0, le=Decimal(".02"))
    relative_return: Decimal = Field(default=Decimal(".02"), ge=0, le=Decimal(".2"))
    stop_atr: Decimal = Field(default=Decimal("1.5"), ge=1, le=4)
    target_atr: Decimal = Field(default=Decimal("1.5"), ge=1, le=6)


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategies: list[str] = Field(default_factory=lambda:list(STRATEGIES), min_length=1, max_length=6)
    timeframes: list[str] = Field(default_factory=lambda:["1d", "4h"], min_length=1, max_length=6)
    assets: list[str] = Field(default_factory=lambda:list(ASSETS), min_length=1, max_length=8)
    grid: list[ResearchParametersRequest] = Field(default_factory=lambda:[ResearchParametersRequest.model_validate(p.payload()) for p in GRID], min_length=1, max_length=9)


class CorrectionRequest(BaseModel):
    request_id:str=Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')
    fingerprint:str=Field(pattern=r'^[a-f0-9]{64}$')
    reason:str=Field(min_length=20,max_length=2000)


class PromotionRequest(BaseModel):
    approve: bool
    reason: str = Field(min_length=20,max_length=2000)


class PilotRequest(BaseModel):
    request_id: str = Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')


class NewsRequest(BaseModel):
    event_id:str=Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')
    symbol:str=Field(pattern=r'^[A-Z0-9]+-EUR$')
    timestamp:datetime
    title:str=Field(min_length=1,max_length=300)
    body:str=Field(min_length=1,max_length=2000)
    url:HttpUrl
    source:str=Field(min_length=1,max_length=64)

    @field_validator('timestamp')
    @classmethod
    def valid_time(cls,value:datetime)->datetime:
        from datetime import timedelta
        if value.tzinfo is None or value>utc_now()+timedelta(seconds=5):
            raise ValueError('News timestamp must be timezone-aware and cannot be in the future.')
        return value


def _settings() -> Settings:
    return get_settings()


async def require_user(request: Request, credentials: HTTPBasicCredentials | None = Depends(security), settings: Settings = Depends(_settings)) -> str:
    client = request.client.host if request.client else "unknown"
    try:
        retry = await request.app.state.repository.authentication_attempt(client)
    except Exception:
        raise HTTPException(status_code=503,detail='Authentication store unavailable') from None
    if retry is not None:
        raise HTTPException(status_code=429, detail="Authentication cooldown active", headers={"Retry-After":str(retry)})
    password = settings.dashboard_password.get_secret_value()
    ok = credentials is not None and secrets.compare_digest(credentials.username.encode(), settings.dashboard_username.encode()) and secrets.compare_digest(credentials.password.encode(), password.encode())
    if not ok:
        retry = await request.app.state.repository.authentication_attempt(client,failed=True)
        if retry is not None:
            raise HTTPException(status_code=429, detail="Too many failed authentication attempts", headers={"Retry-After":str(retry)})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})
    assert credentials is not None
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
    decision_engine = DecisionEngine(risk, default_quote_amount={"conservative":Decimal(50), "balanced":Decimal(75), "opportunistic":Decimal(100)}[settings.allocation_profile])
    strategy_engine = BreakoutStrategyEngine()
    ai_provider = make_ai_provider(settings, repository)
    market_client = RevolutXPublicClient(
        base_url=settings.revolut_x_base_url,
        region=settings.revolut_x_region,
        timeout=float(settings.market_data_timeout_seconds),
        rate_reserver=repository.reserve_public_request,
    )
    market_data = MarketDataService(market_client, max_staleness_seconds=settings.market_data_max_staleness_seconds)
    gateway = PaperExecutionGateway(
        repository,
        market_data=market_data,
        risk_engine=risk,
        initial_cash=settings.initial_cash_eur,
        fee_bps=settings.default_fee_bps,
        allocation_profile=settings.allocation_profile,
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
        await repository.configure_research_policy(Path(settings.research_root), test_environment=settings.environment == "test",
            approved={s.strip() for s in settings.approved_strategy_ids.split(",") if s.strip()},
            execution_costs={'fee_bps':str(settings.default_fee_bps),'slippage_bps':str(settings.default_slippage_bps),'spread_bps':'10','volume_participation':'.01'})
        strategy_engine.member_parameters=await repository.frozen_runtime_parameters()
        yield
        await market_data.close()
        await engine.dispose()

    app = FastAPI(title=settings.app_name, version="4.1.0", lifespan=lifespan)
    app.state.auth_throttle = AuthenticationThrottle()
    app.state.repository = repository
    app.state.engine = engine
    app.state.market_data = market_data
    app.state.scanner = scanner_service
    app.state.execution_gateway = gateway

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "mode": "paper", "version":"4.1.0"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str | bool]:
        try:
            await check_schema(engine)
        except Exception:
            raise HTTPException(status_code=503, detail="Schema unavailable or incompatible") from None
        return {"ready": True, "live_trading_enabled": settings.live_trading_enabled}

    @app.get("/metrics", dependencies=[Depends(require_user)])
    async def metrics() -> Response:
        snapshot=await repository.snapshot()
        if snapshot['equity']:
            equity_metric.set(float(snapshot['equity']))
        else:
            equity_metric.set(float('nan'))
        cash_metric.set(float(snapshot['available_cash']))
        risk_metric.set(snapshot['risk_state']!='HEALTHY')
        reconciliation_metric.set(len(await repository.verify_invariants(Decimal(500))))
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/overview", dependencies=[Depends(require_user)])
    async def overview() -> dict[str, object]:
        snapshot = await repository.snapshot()
        return {
            "application_version":"4.1.0",
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

    @app.get('/api/reconciliation/repair-plan',dependencies=[Depends(require_user)])
    async def correction_plan()->dict[str,Any]:
        from autotrader.persistence.corrections import review_projection_repair
        try:
            return await review_projection_repair(repository)
        except ValueError as exc:
            raise HTTPException(status_code=409,detail=str(exc)) from None

    @app.post('/api/reconciliation/repair')
    async def correction_apply(request:CorrectionRequest,actor:str=Depends(require_user))->dict[str,str]:
        from autotrader.persistence.corrections import apply_projection_repair
        try:
            return await apply_projection_repair(repository,request_id=request.request_id,
                fingerprint=request.fingerprint,actor=actor,reason=request.reason)
        except ValueError as exc:
            raise HTTPException(status_code=409,detail=str(exc)) from None

    @app.get("/api/ai", dependencies=[Depends(require_user)])
    async def ai_status() -> dict[str, object]:
        return {"provider":settings.ai_provider.value,"model":settings.ai_model if settings.ai_provider.value=="openai" else "mock-v1" if settings.ai_provider.value=="mock" else "",
            "enabled":settings.ai_provider.value!='off',
            "paid_enabled":settings.ai_provider.value=='openai',
            "budget":await repository.ai_budget_status(settings.ai_monthly_budget_usd,
                max_per_day=settings.ai_max_analyses_per_day,max_per_hour=settings.ai_max_analyses_per_hour),
            "account_model_verified":False if settings.ai_provider.value!="openai" else "verified_per_request"}

    @app.post('/api/news',dependencies=[Depends(require_user)])
    async def ingest_news(request:NewsRequest)->dict[str,str]:
        try:
            await repository.record_news(request.event_id,request.symbol,request.timestamp,request.title,
                request.body,str(request.url),request.source)
        except ValueError as exc:
            raise HTTPException(status_code=409,detail=str(exc)) from None
        return {'event_id':request.event_id,'status':'UNVERIFIED_EXTERNAL_CONTEXT'}

    @app.get('/api/research/promotions',dependencies=[Depends(require_user)])
    async def promotions() -> Any:
        return await repository.promotion_candidates()

    @app.post('/api/research/promotions/{candidate_id}')
    async def promotion_decision(candidate_id: str, request: PromotionRequest, actor: str = Depends(require_user)) -> Any:
        try:
            await repository.decide_promotion(candidate_id,approve=request.approve,actor=actor,reason=request.reason)
            await repository.configure_research_policy(Path(settings.research_root),test_environment=settings.environment=='test',approved=set(),
                execution_costs={'fee_bps':str(settings.default_fee_bps),'slippage_bps':str(settings.default_slippage_bps),'spread_bps':'10','volume_participation':'.01'})
            strategy_engine.member_parameters=await repository.frozen_runtime_parameters()
            return await repository.promotion_candidates()
        except ValueError as exc:
            raise HTTPException(status_code=409,detail=str(exc)) from None

    @app.get('/api/pilots',dependencies=[Depends(require_user)])
    async def pilots() -> Any:
        return await repository.pilots()

    @app.post('/api/pilots',dependencies=[Depends(require_user)],status_code=201)
    async def start_pilot(request: PilotRequest) -> Any:
        try:
            return await repository.start_pilot(request.request_id,pilot_configuration(settings),test_environment=settings.environment=='test')
        except ValueError as exc:
            raise HTTPException(status_code=409,detail=str(exc)) from None

    @app.get('/api/pilots/{pilot_id}/report',dependencies=[Depends(require_user)])
    async def pilot_report(pilot_id: str, day: date | None = None, format: Literal['json','csv'] = 'json') -> Any:
        try:
            report=await repository.pilot_report(pilot_id,day)
        except ValueError as exc:
            raise HTTPException(status_code=409,detail=str(exc)) from None
        if format=='csv':
            import csv
            import io
            stream=io.StringIO()
            writer=csv.DictWriter(stream,fieldnames=list(report))
            writer.writeheader()
            writer.writerow({key:json.dumps(value) if isinstance(value,(list,dict)) else value for key,value in report.items()})
            return Response(stream.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="paper-pilot-report.csv"'})
        return report

    @app.get("/api/settings", dependencies=[Depends(require_user)])
    async def safe_settings() -> dict[str,object]:
        from dataclasses import asdict
        return {"mode":"paper","initial_cash_eur":"500","base_currency":"EUR",
            "risk_limits":_jsonable(asdict(risk.limits)),"ai_provider":settings.ai_provider.value,
            "ai_model":settings.ai_model,"scanner_max_pairs":settings.scanner_max_pairs,
            "scan_interval_seconds":settings.worker_scan_interval_seconds,"live_execution":False,
            "allocation_profile":settings.allocation_profile,"strategy_promotion":"explicit approval plus matching validated research required"}

    @app.get("/api/execution", dependencies=[Depends(require_user)])
    async def execution_quality() -> dict[str, Any]:
        return await repository.execution_analytics(settings.default_fee_bps, settings.default_slippage_bps)

    @app.get("/api/intelligence", dependencies=[Depends(require_user)])
    async def opportunity_intelligence() -> dict[str, Any]:
        return await repository.opportunity_analytics()

    @app.get("/api/research", dependencies=[Depends(require_user)])
    async def research_catalog() -> dict[str, Any]:
        from dataclasses import asdict
        root = Path(settings.research_root)
        try:
            latest = load_latest(root)
            catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8")) if (root / "catalog.json").exists() else {}
        except (ValueError, OSError) as exc:
            return {"status":"DATA_UNAVAILABLE", "error":str(exc), "datasets":[], "latest":None}
        return {"status":"AVAILABLE" if latest else "NO_RESEARCH_RUN", "latest":latest,
            "runs":[{"run_id":path.parent.name, "verdict":json.loads(path.read_text(encoding="utf-8")).get("verdict")} for path in sorted(root.glob("runs/*/summary.json"), reverse=True)][:30],
            "jobs":await repository.research_jobs(),
            "datasets":[{k:v for k,v in m.items() if k not in {"provenance", "gaps"}} for m in catalog.get("manifests", [])],
            "registry":[asdict(spec) for spec in REGISTRY], "acquisition_failures":catalog.get("failures", []),
            "promotions":await repository.promotion_candidates()}

    @app.post("/api/research/jobs", dependencies=[Depends(require_user)], status_code=202)
    async def queue_research(request: ResearchRequest) -> dict[str, str]:
        if any(s not in STRATEGIES for s in request.strategies) or any(a not in ASSETS for a in request.assets) or any(tf not in TIMEFRAMES for tf in request.timeframes):
            raise HTTPException(status_code=400, detail="Unknown strategy or EUR asset")
        try:
            job_id = await repository.queue_research(request.model_dump(mode="json"))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return {"job_id":job_id, "status":"QUEUED", "worker":"Dedicated research worker; paper protection remains independent"}

    @app.get("/api/research/runs/{run_id}/{artifact}", dependencies=[Depends(require_user)])
    async def research_artifact(run_id: str, artifact: str) -> dict[str, Any]:
        import re
        if not re.fullmatch(r"research-\d{8}T\d{6}", run_id) or (artifact != "summary.json" and not re.fullmatch(r"(?:1m|5m|15m|1h|4h|1d)-[A-Z0-9_]+-(?:test|validation)\.json", artifact)):
            raise HTTPException(status_code=400, detail="Unsupported research artifact identity")
        root = Path(settings.research_root).resolve()
        path = (root / "runs" / run_id / artifact).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(status_code=404, detail="Research artifact not found")
        return dict(json.loads(path.read_text(encoding="utf-8")))

    @app.get("/api/backtests", dependencies=[Depends(require_user)])
    async def backtest_runs() -> dict[str,object]:
        async with repository.session_factory() as session:
            rows=(await session.scalars(select(BacktestRunModel).order_by(BacktestRunModel.started_at.desc()).limit(20))).all()
            return {"runs":[{"run_id":r.run_id,"symbol":r.symbol,"started_at":r.started_at.isoformat(),
                "completed_at":r.completed_at.isoformat() if r.completed_at else None,"payload_json":json.loads(r.payload_json)} for r in rows]}

    @app.post("/api/backtests", dependencies=[Depends(require_user)])
    async def run_historical_backtest(request:BacktestRequest) -> dict[str,object]:
        from dataclasses import asdict

        from autotrader.backtest import Backtester
        from autotrader.domain import TradingPair
        from autotrader.portfolio import Portfolio
        async with repository.session_factory() as session:
            rows=(await session.scalars(select(MarketCandle).where(MarketCandle.symbol==request.symbol,
                MarketCandle.timeframe=="5m").order_by(MarketCandle.timestamp.desc()).limit(request.max_bars))).all()
            if len(rows)<51:
                raise HTTPException(status_code=409,detail="At least 51 persisted closed candles are required.")
            candles=[Candle(r.symbol,r.timestamp.replace(tzinfo=__import__('datetime').UTC) if r.timestamp.tzinfo is None else r.timestamp,
                r.open,r.high,r.low,r.close,r.volume,r.timeframe,r.source) for r in reversed(rows)]
        run_id=new_id("bt")
        async with repository.session_factory() as session,session.begin():
            session.add(BacktestRunModel(run_id=run_id,strategy_id="ensemble-v3.4",symbol=request.symbol,
                started_at=utc_now(),payload_json='{"status":"RUNNING"}'))
        try:
            report=await Backtester(TradingPair(request.symbol,request.symbol.split('-')[0],'EUR'),
                Portfolio(Decimal(500)),DecisionEngine(RiskEngine(RiskLimits())),entry_order_type=request.entry_order_type).run_async(candles)
            result={"status":"COMPLETED","report":asdict(report)}
        except Exception as exc:
            result={"status":"FAILED","error":type(exc).__name__}
        async with repository.session_factory() as session,session.begin():
            row=await session.get(BacktestRunModel,run_id)
            assert row is not None
            row.completed_at,row.payload_json=utc_now(),_json(result)
        return {"run_id":run_id,**_jsonable(result)}

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
        return await repository.read_scan()

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
