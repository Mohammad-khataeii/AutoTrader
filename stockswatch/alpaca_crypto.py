"""AlpacaCrypto: isolated crypto-spot research and historical-bar ingestion.

Uses Alpaca crypto data ONLY; never uses the legacy exchange/crypto engine.
Prices in historical bars are Alpaca quote midpoints, not executable fills.
Spot market supports LONG or FLAT only. No crypto short or leverage paths.
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx

from .storage import connect, rows, one, utc

UTC = timezone.utc
PAIRS = (
    "BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "LINK/USD",
    "LTC/USD", "BCH/USD", "DOGE/USD", "UNI/USD", "AAVE/USD",
)
DATA_ORIGIN = "https://data.alpaca.markets"
LOCATION = "us"
TIMEFRAMES = ("1Day", "1Hour")
PERIOD = {"1Day": timedelta(days=90), "1Hour": timedelta(days=7)}
BACKFILL_START = {"1Day": timedelta(days=735), "1Hour": timedelta(days=35)}
FINAL_STATES = {"COMPLETE", "ERROR"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_assets (
 symbol TEXT PRIMARY KEY, eligible INTEGER NOT NULL DEFAULT 0,
 checked_at TEXT, reason TEXT NOT NULL DEFAULT 'awaiting_asset_verification',
 min_order_size TEXT, min_trade_increment TEXT, price_increment TEXT);
CREATE TABLE IF NOT EXISTS ac_jobs (
 symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
 start_at TEXT NOT NULL, end_at TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'PENDING', token TEXT,
 attempts INTEGER NOT NULL DEFAULT 0, updated_at TEXT, error TEXT,
 PRIMARY KEY(symbol,timeframe,start_at,end_at));
CREATE INDEX IF NOT EXISTS ac_jobs_scheduler ON ac_jobs(state, timeFrame, end_at);
CREATE TABLE IF NOT EXISTS ac_bars (
 symbol TEXT NOT NULL, timeframe TEXT NOT NULL, ts TEXT NOT NULL,
 o REAL NOT NULL, h REAL NOT NULL, l REAL NOT NULL, c REAL NOT NULL, v REAL NOT NULL,
 source TEXT NOT NULL, ingested_at TEXT NOT NULL,
 PRIMARY KEY(symbol,timeframe,ts));
CREATE INDEX IF NOT EXISTS ac_bars_latest ON ac_bars(symbol,timeframe,ts DESC);
CREATE TABLE IF NOT EXISTS ac_signals (
 symbol TEXT NOT NULL, bar_at TEXT NOT NULL, evaluated_at TEXT NOT NULL,
 action TEXT NOT NULL, score REAL NOT NULL, price REAL NOT NULL,
 stop REAL, target REAL, reason TEXT NOT NULL,
 PRIMARY KEY(symbol,bar_at));
CREATE TABLE IF NOT EXISTS ac_state (
 id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL DEFAULT 1,
 high_water TEXT, last_cycle TEXT, last_error TEXT,
 configured_account TEXT);
INSERT OR IGNORE INTO ac_state(id,paused) VALUES(1,1);
CREATE TABLE IF NOT EXISTS ac_intents (
 client_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
 symbol TEXT NOT NULL, side TEXT NOT NULL, created_at TEXT NOT NULL,
 state TEXT NOT NULL, broker_order_id TEXT, broker_status TEXT,
 qty TEXT, notional TEXT, reason TEXT NOT NULL, last_checked TEXT,
 CHECK(side IN ('buy','sell')));
CREATE INDEX IF NOT EXISTS ac_intents_by_symbol ON ac_intents(symbol, created_at DESC);
CREATE TABLE IF NOT EXISTS ac_broker_snapshot (
 id INTEGER PRIMARY KEY CHECK(id=1), observed_at TEXT NOT NULL,
 account_json TEXT NOT NULL, positions_json TEXT NOT NULL,
 open_order_count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ac_managed (
 symbol TEXT PRIMARY KEY, account_id TEXT NOT NULL,
 entry_client_id TEXT NOT NULL, stop TEXT NOT NULL, target TEXT NOT NULL,
 entered_at TEXT NOT NULL);
"""

class CryptoDataError(RuntimeError):
    """Stable code; must never contain credentials or provider response bodies."""


