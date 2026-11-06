"""A separate authenticated API; browser cookies verified against existing AutoTrader session server."""

from __future__ import annotations
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from functools import lru_cache
from typing import Literal
import httpx
from fastapi import FastAPI, Depends, HTTPException, Request
from pydantic import BaseModel
from .storage import connect, init, init_execution, one, rows, setting, utc, worker_ownership
from .ledger import EXECUTION_MODE, mark_to_market, outcome
from .alpaca_paper import PaperError, broker_mode, broker_init, enrich_dashboard, broker_status, set_broker_paused
from .service import Service, daily_refresh_due
from . import intraday_store, backfill
from .observer import init_journal, scanner_snapshot, EXPORT_TABLES, export_jsonl

logging.basicConfig(level=os.getenv("STOCKSWATCH_LOG_LEVEL", "INFO"))
# httpx INFO includes URLs with query strings, including broker IDs and API parameters.
logging.getLogger("httpx").setLevel(logging.WARNING)
service = Service()


@asynccontextmanager
async def lifespan(app):
    with worker_ownership():
        init()
        init_execution()
        init_journal()
        if broker_mode():
            broker_init()
        intraday_store.initialize()
        backfill.initialize()
        service.start()
        try:
            yield
        finally:
            await service.stop()


app = FastAPI(title="StocksWatch isolated USD simulator", version="stocks-v1", lifespan=lifespan)


@app.get("/healthz")
def health():
    return {"status": "ok", "mode": "alpaca_paper" if broker_mode() else "paper",
            "system": "stockswatch", "schema": "stocks-v1"}


async def authenticated(req:Request):
    # Forward ONLY the signed session cookie. Other domain cookies may make the raw
    # Cookie header exceed 4096 bytes, and must never be sent to the core backend.
    # The core backend remains the sole authentication and CSRF authority.
    import re
    raw=req.headers.get('cookie','')
    if not raw or len(raw)>16384:
        raise HTTPException(status_code=401,detail='StocksWatch session cookie missing or oversized')
    match=re.search(r'(?:^|;[ ]*)personal_plan_session=([A-Za-z0-9._-]{40,512})(?=;|$)',raw)
    if not match:
        raise HTTPException(status_code=401,detail='StocksWatch session cookie not received')
    only_session='personal_plan_session='+match.group(1)
    try:
        async with httpx.AsyncClient(timeout=6,trust_env=False) as client:
            r=await client.get('http://backend:8000/api/session',headers={'Cookie':only_session})
        if r.status_code==401:
            raise HTTPException(status_code=401,detail='StocksWatch session rejected by core backend')
        if r.status_code!=200:
            raise HTTPException(status_code=503,detail='StocksWatch core session service unavailable')
        proof=r.json().get('csrf_token','')
        if not isinstance(proof,str) or not proof:
            raise HTTPException(status_code=503,detail='StocksWatch core session proof unavailable')
        if req.method not in ('GET','HEAD','OPTIONS') and req.headers.get('x-csrf-token')!=proof:
            raise HTTPException(status_code=403,detail='Invalid session write token')
        return True
    except HTTPException:raise
    except (httpx.HTTPError,ValueError,KeyError):
        raise HTTPException(status_code=503,detail='StocksWatch authentication service unavailable') from None


def cycle_status():
    from .sessions import completed_day, instant

    last = setting("last_cycle", {"state": "STARTING"})
    if broker_mode():
        paper = service.broker_result
        return {**last, "state": paper["status"], "paper": paper, "scanner_state": service.last_result["state"]}
    if service.last_result.get("state") in {"STARTING", "ERROR"}:
        return service.last_result
    stamp = last.get("completed_at")
    now = datetime.now(timezone.utc)
    tick = max(120, min(86400, int(os.getenv("STOCKSWATCH_TICK_SECONDS", "900"))))
    if not stamp or (now - instant(stamp)).total_seconds() > tick + 300:
        return {**last, "state": "ERROR", "reason": "worker_cycle_stale"}
    paper = last.get("paper", {})
    if paper.get("status") == "ERROR":
        return last
    if paper.get("market_day") != completed_day(now):
        return {**last, "state": "WAITING_FOR_DATA", "reason": "new_completed_session"}
    next_open = paper.get("next_core_open")
    if next_open and now >= instant(next_open):
        return {**last, "state": "WAITING_FOR_NEXT_SESSION", "reason": "observation_window_closed"}
    return last


