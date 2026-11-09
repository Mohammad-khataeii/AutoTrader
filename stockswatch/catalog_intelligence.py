"""Research-only intelligence for the full Alpaca stock catalogue.

No broker order methods. No changes to the legacy 102-symbol execution universe.
All evidence is stored in the separate catalogue SQLite database. A symbol is
never called AI-analyzed without an actual attributed model result.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import httpx

from . import asset_catalog as cat
from .market import parse_filings

UTC = timezone.utc
DDL = """
CREATE TABLE IF NOT EXISTS sw_catalog_intelligence(
    symbol TEXT PRIMARY KEY,
    history_state TEXT NOT NULL DEFAULT 'AWAITING_HISTORY',
    analyzed_at TEXT,
    last_day TEXT,
    close REAL,
    change_20d_pct REAL,
    avg_20d_iex_dollars REAL,
    sma_50 REAL,
    sma_200 REAL,
    price_score REAL,
    price_reason TEXT,
    sec_state TEXT NOT NULL DEFAULT 'PENDING',
    sec_cik INTEGER,
    sec_checked_at TEXT,
    ai_state TEXT NOT NULL DEFAULT 'NOT_EVALUATED',
    FOREIGN KEY(symbol) REFERENCES sw_catalog_assets(symbol)
);
CREATE INDEX IF NOT EXISTS sw_ci_due
    ON sw_catalog_intelligence(history_state,sec_state,price_score,analyzed_at);