def initialize():
    with connect() as c:
        c.executescript(SCHEMA)
        c.executemany("INSERT OR IGNORE INTO ac_assets(symbol) VALUES(?)", [(p,) for p in PAIRS])


def _stamp(v):
    if not isinstance(v, str):
        raise CryptoDataError("crypto_bar_timestamp_invalid")
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise CryptoDataError("crypto_bar_timestamp_invalid") from None
    if d.tzinfo is None:
        raise CryptoDataError("crypto_bar_timestamp_naive")
    return d.astimezone(UTC)


def _number(v, *, positive=True):
    try:
        d = Decimal(str(v))
    except (InvalidOperation, TypeError):
        raise CryptoDataError("crypto_bar_non_numeric") from None
    if not d.is_finite() or (d <= 0 if positive else d < 0):
        raise CryptoDataError("crypto_bar_non_positive")
    return float(d)


def _headers():
    # Read-only data may use the existing StocksWatch Alpaca data credentials.
    key = os.getenv("ALPACA_CRYPTO_DATA_KEY") or os.getenv("STOCKSWATCH_ALPACA_KEY")
    secret = os.getenv("ALPACA_CRYPTO_DATA_SECRET") or os.getenv("STOCKSWATCH_ALPACA_SECRET")
    if not key or not secret:
        raise CryptoDataError("crypto_data_credentials_unconfigured")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