@app.get("/api/stockswatch/status", dependencies=[Depends(authenticated)])
def status():
    counts = {
        r["source"]: r["num"] for r in rows("SELECT source,COUNT(*) num FROM bars GROUP BY source")
    }
    state = cycle_status()
    broker = broker_status() if broker_mode() else None
    acct = broker if broker else one("SELECT paused FROM portfolio WHERE id=1")
    return {
        "mode": "ALPACA_PAPER" if broker_mode() else "PAPER_ONLY",
        "broker_connection": broker,
        "live_trading_enabled": False,
        "version": "stocks-v1",
        "provider": os.getenv("STOCKSWATCH_PRICE_PROVIDER", "stooq"),
        "data_sources": counts,
        "cycle": state,
        "paper_paused": bool(acct["paused"]) if acct else True,
        "gemini": "CAPPED_READ_ONLY",
        "source_warnings": [
            "Stooq EOD is NOT exchange-licensed live data",
            "No automated use of SEC until a declared User-Agent is configured",
            "Current universe excludes delisted stocks; historical backtests are survivorship-biased",
        ],
    }


@lru_cache(maxsize=1)
def load_research_evidence():
    path = Path(__file__).with_name("research_evidence.json")
    return json.loads(path.read_text()) if path.is_file() else None


@app.get("/api/stockswatch/dashboard", dependencies=[Depends(authenticated)])
def dashboard():
    broker = broker_mode()
    if not broker:
        account, positions, equity, exposure, drawdown = mark_to_market()
    recent = [] if broker else rows("SELECT * FROM equity_curve ORDER BY day DESC LIMIT 370")
    recent.reverse()
    decisions = rows("""SELECT d.symbol,d.signal_day,d.score,d.regime,d.signals_json,d.reasons_json,d.action,d.policy_version,a.name,a.sector
          FROM decisions d JOIN assets a ON a.symbol=d.symbol WHERE d.signal_day=(SELECT MAX(signal_day) FROM decisions)
          ORDER BY d.score DESC,d.symbol LIMIT 40""")
    for d in decisions:
        d["signals"] = json.loads(d.pop("signals_json"))
        d["reasons"] = json.loads(d.pop("reasons_json"))
    filings = rows(
        "SELECT symbol,form,accepted_at,description,url FROM filings ORDER BY accepted_at DESC LIMIT 20"
    )
    facts = rows(
        "SELECT symbol,tag,value,unit,accepted_at,end_day,source_url FROM facts ORDER BY accepted_at DESC LIMIT 20"
    )
    macro = rows(
        "SELECT series,value,observation_day,available_at,source FROM macro ORDER BY available_at DESC LIMIT 15"
    )
    ai = rows(
        "SELECT symbol,analysis_json,generated_at,source_url,model FROM ai_insights ORDER BY generated_at DESC LIMIT 8"
    )
    for a in ai:
        a["analysis"] = json.loads(a.pop("analysis_json"))
    fills = [] if broker else rows("""SELECT f.*,o.detail_json FROM fills f LEFT JOIN sw_order_outcomes o
        ON o.order_id=f.order_id ORDER BY f.created_at DESC,f.id DESC LIMIT 50""")
    for fill in fills:
        fill["evidence"] = json.loads(fill.pop("detail_json") or "{}")
    orders = [] if broker else rows("""SELECT p.id,p.symbol,p.side,p.signal_day,p.state,p.created_at,e.target_day,o.reason,o.recorded_at
        FROM pending_orders p LEFT JOIN sw_order_evidence e ON e.order_id=p.id
        LEFT JOIN sw_order_outcomes o ON o.order_id=p.id
        ORDER BY (p.state='PENDING') DESC,p.created_at DESC LIMIT 50""")
    last_fill = {} if broker else one("""SELECT MAX(CASE WHEN side='BUY' THEN created_at END) last_buy,
        MAX(CASE WHEN side='SELL' THEN created_at END) last_sell FROM fills""")
    price_updates = rows("""SELECT symbol,day,observed_at,source,c FROM sw_eod_observations
        ORDER BY day DESC,observed_at DESC,symbol LIMIT 20""")
    research = one(
        "SELECT status,report_json,created_at,source_hash FROM research_runs ORDER BY created_at DESC LIMIT 1"
    )
    report = json.loads(research["report_json"]) if research else None
    ml = one(
        "SELECT status,metrics_json,trained_at FROM model_runs ORDER BY trained_at DESC LIMIT 1"
    )
    model = json.loads(ml["metrics_json"]) if ml else {"status": "NOT_TRAINED"}
    spy_marks = [row["spy_close"] for row in recent if row["spy_close"]]
    benchmark = (spy_marks[-1] / spy_marks[0] - 1) * 100 if len(spy_marks) > 1 else None
    comparison = load_research_evidence()
    coverage = rows(
        "SELECT a.symbol,a.name,a.sector,COUNT(b.day) bars,MAX(b.day) last_day FROM assets a LEFT JOIN bars b USING(symbol) GROUP BY a.symbol ORDER BY a.symbol"
    )
    state = cycle_status()
    payload = {
        "status": state,
        "account": {} if broker else {
            "currency": "USD",
            "initial_cash": account["initial_cash"],
            "cash": round(account["cash"], 2),
            "equity": equity,
            "exposure": exposure,
            "unrealized": round(sum(p["unrealized"] for p in positions), 2),
            "realized": round(account["realized"], 2),
            "drawdown_pct": round(drawdown * 100, 3),
            "pnl": round(equity - account["initial_cash"], 2),
            "pnl_pct": round((equity / account["initial_cash"] - 1) * 100, 3),
            "paused": bool(account["paused"]),
        },
        "positions": [] if broker else positions,
        "equity_curve": recent,
        "benchmark_change_pct": benchmark,
        "signals": state["paper"].get("signals", []) if broker else decisions,
        "filings": filings,
        "fundamentals": facts,
        "macro": macro,
        "ai_insights": ai,
        "fills": fills,
        "pending_orders": [o for o in orders if o["state"] == "PENDING"],
        "order_history": [o for o in orders if o["state"] != "PENDING"],
        "last_fill": last_fill,
        "price_updates": price_updates,
        "historical_comparison": comparison,
        "research": {
            "status": research["status"] if research else "NOT_RUN",
            "created_at": research["created_at"] if research else None,
            "source_hash": research["source_hash"] if research else None,
            "by_strategy": report.get("by_strategy") if report else {},
            "warnings": report.get("warnings") if report else [],
            "total_backtests": report.get("total_backtests") if report else 0,
        },
        "ml": model,
        "coverage": coverage,
        "paper_only": True,
        "updated_at": utc(),
        "execution_mode": EXECUTION_MODE,
        "can_issue_live_orders": False,
    }
    return enrich_dashboard(payload) if broker else payload


