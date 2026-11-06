"""A separate authenticated API; browser cookies verified against existing AutoTrader session server."""
from __future__ import annotations
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date,datetime,timezone
from pathlib import Path
from typing import Literal
import httpx
from fastapi import FastAPI,Depends,HTTPException,Request
from pydantic import BaseModel
from .storage import init,rows,one,setting,utc
from .ledger import mark_to_market,eligible_signals,latest_bars
from .service import Service
from .observer import init_journal, scanner_snapshot, EXPORT_TABLES, export_jsonl

logging.basicConfig(level=os.getenv('STOCKSWATCH_LOG_LEVEL','INFO'))
service=Service()

@asynccontextmanager
async def lifespan(app):
    init();init_journal();service.start()
    try:yield
    finally:await service.stop()

app=FastAPI(title='StocksWatch isolated USD simulator',version='stocks-v1',lifespan=lifespan)

@app.get('/healthz')
def health():return {'status':'ok','mode':'paper','system':'stockswatch','schema':'stocks-v1'}

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

@app.get('/api/stockswatch/status',dependencies=[Depends(authenticated)])
def status():
    counts={r['source']:r['num'] for r in rows('SELECT source,COUNT(*) num FROM bars GROUP BY source')}
    state=setting('last_cycle',{'state':'STARTING'})
    acct=one('SELECT paused FROM portfolio WHERE id=1')
    return {'mode':'PAPER_ONLY','live_trading_enabled':False,'version':'stocks-v1','provider':os.getenv('STOCKSWATCH_PRICE_PROVIDER','stooq'),
            'data_sources':counts,'cycle':state,'paper_paused':bool(acct['paused']) if acct else True,
            'gemini':'CAPPED_READ_ONLY', 'source_warnings':['Stooq EOD is NOT exchange-licensed live data',
                   'No automated use of SEC until a declared User-Agent is configured',
                   'Current universe excludes delisted stocks; historical backtests are survivorship-biased']}

@app.get('/api/stockswatch/dashboard',dependencies=[Depends(authenticated)])
def dashboard():
    account,positions,equity,exposure,drawdown=mark_to_market()
    recent=rows('SELECT * FROM equity_curve ORDER BY day DESC LIMIT 370');recent.reverse()
    decisions=rows('''SELECT d.symbol,d.signal_day,d.score,d.regime,d.signals_json,d.reasons_json,d.action,d.policy_version,a.name,a.sector
          FROM decisions d JOIN assets a ON a.symbol=d.symbol WHERE d.signal_day=(SELECT MAX(signal_day) FROM decisions)
          ORDER BY d.score DESC,d.symbol LIMIT 40''')
    for d in decisions:
        d['signals']=json.loads(d.pop('signals_json'));d['reasons']=json.loads(d.pop('reasons_json'))
    filings=rows('SELECT symbol,form,accepted_at,description,url FROM filings ORDER BY accepted_at DESC LIMIT 20')
    facts=rows('SELECT symbol,tag,value,unit,accepted_at,end_day,source_url FROM facts ORDER BY accepted_at DESC LIMIT 20')
    macro=rows('SELECT series,value,observation_day,available_at,source FROM macro ORDER BY available_at DESC LIMIT 15')
    ai=rows('SELECT symbol,analysis_json,generated_at,source_url,model FROM ai_insights ORDER BY generated_at DESC LIMIT 8')
    for a in ai:a['analysis']=json.loads(a.pop('analysis_json'))
    fills=rows('SELECT symbol,side,signal_day,fill_day,qty,price,realized,source FROM fills ORDER BY fill_day DESC,id DESC LIMIT 50')
    orders=rows("SELECT symbol,side,signal_day,state FROM pending_orders WHERE state='PENDING' ORDER BY created_at DESC LIMIT 20")
    research=one('SELECT status,report_json,created_at,source_hash FROM research_runs ORDER BY created_at DESC LIMIT 1')
    report=json.loads(research['report_json']) if research else None
    ml=one('SELECT status,metrics_json,trained_at FROM model_runs ORDER BY trained_at DESC LIMIT 1')
    model=json.loads(ml['metrics_json']) if ml else {'status':'NOT_TRAINED'}
    benchmark=(recent[-1]['spy_close']/recent[0]['spy_close']-1)*100 if len(recent)>1 and recent[0]['spy_close'] else None
    coverage=rows('SELECT a.symbol,a.name,a.sector,COUNT(b.day) bars,MAX(b.day) last_day FROM assets a LEFT JOIN bars b USING(symbol) GROUP BY a.symbol ORDER BY a.symbol')
    return {'status':setting('last_cycle',{'state':'STARTING'}),
            'account':{'currency':'USD','initial_cash':account['initial_cash'],'cash':round(account['cash'],2),
                       'equity':equity,'exposure':exposure,'realized':round(account['realized'],2),'drawdown_pct':round(drawdown*100,3),
                       'pnl':round(equity-account['initial_cash'],2),'pnl_pct':round((equity/account['initial_cash']-1)*100,3),
                       'paused':bool(account['paused'])},
            'positions':positions,'equity_curve':recent,'benchmark_change_pct':benchmark,
            'signals':decisions,'filings':filings,'fundamentals':facts,'macro':macro,'ai_insights':ai,
            'fills':fills,'pending_orders':orders,'research':{
                'status':research['status'] if research else 'NOT_RUN',
                'created_at':research['created_at'] if research else None,
                'source_hash':research['source_hash'] if research else None,
                'by_strategy':report.get('by_strategy') if report else {},'warnings':report.get('warnings') if report else [],
                'total_backtests':report.get('total_backtests') if report else 0},
            'ml':model,'coverage':coverage,'paper_only':True,
            'updated_at':utc(),'execution_mode':'NEXT_PUBLISHED_DAILY_BAR_OPEN','can_issue_live_orders':False}

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
    action:Literal['pause','resume']

@app.post('/api/stockswatch/control',dependencies=[Depends(authenticated)])
def control(body:Control):
    from .storage import connect
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('UPDATE portfolio SET paused=? WHERE id=1',(1 if body.action=='pause' else 0,))
        if body.action=='pause':
            c.execute("UPDATE pending_orders SET state='CANCELLED' WHERE state='PENDING' AND side='BUY'")
        c.commit()
    return {'paused':body.action=='pause','mode':'paper'}