class CryptoData:
    def __init__(self, transport=None):
        self.http = httpx.Client(
            base_url=DATA_ORIGIN, headers=_headers(),
            timeout=httpx.Timeout(12.0, connect=5.0),
            trust_env=False, follow_redirects=False, transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.http.close()

    def get(self, path, params):
        if path not in ("/v1beta3/crypto/us/bars", "/v1beta3/crypto/us/latest/quotes"):
            raise CryptoDataError("crypto_data_route_denied")
        try:
            r = self.http.get(path, params=params)
        except httpx.TransportError:
            raise CryptoDataError("crypto_data_transport") from None
        if r.status_code in (401,403,422):
            raise CryptoDataError("crypto_data_entitlement_denied")
        if r.status_code==429:
            raise CryptoDataError("crypto_data_rate_limit")
        if not r.is_success:
            raise CryptoDataError("crypto_data_http_error")
        if len(r.content)>5_000_000:
            raise CryptoDataError("crypto_data_payload_excess")
        try:
            body = r.json()
        except ValueError:
            raise CryptoDataError("crypto_data_invalid_json") from None
        if not isinstance(body,dict):
            raise CryptoDataError("crypto_data_invalid_shape")
        return body

    def bars(self, job):
        data = self.get("/v1beta3/crypto/us/bars", {
            "symbols": job["symbol"], "timeframe": job["timeframe"],
            "start": job["start_at"], "end": job["end_at"],
            "limit": 1000, "sort": "asc",
            **({"page_token": job["token"]} if job.get("token") else {}),
        })
        raw = data.get("bars")
        token = data.get("next_page_token")
        if not isinstance(raw,dict) or set(raw)-{job["symbol"]}:
            raise CryptoDataError("crypto_data_unexpected_pair")
        if token is not None and (not isinstance(token,str) or not token or token==job.get("token")):
            raise CryptoDataError("crypto_data_pagination_invalid")
        values = raw.get(job["symbol"], [])
        if not isinstance(values,list):
            raise CryptoDataError("crypto_data_bars_invalid")
        output=[]
        last=None
        for bar in values:
            if not isinstance(bar,dict):
                raise CryptoDataError("crypto_data_row_invalid")
            stamp=_stamp(bar.get("t"))
            # Alpaca may publish the currently forming bar. Never ingest
            # anything at or beyond the last completed UTC bucket.
            if stamp >= _floor(datetime.now(UTC),job["timeframe"]):
                continue
            if not _stamp(job["start_at"]) <= stamp <= _stamp(job["end_at"]) or (last and stamp <= last):
                raise CryptoDataError("crypto_data_outside_window_or_order")
            last=stamp
            o,h,l,c=(_number(bar.get(x)) for x in ("o","h","l","c"))
            v=_number(bar.get("v",0),positive=False)
            if h < max(o,c,l) or l > min(o,c,h):
                raise CryptoDataError("crypto_data_ohlc_invalid")
            # Repeated snapshots are idempotent; never backdate a bar as if known earlier.
            output.append((job["symbol"],job["timeframe"],stamp.isoformat(),o,h,l,c,v,
                           "alpaca_crypto_us_quote_midpoint",utc()))
        if token and not output:
            raise CryptoDataError("crypto_data_empty_page_with_token")
        return output, token

    def latest_bid(self, symbol):
        body = self.get("/v1beta3/crypto/us/latest/quotes", {"symbols":symbol})
        q=body.get("quotes",{}).get(symbol)
        if not isinstance(q,dict):
            raise CryptoDataError("crypto_quote_missing")
        ts=_stamp(q.get("t"))
        if not timedelta(0)<=datetime.now(UTC)-ts<=timedelta(minutes=3):
            raise CryptoDataError("crypto_quote_stale")
        bid=_number(q.get("bp")); ask=_number(q.get("ap"))
        if bid>=ask:
            raise CryptoDataError("crypto_quote_crossed")
        return bid, ask, ts.isoformat()


def _floor(now,tf):
    now=now.astimezone(UTC)
    return now.replace(hour=0,minute=0,second=0,microsecond=0) if tf=="1Day" else now.replace(minute=0,second=0,microsecond=0)


def queue(now):
    """Stable monthly daily / weekly hourly checkpoints, with bounded new tails."""
    now=now.astimezone(UTC)
    jobs=[]
    for tf in TIMEFRAMES:
        end=_floor(now,tf)
        oldest=end-BACKFILL_START[tf]
        if tf=="1Day":
            cursor=oldest.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
        else:
            cursor=_floor(oldest,"1Day")-timedelta(days=oldest.weekday())
        while cursor<end:
            if tf=="1Day":
                following=(cursor.replace(day=28)+timedelta(days=4)).replace(day=1)
            else:
                following=cursor+timedelta(days=7)
            next_at=min(following,end)
            for pair in PAIRS:
                jobs.append((pair,tf,cursor.isoformat(),next_at.isoformat()))
            cursor=next_at
    with connect() as c:
        c.executemany("""INSERT OR IGNORE INTO ac_jobs
            (symbol,timeframe,start_at,end_at,state) VALUES(?,?,?,?,'PENDING')""",jobs)


def refresh_recent_hourly(data,now):
    """Refresh just-completed hourly candles, independent of deep backfill progress."""
    end=_floor(now,"1Hour")
    start=end-timedelta(hours=5)
    batch=[]
    for symbol in PAIRS:
        job={"symbol":symbol,"timeframe":"1Hour","start_at":start.isoformat(),
             "end_at":end.isoformat(),"token":None}
        values,token=data.bars(job)
        if token:
            raise CryptoDataError("crypto_recent_hourly_pagination_unverified")
        batch.extend(values)
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        c.executemany("INSERT OR IGNORE INTO ac_bars VALUES(?,?,?,?,?,?,?,?,?,?)",batch)
        c.commit()
    return len(batch)


def backfill_step(data,now):
    cutoff=(now-timedelta(minutes=5)).isoformat()
    job=one("""SELECT * FROM ac_jobs
      WHERE state IN ('PENDING','RUNNING','RETRY')
        AND (state!='RETRY' OR updated_at<?)
      -- Hourly data is the bottleneck for 220-hour research eligibility.
      -- Previously daily windows were exhausted first, leaving all ten pairs
      -- in WAIT even after many thousands of daily observations arrived.
      -- Finish an in-flight paginated job first, then work newest hourly
      -- windows across symbols, then fill the remaining daily archive.
      ORDER BY CASE WHEN state='RUNNING' THEN 0
                    WHEN timeframe='1Hour' THEN 1 ELSE 2 END,
        end_at DESC, symbol LIMIT 1""",(cutoff,))
    if job is None:
        return False
    try:
        bars,token=data.bars(job)
        with connect() as c:
            c.execute("BEGIN IMMEDIATE")
            current=c.execute("""SELECT state,token FROM ac_jobs
               WHERE symbol=? AND timeframe=? AND start_at=? AND end_at=?""",
               tuple(job[k] for k in ("symbol","timeframe","start_at","end_at"))).fetchone()
            if current is None or current["token"]!=job["token"] or current["state"]!=job["state"]:
                c.rollback()
                return True
            c.executemany("INSERT OR IGNORE INTO ac_bars VALUES(?,?,?,?,?,?,?,?,?,?)",bars)
            c.execute("""UPDATE ac_jobs SET state=?,token=?,attempts=0,error=NULL,updated_at=?
                WHERE symbol=? AND timeframe=? AND start_at=? AND end_at=?""",
                ("RUNNING" if token else "COMPLETE",token,utc(),
                 *(job[k] for k in ("symbol","timeframe","start_at","end_at"))))
            c.commit()
    except CryptoDataError as exc:
        with connect() as c:
            attempts=job["attempts"]+1
            c.execute("""UPDATE ac_jobs SET attempts=?, state=?, error=?, updated_at=?
                WHERE symbol=? AND timeframe=? AND start_at=? AND end_at=?""",
                (attempts,"ERROR" if attempts>=5 else "RETRY",str(exc),utc(),
                 *(job[k] for k in ("symbol","timeframe","start_at","end_at"))))
        # Rate limits, entitlement failures and provider outages must stop
        # the current burst rather than causing repeated immediate requests.
        return False
    return True


def backfill_burst(data,now,max_jobs=6):
    """Bounded paper-research GET burst; never places orders.

    Reconciles the most recent hourly buckets first, processes only a small
    number of pages per iteration, and yields if a provider request fails.
    Returns attempts rather than inventing data coverage.
    """
    max_jobs=max(0,min(int(max_jobs),8))
    done=0
    for index in range(max_jobs):
        if not backfill_step(data,now):
            break
        done+=1
        if index+1<max_jobs:
            time.sleep(0.65)
    return done


def _ema(values,n):
    if len(values)<n:return None
    e=sum(values[:n])/n
    k=2/(n+1)
    for value in values[n:]:e+=(value-e)*k
    return e


def _atr(bars,n=14):
    tr=[]
    for prev,bar in zip(bars,bars[1:]):
        tr.append(max(bar["h"]-bar["l"],abs(bar["h"]-prev["c"]),abs(bar["l"]-prev["c"])))
    return sum(tr[-n:])/n if len(tr)>=n else None


def _rsi(values,n=14):
    if len(values)<n+1:return None
    diffs=[b-a for a,b in zip(values[-(n+1):-1],values[-n:])]
    gain=sum(max(v,0) for v in diffs)/n
    loss=sum(max(-v,0) for v in diffs)/n
    return 100 if loss==0 else 100-100/(1+gain/loss)


def signal(symbol, now=None):
    """Causal 1h trend + 1d regime, no strategy signal on incomplete buckets."""
    now=now or datetime.now(UTC)
    if symbol not in PAIRS:
        raise CryptoDataError("crypto_pair_not_allowed")
    bar_end=_floor(now,"1Hour").isoformat()
    day_end=_floor(now,"1Day").isoformat()
    hourly=rows("""SELECT * FROM ac_bars WHERE symbol=? AND timeframe='1Hour'
       AND ts<? ORDER BY ts DESC LIMIT 260""",(symbol,bar_end))[::-1]
    daily=rows("""SELECT * FROM ac_bars WHERE symbol=? AND timeframe='1Day'
       AND ts<? ORDER BY ts DESC LIMIT 260""",(symbol,day_end))[::-1]
    def observation(action,why,score=0,stop=None,target=None):
        return {"symbol":symbol,"action":action,"reason":why,"score":round(score,3),
          "price":hourly[-1]["c"] if hourly else None,
          "stop":stop,"target":target,
          "bar_at":hourly[-1]["ts"] if hourly else None,"as_of":now.isoformat()}
    if len(hourly)<220 or len(daily)<220:
        return observation("WAIT","insufficient_completed_history")
    last=_stamp(hourly[-1]["ts"])
    if now-last>timedelta(hours=3):
        return observation("WAIT","stale_completed_hourly_bar")
    h=[b["c"] for b in hourly];d=[b["c"] for b in daily]
    e20=_ema(h,20);e50=_ema(h,50);e200=_ema(h,200)
    d200=_ema(d,200)
    atr=_atr(hourly);rsi=_rsi(h)
    if any(x is None or not math.isfinite(x) for x in (e20,e50,e200,d200,atr,rsi)):
        return observation("WAIT","invalid_technical_indicators")
    volatility=atr/h[-1]
    trend=h[-1]>e50>e200 and e20>e50
    macro=d[-1]>d200
    breakout=h[-1]>max(b["h"] for b in hourly[-21:-1])
    healthy=45<=rsi<=72 and 0.001<volatility<0.06
    score=sum((trend,macro,breakout,healthy))/4
    if not (trend and macro and healthy and breakout):
        return observation("HOLD","no_confirmed_spot_long_setup",score)
    stop=h[-1]-2.5*atr
    target=h[-1]+4.5*atr
    if stop<=0:
        return observation("WAIT","invalid_stop_distance")
    return observation("BUY","daily_uptrend_hourly_breakout_healthy_volatility",score,
                       round(stop,8),round(target,8))


def scan(now):
    """Refresh-only research. Writes signal evidence, never broker orders."""
    evaluated=[]
    for symbol in PAIRS:
        s=signal(symbol,now)
        evaluated.append(s)
        if s["bar_at"] and s["price"] is not None:
            with connect() as c:
                c.execute("""INSERT INTO ac_signals
                    (symbol,bar_at,evaluated_at,action,score,price,stop,target,reason)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    -- A WAIT recorded before deep history was populated must
                    -- be revisited after backfill. Update evaluation time and
                    -- evidence in place; do not pretend a historical signal
                    -- existed when the data had not yet been collected.
                    ON CONFLICT(symbol,bar_at) DO UPDATE SET
                      evaluated_at=excluded.evaluated_at,
                      action=excluded.action,
                      score=excluded.score,
                      price=excluded.price,
                      stop=excluded.stop,
                      target=excluded.target,
                      reason=excluded.reason""",
                    (symbol,s["bar_at"],now.isoformat(),s["action"],s["score"],
                     s["price"],s["stop"],s["target"],s["reason"]))
    with connect() as c:
        c.execute("UPDATE ac_state SET last_cycle=?,last_error=NULL WHERE id=1",(now.isoformat(),))
    return evaluated


def dashboard():
    state=one("SELECT * FROM ac_state WHERE id=1") or {}
    jobs=rows("SELECT timeframe,state,COUNT(*) AS n FROM ac_jobs GROUP BY timeframe,state")
    bars=rows("SELECT timeframe,COUNT(*) AS n,COUNT(DISTINCT symbol) AS symbols FROM ac_bars GROUP BY timeframe")
    latest=rows("""SELECT a.symbol,a.eligible,a.checked_at,a.reason,
      (SELECT MAX(ts) FROM ac_bars b WHERE b.symbol=a.symbol AND b.timeframe='1Hour') latest_hour,
      (SELECT MAX(ts) FROM ac_bars b WHERE b.symbol=a.symbol AND b.timeframe='1Day') latest_day
      FROM ac_assets a ORDER BY a.symbol""")
    signals=rows("""SELECT s.* FROM ac_signals s JOIN
      (SELECT symbol,MAX(bar_at) bar_at FROM ac_signals GROUP BY symbol) k
      ON s.symbol=k.symbol AND s.bar_at=k.bar_at ORDER BY s.symbol""")
    intents=rows("""SELECT client_id,symbol,side,created_at,state,broker_status,qty,notional,reason
        FROM ac_intents ORDER BY created_at DESC LIMIT 30""")
    managed=rows("SELECT symbol,stop,target,entered_at FROM ac_managed")
    broker=one("SELECT * FROM ac_broker_snapshot WHERE id=1")
    return {
      "mode":"ALPACA_CRYPTO_SPOT_PAPER","short_supported":False,"margin_supported":False,
      "currency":"USD","location":LOCATION,"bars_are_quote_midpoints":True,
      "paper_orders_enabled":os.getenv("ALPACA_CRYPTO_ALLOW_PAPER_ORDERS","0")=="1",
      "paused":bool(state.get("paused",1)),
      "broker_account_verified":bool(state.get("configured_account")),
      "last_cycle":state.get("last_cycle"),"last_error":state.get("last_error"),
      "assets":latest,"history_jobs":jobs,"history_bars":bars,
      "broker_snapshot": {"observed_at":broker["observed_at"],
        "account":json.loads(broker["account_json"]),
        "positions":json.loads(broker["positions_json"]),
        "open_order_count":broker["open_order_count"]} if broker else None,
      "signals":signals,"intents":intents,"managed":managed,
      "legacy_crypto_source_preserved":True,
      "disclaimer":"Historical bars are midpoint quotes, not executable prices. Crypto and stocks may share the existing Alpaca Paper account, but order journals stay separate. Short selling crypto is unsupported.",
    }