@app.get("/api/stockswatch/intraday", dependencies=[Depends(authenticated)])
def intraday():
    result = intraday_store.status()
    result["orders"] = intraday_store.order_history() if broker_mode() else []
    result["daily_refresh_due"] = daily_refresh_due(datetime.now(timezone.utc))
    result.setdefault("tracked", one("SELECT COUNT(*) AS n FROM assets")["n"])
    result["missed_proxies"] = intraday_store.missed_proxies()
    return result


@lru_cache(maxsize=1)
def _universe_snapshot(bucket):
    return backfill.report(datetime.now(timezone.utc))


@app.get("/api/stockswatch/universe", dependencies=[Depends(authenticated)])
def universe():
    return _universe_snapshot(int(datetime.now(timezone.utc).timestamp())//60)


@app.get('/api/stockswatch/scanner', dependencies=[Depends(authenticated)])
def scanner():
    return scanner_snapshot()


@app.get('/api/stockswatch/export/{kind}', dependencies=[Depends(authenticated)])
def export(kind:str):
    from fastapi.responses import StreamingResponse
    if kind != "all" and kind not in EXPORT_TABLES:
        raise HTTPException(404,'Unknown StocksWatch dataset')
    return StreamingResponse(export_jsonl(kind),media_type='application/x-ndjson',
        headers={'Content-Disposition':f'attachment; filename="stockswatch-{kind}.jsonl"',
                 'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


class Control(BaseModel):
    action: Literal["pause", "resume"]


@app.post("/api/stockswatch/control", dependencies=[Depends(authenticated)])
def control(body: Control):
    if broker_mode():
        try:
            return set_broker_paused(body.action == "pause")
        except PaperError as exc:
            raise HTTPException(409, detail=str(exc)) from None
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("UPDATE portfolio SET paused=? WHERE id=1", (1 if body.action == "pause" else 0,))
        if body.action == "pause":
            for order in c.execute(
                "SELECT * FROM pending_orders WHERE state='PENDING' AND side='BUY'"
            ).fetchall():
                outcome(c, order, "CANCELLED", "manual_buy_pause", datetime.now(timezone.utc))
        c.commit()
    return {"paused": body.action == "pause", "mode": "paper"}
