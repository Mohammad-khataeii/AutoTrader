"""GET-only staged daily-history warmup for the additional 50 StocksWatch stocks.

This is not an order or signal submission route. It never alters existing
stocks/crypto positions, existing paper intents, execution switches, daily
price-check certificates or the already-approved OCO manager.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from . import backfill, market, storage
from .sessions import completed_day, history_days, instant, published_after
from .universe import EXPANSION50, REGISTRY

log=logging.getLogger(__name__)
SYMBOLS=tuple(s for s,_,_ in EXPANSION50)
SCHEMA="""
CREATE TABLE IF NOT EXISTS sw_expansion50_warmup (
 symbol TEXT PRIMARY KEY, status TEXT NOT NULL, attempted_at TEXT,
 daily_bars INTEGER NOT NULL DEFAULT 0, first_day TEXT, last_day TEXT,
 error TEXT);
"""


def initialize():
    with storage.connect() as conn:
        conn.executescript(SCHEMA)


def snapshot():
    initialize()
    old={r["symbol"]:r for r in storage.rows(
        "SELECT * FROM sw_expansion50_warmup ORDER BY symbol")}
    return [old.get(sym,{"symbol":sym,"status":"QUEUED","daily_bars":0})
            for sym in SYMBOLS]


def verify_201(symbol,day):
    expected=history_days(day)
    with storage.connect() as conn:
        records=conn.execute("""SELECT day,source,adjustment FROM bars
            WHERE symbol=? AND day<=? ORDER BY day DESC LIMIT 201""",
            (symbol,day)).fetchall()
    records=list(reversed(records))
    return (len(records)==201
            and tuple(x["day"] for x in records)==expected
            and all(x["source"]=="alpaca_iex_daily" and x["adjustment"]=="RAW"
                    for x in records))


def _save_status(symbol,status,now,*,n=0,first=None,last=None,error=None):
    assert symbol in SYMBOLS
    with storage.connect() as c:
        c.execute("""INSERT INTO sw_expansion50_warmup
            (symbol,status,attempted_at,daily_bars,first_day,last_day,error)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
            status=excluded.status,attempted_at=excluded.attempted_at,
            daily_bars=excluded.daily_bars,first_day=excluded.first_day,
            last_day=excluded.last_day,error=excluded.error""",
            (symbol,status,now.isoformat(),n,first,last,error))


def _store(symbol,bars,now,day):
    """Only validated completed IEX RAW daily bars; no execution certificates."""
    if symbol not in SYMBOLS:
        raise ValueError("expansion50_symbol_outside_allowlist")
    validated=market.validate_bars(bars,day)
    if len(validated)!=len(bars):
        raise ValueError("expansion50_unverified_provider_bar")
    if any(not published_after(b["day"])<=now for b in bars):
        raise ValueError("expansion50_unpublished_daily_candle")
    order={b["day"]:b for b in bars}
    if len(order)!=len(bars):
        raise ValueError("expansion50_duplicate_daily_date")
    observed=now.isoformat()
    local=[(symbol,b["day"],b["o"],b["h"],b["l"],b["c"],b["v"],
            "alpaca_iex_daily","RAW",observed) for b in bars]
    archive=[(symbol,"1Day","iex","raw",b["t"],b["day"],"DAILY",
              observed,*(str(b[k]) for k in ("o","h","l","c","v")))
             for b in bars]
    with storage.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        # Both tables are versioned by symbol+day; never replace pre-existing
        # broker/risk evidence or legacy price observations.
        conn.executemany("""INSERT OR IGNORE INTO bars
            (symbol,day,o,h,l,c,v,source,adjustment,observed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",local)
        conn.executemany("""INSERT OR IGNORE INTO sw_historical_bars
            (symbol,timeframe,feed,adjustment,at,trade_date,phase,observed_at,
             o,h,l,c,v) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",archive)
        conn.commit()


async def warmup(*,limit=5,cooldown_minutes=30,pace_seconds=1.0):
    """Download at most `limit` outstanding tickers per run, resumably."""
    if not 1<=limit<=10 or not 0.5<=pace_seconds<=10:
        raise ValueError("expansion50_warmup_limits_invalid")
    initialize()
    from .alpaca_paper import PaperClient
    now=datetime.now(UTC)
    day=completed_day(now)
    cutoff=now-timedelta(minutes=cooldown_minutes)
    existing={r["symbol"]:r for r in storage.rows(
        "SELECT * FROM sw_expansion50_warmup")}
    candidates=[sym for sym in SYMBOLS if
        not (sym in existing and existing[sym]["status"]=="READY_HISTORY")
        and not (sym in existing and existing[sym]["attempted_at"]
                 and instant(existing[sym]["attempted_at"])>cutoff)]
    output=[]
    with PaperClient(retry_reads=True) as broker:
        broker.account()  # Assert configured PAPER account before any write.
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20,connect=5),trust_env=False,
            follow_redirects=False) as client:
            for symbol in candidates[:limit]:
                checked=datetime.now(UTC)
                try:
                    asset=broker.asset(symbol)  # GET only, no broker order action.
                    if not backfill.asset_evidence(symbol,asset)["verified"]:
                        raise ValueError("paper_stock_asset_not_verified_tradable")
                    first=(__import__("datetime").date.fromisoformat(day)
                           -timedelta(days=550)).isoformat()
                    bars,source,adjustment=await market.alpaca(
                        client,symbol,from_day=first,through=day)
                    if (source,adjustment)!=("alpaca_iex_daily","RAW"):
                        raise ValueError("expansion50_unapproved_data_source")
                    bars=[b for b in bars if b["day"]<=day
                          and published_after(b["day"])<=checked]
                    if not bars:
                        raise ValueError("expansion50_empty_published_daily_data")
                    _store(symbol,bars,checked,day)
                    ready=verify_201(symbol,day)
                    status="READY_HISTORY" if ready else "PARTIAL_HISTORY"
                    _save_status(symbol,status,checked,n=len(bars),
                                 first=bars[0]["day"],last=bars[-1]["day"])
                    output.append({"symbol":symbol,"status":status,"stored":len(bars),
                                   "trade_ready":False})
                except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
                    reason=(str(exc) if isinstance(exc,ValueError)
                            else type(exc).__name__)
                    _save_status(symbol,"RETRY",checked,error=reason[:90])
                    output.append({"symbol":symbol,"status":"RETRY","reason":reason[:90]})
                await asyncio.sleep(pace_seconds)
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-symbols",type=int,default=5)
    parser.add_argument("--pace-seconds",type=float,default=1.0)
    parser.add_argument("--report",action="store_true")
    args=parser.parse_args()
    if args.report:
        print(json.dumps(snapshot(),indent=2))
        return
    results=asyncio.run(warmup(limit=args.max_symbols,
                              pace_seconds=args.pace_seconds))
    status=snapshot()
    print(json.dumps({"attempts":results,"universe":len(REGISTRY),
       "expansion_count":len(SYMBOLS),
       "daily_history_ready":sum(r["status"]=="READY_HISTORY" for r in status),
       "not_yet_ready":sum(r["status"]!="READY_HISTORY" for r in status),
       "note":"History readiness does NOT bypass live price checks, verified asset status or trade risk gates."
       },indent=2))


if __name__=="__main__":
    main()
