"""Bounded, resumable Alpaca US equity catalogue and daily RESEARCH history.

This module never sends broker orders, never promotes catalogue symbols into
the 102-symbol trading registry, and uses a SEPARATE SQLite database.
Run via: python -m stockswatch.asset_catalog --sync --download --max-batches 3
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sqlite3
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from . import market, storage
from .sessions import completed_day, published_after
from .universe import REGISTRY

NY = ZoneInfo("America/New_York")
CATALOG_PATH = Path(os.getenv(
    "STOCKSWATCH_CATALOG_DB",
    str(Path(storage.DB_PATH).with_name("stockswatch-catalog.sqlite3")),
))
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.]{0,14}$")
EXCHANGES = frozenset(("NASDAQ", "NYSE", "ARCA", "AMEX", "BATS", "OTC", "NYSEARCA", "TXSE"))
SCHEMA = """
CREATE TABLE IF NOT EXISTS sw_catalog_assets(
  symbol TEXT PRIMARY KEY, name TEXT NOT NULL, exchange TEXT NOT NULL,
  active INTEGER NOT NULL, tradable INTEGER NOT NULL,
  original INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
  observed_at TEXT NOT NULL, attempted_at TEXT, bar_count INTEGER NOT NULL DEFAULT 0,
  latest_day TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS sw_catalog_ready
  ON sw_catalog_assets(active,tradable,original,status,attempted_at,symbol);
CREATE TABLE IF NOT EXISTS sw_catalog_daily(
  symbol TEXT NOT NULL, day TEXT NOT NULL, o REAL NOT NULL, h REAL NOT NULL,
  l REAL NOT NULL, c REAL NOT NULL, v REAL NOT NULL,
  feed TEXT NOT NULL, observed_at TEXT NOT NULL,
  PRIMARY KEY(symbol,day)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sw_catalog_metadata(
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
"""

@contextmanager
def connect(*, readonly=False):
    path = CATALOG_PATH
    if readonly and not path.exists():
        yield None
        return
    if not readonly:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        path.as_uri() + "?mode=ro" if readonly else str(path),
        uri=readonly, timeout=12,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA temp_store=MEMORY")
    try:
        yield conn
        if not readonly:
            conn.commit()
    finally:
        conn.close()

def initialize():
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)

def normalized_assets(payload, observed):
    """Treat inventory as data, not executable approval or quote evidence."""
    if not isinstance(payload, list) or not payload or len(payload) > 100000:
        raise ValueError("catalog_inventory_invalid")
    found = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("catalog_inventory_invalid")
        if item.get("class") != "us_equity" or item.get("status") != "active":
            continue
        sym, exch = item.get("symbol"), item.get("exchange")
        if not isinstance(sym, str) or not SYMBOL.fullmatch(sym):
            continue
        if not isinstance(exch, str) or exch not in EXCHANGES:
            continue
        if sym in found:
            raise ValueError("catalog_duplicate_symbol")
        name = str(item.get("name") or sym)[:160]
        listed = int(item.get("tradable") is True)
        original = int(sym in REGISTRY)
        found[sym] = (
            sym, name, exch, 1, listed, original,
            "ORIGINAL" if original else "PENDING" if listed else "NOT_TRADABLE",
            observed,
        )
    if len(found) < 102:
        # A truncated response must NEVER erase the previously known universe.
        raise ValueError("catalog_inventory_suspiciously_small")
    return list(found.values())

def save_inventory(payload, now=None):
    now = now or datetime.now(UTC)
    observed = now.isoformat()
    data = normalized_assets(payload, observed)
    initialize()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE sw_catalog_assets SET active=0")
        db.executemany("""INSERT INTO sw_catalog_assets(
          symbol,name,exchange,active,tradable,original,status,observed_at)
          VALUES(?,?,?,?,?,?,?,?)
          ON CONFLICT(symbol) DO UPDATE SET name=excluded.name,
          exchange=excluded.exchange,active=1,tradable=excluded.tradable,
          original=excluded.original,observed_at=excluded.observed_at,
          status=CASE WHEN excluded.original=1 THEN 'ORIGINAL'
             WHEN excluded.tradable=0 THEN 'NOT_TRADABLE'
             WHEN sw_catalog_assets.status IN ('ORIGINAL','NOT_TRADABLE')
               THEN 'PENDING'
             ELSE sw_catalog_assets.status END
          """, data)
        db.execute("""INSERT INTO sw_catalog_metadata(key,value)
          VALUES('last_sync',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                   (observed,))
    return report()

def sync():
    from .alpaca_paper import PaperClient
    with PaperClient(retry_reads=True) as client:
        client.account()  # Verify configured USD PAPER account, GET only.
        payload = client.get("/v2/assets", {"status": "active", "asset_class": "us_equity"})
    return save_inventory(payload)

def _pending(now, count):
    cutoff_retry = (now-timedelta(hours=6)).isoformat()
    cutoff_partial = (now-timedelta(hours=24)).isoformat()
    cutoff_empty = (now-timedelta(days=3)).isoformat()
    with connect(readonly=True) as db:
        return [r["symbol"] for r in db.execute("""
            SELECT symbol FROM sw_catalog_assets WHERE active=1 AND tradable=1
            AND original=0 AND (
                 status='PENDING'
                 OR (status='RETRY' AND attempted_at<=?)
                 OR (status='PARTIAL' AND attempted_at<=?)
                 OR (status='NO_HISTORY' AND attempted_at<=?))
            ORDER BY CASE status WHEN 'PENDING' THEN 0 ELSE 1 END, symbol
            LIMIT ?""", (cutoff_retry,cutoff_partial,cutoff_empty,count))]

def _parse_bar(raw, through, observed):
    if not isinstance(raw, dict):
        raise ValueError("catalog_bar_invalid")
    try:
        stamp = datetime.fromisoformat(str(raw["t"]).replace("Z","+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("catalog_bar_naive")
        day = stamp.astimezone(NY).date().isoformat()
        if day > through or published_after(day) > observed:
            return None
        prices = [float(raw[k]) for k in ("o","h","l","c","v")]
        o,h,l,c,v = prices
        if (not all(math.isfinite(x) for x in prices) or min(o,h,l,c)<=0 or v<=0
                or l > min(o,c) or h < max(o,c)):
            raise ValueError("catalog_bar_ohlcv_invalid")
        return day, o,h,l,c,v
    except (TypeError, KeyError, OverflowError) as exc:
        raise ValueError("catalog_bar_invalid") from exc

def fetch_daily(client, symbols, now):
    """Complete all provider pages BEFORE committing any part of a batch."""
    if not (1 <= len(symbols) <= 10) or len(set(symbols)) != len(symbols):
        raise ValueError("catalog_batch_invalid")
    through = completed_day(now)
    start = (now.date()-timedelta(days=550)).isoformat()
    end = (now.date()+timedelta(days=1)).isoformat()
    output = {sym: {} for sym in symbols}
    token = None
    seen = set()
    for page in range(32):
        args = {
            "symbols": ",".join(symbols), "timeframe": "1Day",
            "start": start, "end": end, "adjustment": "raw",
            "feed": "iex", "limit": 10000,
        }
        if token:
            args["page_token"] = token
        response = client.get(
            "https://data.alpaca.markets/v2/stocks/bars",
            params=args, headers=market.alpaca_headers(),
        )
        market.alpaca_status(response)
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("bars"), dict):
            raise ValueError("catalog_provider_page_invalid")
        if set(body["bars"]) - set(symbols):
            raise ValueError("catalog_provider_symbol_mismatch")
        for sym, bars in body["bars"].items():
            if not isinstance(bars, list):
                raise ValueError("catalog_provider_page_invalid")
            for bar in bars:
                parsed = _parse_bar(bar, through, now)
                if parsed:
                    day = parsed[0]
                    if day in output[sym] and output[sym][day] != parsed:
                        raise ValueError("catalog_provider_duplicate_conflict")
                    output[sym][day] = parsed
        next_token = body.get("next_page_token")
        if not next_token:
            return output
        if not isinstance(next_token, str) or next_token in seen:
            raise ValueError("catalog_provider_pagination_invalid")
        seen.add(next_token)
        token = next_token
    raise ValueError("catalog_provider_pagination_incomplete")

def _write_daily(output, now):
    stamp = now.isoformat()
    latest_limit = (now.date()-timedelta(days=8)).isoformat()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for sym, bars in output.items():
            values = [ (sym,*item,"iex_raw_daily_research",stamp)
                       for item in sorted(bars.values()) ]
            db.executemany("""INSERT OR IGNORE INTO sw_catalog_daily
                (symbol,day,o,h,l,c,v,feed,observed_at)
                VALUES(?,?,?,?,?,?,?,?,?)""", values)
            row = db.execute("""SELECT COUNT(*) n,MAX(day) latest FROM sw_catalog_daily
                WHERE symbol=?""", (sym,)).fetchone()
            count, latest = int(row["n"]), row["latest"]
            status = ("READY_HISTORY" if count>=201 and latest and latest>=latest_limit
                      else "PARTIAL" if count else "NO_HISTORY")
            db.execute("""UPDATE sw_catalog_assets
              SET status=?,attempted_at=?,bar_count=?,latest_day=?,error=NULL
              WHERE symbol=? AND active=1 AND original=0""",
              (status,stamp,count,latest,sym))
    return {sym: len(bars) for sym,bars in output.items()}

def _mark_retry(symbols, now, reason):
    with connect() as db:
        db.executemany("""UPDATE sw_catalog_assets
          SET status='RETRY',attempted_at=?,error=? WHERE symbol=?""",
          [(now.isoformat(),reason,sym) for sym in symbols])

def download(*, max_batches=3, batch_size=10, pace_seconds=2.0,
             max_db_mb=1024, min_free_mb=3072):
    if not 1<=max_batches<=24 or not 1<=batch_size<=10 or not 1<=pace_seconds<=30:
        raise ValueError("catalog_download_limits_invalid")
    initialize()
    # Ensure that account identity is validated, even for GET-only data downloads.
    from .alpaca_paper import PaperClient
    with PaperClient(retry_reads=True) as broker:
        broker.account()
    outcomes = []
    with httpx.Client(timeout=httpx.Timeout(35, connect=8),
                      trust_env=False,follow_redirects=False) as client:
        for _ in range(max_batches):
            if CATALOG_PATH.stat().st_size > max_db_mb*1024**2:
                return {"state":"DB_CAP_REACHED","attempts":outcomes,"summary":report()}
            if shutil.disk_usage(CATALOG_PATH.parent).free < min_free_mb*1024**2:
                return {"state":"LOW_DISK_FREE","attempts":outcomes,"summary":report()}
            now = datetime.now(UTC)
            symbols = _pending(now,batch_size)
            if not symbols:
                break
            try:
                values = fetch_daily(client,symbols,now)
                stored = _write_daily(values,now)
                outcomes.append({"symbols":symbols,"bars":stored,"state":"STORED"})
            except (httpx.HTTPError,ValueError,RuntimeError) as exc:
                # Do not expose provider payloads, full URLs, or credentials.
                code = str(exc) if isinstance(exc,ValueError) and str(exc).startswith("catalog_") else type(exc).__name__
                _mark_retry(symbols,now,code[:70])
                outcomes.append({"symbols":symbols,"state":"RETRY","reason":code})
                if isinstance(exc,(httpx.HTTPError,RuntimeError)):
                    break
            time.sleep(pace_seconds)
    return {"state":"OK","attempts":outcomes,"summary":report()}

def report():
    with connect(readonly=True) as db:
        if db is None:
            return {"state":"NOT_INITIALIZED","assets":0,"tradable":0,"history_ready":0}
        assets = db.execute("""SELECT COUNT(*) n,
            COALESCE(SUM(active),0) active,
            COALESCE(SUM(active*tradable),0) tradable,
            COALESCE(SUM(active*original),0) original,
            COALESCE(SUM(CASE WHEN active=1 AND original=0 AND status='READY_HISTORY'
                THEN 1 ELSE 0 END),0) history_ready
            FROM sw_catalog_assets""").fetchone()
        states = {r["status"]:r["n"] for r in db.execute("""
             SELECT status,COUNT(*) n FROM sw_catalog_assets
             WHERE active=1 GROUP BY status""")}
        bars = db.execute("SELECT COUNT(*) n FROM sw_catalog_daily").fetchone()["n"]
        last = db.execute("SELECT value FROM sw_catalog_metadata WHERE key='last_sync'").fetchone()
        return {"state":"OK","assets":assets["n"],"active":assets["active"],
                "tradable":assets["tradable"],"original":assets["original"],
                "history_ready":assets["history_ready"],"history_rows":bars,
                "states":states,"last_sync":last["value"] if last else None,
                "db_mb":round(CATALOG_PATH.stat().st_size / 1024**2,1)}

def browse(query="", limit=50, offset=0):
    if type(query) is not str or len(query)>40 or type(limit) is not int or not 1<=limit<=100 \
       or type(offset) is not int or not 0<=offset<=100000:
        raise ValueError("catalog_query_invalid")
    if not CATALOG_PATH.exists():
        return {"summary":report(),"results":[],"total":0}
    term = query.strip().upper()
    with connect(readonly=True) as db:
        where = "WHERE active=1 AND (symbol LIKE ? OR upper(name) LIKE ?)"
        pat = "%" + term.replace("%",r"\%").replace("_",r"\_") + "%"
        where = where.replace("LIKE ?", "LIKE ? ESCAPE '\\'")
        n = db.execute("SELECT COUNT(*) FROM sw_catalog_assets "+where,(pat,pat)).fetchone()[0]
        results = [dict(r) for r in db.execute(
            "SELECT symbol,name,exchange,tradable,original,status,bar_count,latest_day "
            "FROM sw_catalog_assets "+where+" ORDER BY symbol LIMIT ? OFFSET ?",
            (pat,pat,limit,offset))]
    return {"summary":report(),"results":results,"total":n,"offset":offset,"limit":limit,
            "note":"Research catalogue only. Existing 102-symbol paper trading registry unchanged."}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sync",action="store_true")
    parser.add_argument("--download",action="store_true")
    parser.add_argument("--report",action="store_true")
    parser.add_argument("--search",default=None)
    parser.add_argument("--max-batches",type=int,default=3)
    parser.add_argument("--batch-size",type=int,default=10)
    parser.add_argument("--pace-seconds",type=float,default=2.)
    parser.add_argument("--max-db-mb",type=int,default=1024)
    parser.add_argument("--min-free-mb",type=int,default=3072)
    args = parser.parse_args()
    output = {}
    if args.sync:
        output["sync"] = sync()
    if args.download:
        output["download"] = download(max_batches=args.max_batches,
             batch_size=args.batch_size,pace_seconds=args.pace_seconds,
             max_db_mb=args.max_db_mb,min_free_mb=args.min_free_mb)
    if args.report or not output:
        output["report"] = report()
    if args.search is not None:
        output["browse"] = browse(args.search)
    print(json.dumps(output,indent=2))

if __name__ == "__main__":
    main()