CREATE TABLE IF NOT EXISTS sw_catalog_sec_tickers(
    symbol TEXT PRIMARY KEY,cik INTEGER NOT NULL,refreshed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sw_catalog_filings(
    id TEXT PRIMARY KEY,symbol TEXT NOT NULL,form TEXT NOT NULL,
    accepted_at TEXT NOT NULL,url TEXT NOT NULL,description TEXT,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sw_catalog_filings_recent
    ON sw_catalog_filings(symbol,accepted_at DESC);
CREATE TABLE IF NOT EXISTS sw_catalog_ci_meta(
    key TEXT PRIMARY KEY,value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sw_catalog_ai_insights(
    filing_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,model TEXT NOT NULL,
    analysis_json TEXT NOT NULL,generated_at TEXT NOT NULL,source_url TEXT NOT NULL
);
"""


def initialize():
    cat.initialize()
    with cat.connect() as db:
        db.executescript(DDL)
        db.execute("""INSERT OR IGNORE INTO sw_catalog_intelligence(symbol)
            SELECT symbol FROM sw_catalog_assets WHERE active=1""")


def score_daily(bars, today=None):
    """Explainable, strictly historical score; IEX volume is not SIP liquidity."""
    today = today or datetime.now(UTC).date()
    if len(bars) < 201:
        return {"state":"INSUFFICIENT_HISTORY","reason":"needs_201_completed_daily_bars"}
    v = [float(x["c"]) for x in bars]
    vols = [float(x["v"]) for x in bars]
    if any(not math.isfinite(x) or x <= 0 for x in v) or any(
            not math.isfinite(x) or x < 0 for x in vols):
        return {"state":"INVALID_HISTORY","reason":"bad_ohlcv"}
    recent_date = datetime.fromisoformat(str(bars[-1]["day"])).date()
    if (today - recent_date).days > 7:
        return {"state":"STALE_HISTORY","reason":"last_daily_bar_older_than_7_days"}
    close = v[-1]
    sma50, sma200 = sum(v[-50:])/50, sum(v[-200:])/200
    change = 100*(close/v[-21]-1)
    iex_turnover = sum(p*q for p,q in zip(v[-20:],vols[-20:]))/20
    trend = close > sma50 > sma200
    momentum = 0 < change < 25
    liquidity = iex_turnover >= 100000
    score = round((1.0 if trend else 0) +
                  (0.6 if momentum else 0) +
                  (0.4 if liquidity else 0),3)
    return {"state":"RESEARCH_READY","last_day":recent_date.isoformat(),
            "close":close,"change_20d_pct":round(change,3),
            "avg_20d_iex_dollars":round(iex_turnover,2),
            "sma_50":round(sma50,6),"sma_200":round(sma200,6),
            "score":score,
            "reason":("trend_ok" if trend else "trend_unconfirmed") + ":" +
                     ("momentum_ok" if momentum else "momentum_unconfirmed") + ":" +
                     ("iex_activity_observed" if liquidity else "iex_activity_low")}
            

def price_cycle(max_symbols=120):
    if not 1 <= max_symbols <= 300:
        raise ValueError("catalog_analysis_batch_invalid")
    initialize()
    stamp = datetime.now(UTC).isoformat()
    cutoff = (datetime.now(UTC)-timedelta(hours=24)).isoformat()
    with cat.connect(readonly=True) as db:
        targets = [r["symbol"] for r in db.execute("""
            SELECT c.symbol FROM sw_catalog_assets c
            JOIN sw_catalog_intelligence i ON i.symbol=c.symbol
            WHERE c.active=1 AND c.tradable=1 AND c.original=0
              AND c.bar_count>=201
              AND (i.analyzed_at IS NULL OR i.analyzed_at<? OR i.last_day!=c.latest_day)
            ORDER BY CASE WHEN i.analyzed_at IS NULL THEN 0 ELSE 1 END,
                     c.latest_day DESC, c.symbol
            LIMIT ?""",(cutoff,max_symbols))]
    examined=0
    for sym in targets:
        with cat.connect(readonly=True) as db:
            bars=list(db.execute(
                """SELECT day,c,v FROM sw_catalog_daily
                   WHERE symbol=? ORDER BY day DESC LIMIT 260""",(sym,)))
        result=score_daily(list(reversed(bars)))
        with cat.connect() as db:
            db.execute("""UPDATE sw_catalog_intelligence
                SET history_state=?,analyzed_at=?,last_day=?,close=?,
                    change_20d_pct=?,avg_20d_iex_dollars=?,sma_50=?,
                    sma_200=?,price_score=?,price_reason=?
                WHERE symbol=?""",(
                result["state"],stamp,result.get("last_day"),
                result.get("close"),result.get("change_20d_pct"),
                result.get("avg_20d_iex_dollars"),result.get("sma_50"),
                result.get("sma_200"),result.get("score"),result["reason"],sym))
        examined+=1
    return {"analysed_this_cycle":examined}


def _sec_mapping(client,agent,now):
    # SEC company_tickers.json mapping refreshed at most once per 24 hours.
    with cat.connect(readonly=True) as db:
        stamp=db.execute("SELECT value FROM sw_catalog_ci_meta WHERE key='sec_map_at'").fetchone()
        if stamp and stamp["value"] >= (now-timedelta(hours=24)).isoformat():
            return
    response=client.get("https://www.sec.gov/files/company_tickers.json",
                        headers={"User-Agent":agent,"Accept":"application/json"})
    response.raise_for_status()
    if len(response.content)>5000000:
        raise ValueError("sec_ticker_mapping_too_large")
    body=response.json()
    if not isinstance(body,dict) or len(body)<1000:
        raise ValueError("sec_ticker_mapping_invalid")
    values=[]
    for entry in body.values():
        if not isinstance(entry,dict):
            continue
        sym,cik=entry.get("ticker"),entry.get("cik_str")
        if isinstance(sym,str) and cat.SYMBOL.fullmatch(sym) and isinstance(cik,int) and cik>0:
            values.append((sym,cik,now.isoformat()))
    if len(values)<1000:
        raise ValueError("sec_ticker_mapping_unreliable")
    with cat.connect() as db:
        db.execute("DELETE FROM sw_catalog_sec_tickers")
        db.executemany("""INSERT INTO sw_catalog_sec_tickers(symbol,cik,refreshed_at)
                         VALUES(?,?,?)""",values)
        db.execute("""INSERT INTO sw_catalog_ci_meta(key,value) VALUES('sec_map_at',?)
             ON CONFLICT(key) DO UPDATE SET value=excluded.value""",(now.isoformat(),))


def sec_cycle(max_symbols=2):
    """SEC evidence is paced; no speculative catalyst or synthesized AI claims."""
    if not 0<=max_symbols<=3:
        raise ValueError("sec_cycle_bound_invalid")
    if max_symbols==0:
        return {"state":"DISABLED","checked":0}
    agent=os.getenv("STOCKSWATCH_SEC_USER_AGENT","").strip()
    if "@" not in agent or len(agent)>180:
        return {"state":"MISSING_SEC_USER_AGENT","checked":0}
    now=datetime.now(UTC)
    checked=0
    with httpx.Client(timeout=httpx.Timeout(18,connect=7),
                     trust_env=False,follow_redirects=False) as client:
        _sec_mapping(client,agent,now)
        with cat.connect(readonly=True) as db:
            targets=list(db.execute("""SELECT i.symbol, m.cik FROM sw_catalog_intelligence i
                JOIN sw_catalog_assets a ON a.symbol=i.symbol
                LEFT JOIN sw_catalog_sec_tickers m ON m.symbol=i.symbol
                WHERE a.active=1 AND a.tradable=1 AND a.original=0
                  AND i.history_state='RESEARCH_READY'
                  AND (i.sec_checked_at IS NULL OR i.sec_checked_at<?)
                ORDER BY i.price_score DESC, i.avg_20d_iex_dollars DESC
                LIMIT ?""",((now-timedelta(days=7)).isoformat(),max_symbols)))
        for r in targets:
            sym,cik=r["symbol"],r["cik"]
            state="NOT_IN_SEC_TICKER_MAP" if not cik else "SOURCE_ERROR"
            filings=[]
            if cik:
                try:
                    response=client.get(f"https://data.sec.gov/submissions/CIK{cik:010}.json",
                                        headers={"User-Agent":agent,"Accept":"application/json"})
                    response.raise_for_status()
                    if len(response.content)>10000000:
                        raise ValueError("sec_submissions_excess")
                    payload=response.json()
                    filings=[f for f in parse_filings(sym,cik,payload)
                             if f["accepted_at"]>=(now-timedelta(days=365)).isoformat()]
                    state="FILINGS_FOUND" if filings else "NO_RECENT_FILINGS"
                except (httpx.HTTPError,ValueError,TypeError,KeyError):
                    state="SOURCE_ERROR"
            with cat.connect() as db:
                db.executemany("""INSERT OR IGNORE INTO sw_catalog_filings
                    (id,symbol,form,accepted_at,url,description,observed_at)
                    VALUES(?,?,?,?,?,?,?)""",
                    [(f["id"],sym,f["form"],f["accepted_at"],f["url"],
                      f["description"],f["observed_at"]) for f in filings[:50]])
                db.execute("""UPDATE sw_catalog_intelligence SET sec_state=?,
                    sec_cik=?,sec_checked_at=?,ai_state=? WHERE symbol=?""",
                    (state,cik,now.isoformat(),
                     "AWAITING_MODEL_BUDGET" if filings else "NO_SOURCE_EVIDENCE",sym))
            checked+=1
            if checked<max_symbols:
                time.sleep(1.5)
    return {"state":"OK","checked":checked}



async def ai_cycle():
    """One bounded filing-metadata-only AI memo/day, using shared Redis quota.

    This deliberately does not pretend to analyze every ticker or alter BUY
    eligibility. The first day's run may be skipped if no verified SEC filing
    evidence exists, and no quota token is consumed in that case.
    """
    if os.getenv("STOCKSWATCH_GEMINI_ENABLED","true")!="true":
        return {"state":"DISABLED"}
    key=os.getenv("GEMINI_API_KEY","")
    model=os.getenv("GEMINI_MODEL","gemini-2.5-flash-lite")
    if len(key)<20:
        return {"state":"NO_KEY"}
    if model not in {"gemini-2.5-flash-lite","gemini-3.1-flash-lite","gemini-3.5-flash-lite"}:
        return {"state":"MODEL_UNAPPROVED"}
    today=datetime.now(UTC).date().isoformat()
    with cat.connect(readonly=True) as db:
        stamp=db.execute("SELECT value FROM sw_catalog_ci_meta WHERE key='ai_day'").fetchone()
        if stamp and stamp["value"]==today:
            return {"state":"DAILY_CAP"}
        filing=db.execute("""SELECT f.id,f.symbol,f.form,f.accepted_at,f.url,f.description
            FROM sw_catalog_filings f
            LEFT JOIN sw_catalog_ai_insights a ON a.filing_id=f.id
            WHERE a.filing_id IS NULL AND f.accepted_at>=?
            ORDER BY f.accepted_at DESC LIMIT 1""",
            ((datetime.now(UTC)-timedelta(days=30)).isoformat(),)).fetchone()
    if not filing:
        return {"state":"NO_VERIFIED_NEW_FILING"}
    try:
        from autotrader.api.gemini_advisory import reserve
        redis_url=os.getenv("REDIS_URL","")
        if not redis_url or not await reserve(redis_url):
            return {"state":"SHARED_GEMINI_QUOTA_LIMIT"}
    except Exception:
        return {"state":"SHARED_QUOTA_UNAVAILABLE"}
    # Reserve the catalogue's one daily attempt even if Google's API fails.
    with cat.connect() as db:
        db.execute("""INSERT INTO sw_catalog_ci_meta(key,value) VALUES('ai_day',?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",(today,))
    evidence=dict(filing)
    prompt={
        "role":"cautious SEC filing metadata researcher",
        "instruction":"Only the supplied public SEC metadata is verified. Do not infer financial results, stock performance, earnings surprises, sentiment or predictions. Explicitly state what cannot be known without filing text. Never recommend trading actions.",
        "evidence":evidence,
        "output_keys":["summary","known","unknown","risks"]
    }
    request={"contents":[{"role":"user","parts":[{"text":json.dumps(prompt)}]}],
        "generationConfig":{"temperature":0.1,"maxOutputTokens":500,
                            "responseMimeType":"application/json"}}
    async with httpx.AsyncClient(timeout=httpx.Timeout(20,connect=7),
                  trust_env=False,follow_redirects=False) as client:
        try:
            resp=await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key":key,"Content-Type":"application/json"},
                json=request)
            if resp.status_code!=200:
                return {"state":"PROVIDER_HTTP_"+str(resp.status_code)}
            raw=resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            data=json.loads(raw)
            if (not isinstance(data,dict) or
                not isinstance(data.get("summary"),str) or
                any(not isinstance(data.get(k),list) for k in ("known","unknown","risks"))):
                return {"state":"MODEL_OUTPUT_UNVERIFIED"}
            clean={k:data[k][:480] if k=="summary" else
                [x[:250] for x in data[k][:5] if isinstance(x,str)]
                for k in ("summary","known","unknown","risks")}
            clean.update({"source_url":filing["url"],"source_at":filing["accepted_at"],
                          "execution_authority":False})
            with cat.connect() as db:
                db.execute("""INSERT OR IGNORE INTO sw_catalog_ai_insights
                    (filing_id,symbol,model,analysis_json,generated_at,source_url)
                    VALUES(?,?,?,?,?,?)""",
                    (filing["id"],filing["symbol"],model,json.dumps(clean),
                     datetime.now(UTC).isoformat(),filing["url"]))
                db.execute("""UPDATE sw_catalog_intelligence SET ai_state='ATTRIBUTED_AI_NOTE'
                    WHERE symbol=?""",(filing["symbol"],))
            return {"state":"STORED","symbol":filing["symbol"]}
        except (httpx.HTTPError,ValueError,KeyError,IndexError,TypeError):
            return {"state":"PROVIDER_OR_OUTPUT_FAILURE"}


def report():
    if not cat.CATALOG_PATH.exists():
        return {"state":"NOT_INITIALIZED"}
    with cat.connect(readonly=True) as db:
        counts={r["history_state"]:r["n"] for r in db.execute(
            "SELECT history_state,COUNT(*) n FROM sw_catalog_intelligence GROUP BY history_state")}
        sec={r["sec_state"]:r["n"] for r in db.execute(
            "SELECT sec_state,COUNT(*) n FROM sw_catalog_intelligence GROUP BY sec_state")}
        ai={r["ai_state"]:r["n"] for r in db.execute(
            "SELECT ai_state,COUNT(*) n FROM sw_catalog_intelligence GROUP BY ai_state")}
        filings=db.execute("SELECT COUNT(*) n FROM sw_catalog_filings").fetchone()["n"]
        ai_notes=db.execute("SELECT COUNT(*) n FROM sw_catalog_ai_insights").fetchone()["n"]
    return {"state":"OK","price_states":counts,"sec_states":sec,
            "ai_states":ai,"sourced_filings":filings,"attributed_ai_notes":ai_notes,
            "ai_note":"No additional model inference has been run. Gemini quota and sourced evidence must be available."}


def browse(query="",limit=50,offset=0):
    if not isinstance(query,str) or len(query)>40 or not 1<=limit<=100 or not 0<=offset<=100000:
        raise ValueError("catalog_intelligence_query_invalid")
    if not cat.CATALOG_PATH.exists():
        return {"summary":{"state":"NOT_INITIALIZED"},"results":[],"total":0}
    term="%"+query.strip().upper().replace("%","\\%").replace("_","\\_")+"%"
    with cat.connect(readonly=True) as db:
        where="""FROM sw_catalog_assets a
           LEFT JOIN sw_catalog_intelligence i ON i.symbol=a.symbol
           WHERE a.active=1 AND (a.symbol LIKE ? ESCAPE '\\' OR upper(a.name) LIKE ? ESCAPE '\\')"""
        total=db.execute("SELECT COUNT(*) "+where,(term,term)).fetchone()[0]
        items=[dict(x) for x in db.execute(
            """SELECT a.symbol,a.name,a.exchange,a.status,a.bar_count,
                      i.history_state,i.price_score,i.price_reason,
                      i.last_day,i.change_20d_pct,i.avg_20d_iex_dollars,
                      i.sec_state,i.ai_state,
                      (SELECT COUNT(*) FROM sw_catalog_filings f
                       WHERE f.symbol=a.symbol) sourced_filings
            """+where+""" ORDER BY a.symbol LIMIT ? OFFSET ?""",
            (term,term,limit,offset))]
    return {"summary":report(),"results":items,"total":total,"offset":offset}


def cycle():
    px=price_cycle()
    try:
        sec=sec_cycle()
    except (httpx.HTTPError,ValueError,RuntimeError,sqlite3.Error) as exc:
        sec={"state":"DEFERRED_"+type(exc).__name__,"checked":0}
    try:
        ai=asyncio.run(ai_cycle())
    except Exception as exc:
        ai={"state":"DEFERRED_"+type(exc).__name__}
    return {"price":px,"sec":sec,"ai":ai,"summary":report()}


if __name__=="__main__":
    print(json.dumps(cycle(),sort_keys=True))
