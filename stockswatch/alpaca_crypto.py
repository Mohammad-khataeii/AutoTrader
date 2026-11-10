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
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx

from .storage import connect, rows, one, utc

UTC = timezone.utc
# Preserve the original ten markets and their existing persisted history.
BASE_PAIRS = (
    "BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "LINK/USD",
    "LTC/USD", "BCH/USD", "DOGE/USD", "UNI/USD", "AAVE/USD",
)
# Additional Alpaca-supported USD markets. Availability is *also* verified
# against the connected paper account before a pair may receive any order.
EXPANSION_PAIRS = (
    "XRP/USD", "ADA/USD", "DOT/USD", "SHIB/USD", "ARB/USD",
    "RENDER/USD", "ONDO/USD", "FIL/USD", "GRT/USD", "PEPE/USD",
)
# 50 active broker-listed crypto markets (Alpaca asset catalog verified
# 2026-11-09). Non-USD-quoted markets are research-only until the engine
# supports quote-currency-aware sizing, conversion, and settlement.
EXPANSION50_PAIRS = (
    "AAVE/USDC", "AAVE/USDT", "AVAX/USDC", "AVAX/USDT", "BAT/USD",
    "BAT/USDC", "BCH/BTC", "BCH/USDC", "BCH/USDT", "BONK/USD",
    "BTC/USDC", "BTC/USDT", "CRV/USD", "CRV/USDC", "DOGE/USDC",
    "DOGE/USDT", "DOT/USDC", "ETH/BTC", "ETH/USDC", "ETH/USDT",
    "GRT/USDC", "HYPE/USD", "LDO/USD", "LINK/BTC", "LINK/USDC",
    "LINK/USDT", "LTC/BTC", "LTC/USDC", "LTC/USDT", "PAXG/USD",
    "POL/USD", "SHIB/USDC", "SHIB/USDT", "SKY/USD", "SOL/USDC",
    "SOL/USDT", "SUSHI/USD", "SUSHI/USDC", "SUSHI/USDT", "TRUMP/USD",
    "UNI/BTC", "UNI/USDC", "UNI/USDT", "USDT/USDC", "WIF/USD",
    "XTZ/USD", "XTZ/USDC", "YFI/USD", "YFI/USDC", "YFI/USDT",
)
PAIRS = BASE_PAIRS + EXPANSION_PAIRS + EXPANSION50_PAIRS
EXECUTION_PAIRS = tuple(p for p in PAIRS if p.endswith("/USD"))
RESEARCH_ONLY_PAIRS = tuple(p for p in PAIRS if p not in EXECUTION_PAIRS)
assert len(PAIRS) == 70 and len(set(PAIRS)) == 70
assert len(EXPANSION50_PAIRS) == 50
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
CREATE TABLE IF NOT EXISTS ac_signal_gates (
 symbol TEXT NOT NULL, bar_at TEXT NOT NULL, evaluated_at TEXT NOT NULL,
 gates_json TEXT NOT NULL, PRIMARY KEY(symbol,bar_at));
CREATE TABLE IF NOT EXISTS ac_execution_cycles (
 id INTEGER PRIMARY KEY AUTOINCREMENT, evaluated_at TEXT NOT NULL,
 outcome TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ac_execution_cycles_time ON ac_execution_cycles(evaluated_at);
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
-- First-seen decision for each completed pair/hour and distinct reason.
-- Existing ac_signals remains a mutable UI snapshot; this is append-only.
CREATE TABLE IF NOT EXISTS ac_signal_audit (
 symbol TEXT NOT NULL, bar_at TEXT NOT NULL, first_evaluated_at TEXT NOT NULL,
 action TEXT NOT NULL, reason TEXT NOT NULL, score REAL NOT NULL,
 price REAL NOT NULL, stop REAL, target REAL, gates_json TEXT NOT NULL,
 PRIMARY KEY(symbol,bar_at,action,reason));
CREATE INDEX IF NOT EXISTS ac_signal_audit_at ON ac_signal_audit(first_evaluated_at);
-- Only crypto BUY candidates are stored. No credentials or broker account IDs.
CREATE TABLE IF NOT EXISTS ac_admission_audit (
 symbol TEXT NOT NULL, bar_at TEXT NOT NULL, first_checked_at TEXT NOT NULL,
 outcome TEXT NOT NULL, details_json TEXT NOT NULL,
 PRIMARY KEY(symbol,bar_at,outcome));
CREATE INDEX IF NOT EXISTS ac_admission_audit_at ON ac_admission_audit(first_checked_at);
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


# The scanner's close is a completed hourly bar. Only the independent
# latest-quote endpoint can provide a recent bid/ask snapshot for the UI.
QUOTE_TTL_SECONDS = 15
_quote_lock = threading.Lock()
_quote_cached_at = 0.0
_quote_cached_result = None


def _checked_quote(raw, now):
    if not isinstance(raw, dict):
        raise CryptoDataError("crypto_quote_missing")
    at = _stamp(raw.get("t"))
    # Alpaca timestamps may be slightly ahead of the Python clock captured
    # before the GET. Allow <=5s positive provider skew, never stale quotes.
    if not timedelta(seconds=-5) <= now - at <= timedelta(minutes=3):
        raise CryptoDataError("crypto_quote_stale")
    bid = _number(raw.get("bp"))
    ask = _number(raw.get("ap"))
    if bid >= ask:
        raise CryptoDataError("crypto_quote_crossed")
    return {"bid": bid, "ask": ask, "midpoint": (bid + ask) / 2,
            "observed_at": at.isoformat()}


def latest_quotes_snapshot(*, factory=None):
    """GET-only, bounded quote snapshot. No synthetic mark or trading action.

    One Alpaca US latest-quotes request obtains the configured USD pairs. Only validated
    prices younger than three minutes are shown as available. A short cache
    prevents UI polling from exhausting market-data quotas.
    """
    global _quote_cached_at, _quote_cached_result
    with _quote_lock:
        checked_at = time.monotonic()
        if _quote_cached_result is not None and checked_at - _quote_cached_at < QUOTE_TTL_SECONDS:
            return dict(_quote_cached_result)
        now = datetime.now(UTC)
        result = {"available": False, "as_of": now.isoformat(), "quotes": {},
                  "source": "Alpaca US crypto latest bid/ask"}
        try:
            quotes = {}
            # The 70-symbol universe is fetched in bounded batches to avoid
            # oversize query strings, oversized provider responses and bursty UI GETs.
            with (factory or CryptoData)() as data:
                for start in range(0,len(PAIRS),20):
                    symbols = PAIRS[start:start+20]
                    body = data.get("/v1beta3/crypto/us/latest/quotes",
                                    {"symbols": ",".join(symbols)})
                    received = body.get("quotes")
                    if not isinstance(received,dict) or set(received)-set(symbols):
                        raise CryptoDataError("crypto_quote_batch_invalid")
                    quotes.update(received)
            result["available"] = True
            for symbol in PAIRS:
                try:
                    result["quotes"][symbol] = {
                        "available": True, "quote_currency": symbol.split("/")[1],
                        "paper_execution_pair": symbol in EXECUTION_PAIRS,
                        **_checked_quote(quotes.get(symbol), now)}
                except CryptoDataError as exc:
                    result["quotes"][symbol] = {
                        "available": False, "quote_currency": symbol.split("/")[1],
                        "paper_execution_pair": symbol in EXECUTION_PAIRS,
                        "reason": str(exc)}
        except CryptoDataError as exc:
            result["reason"] = str(exc)
        _quote_cached_result = result
        _quote_cached_at = time.monotonic()
        return dict(result)


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
        # Protective exits continue to use independently refreshed bid/ask.
        if symbol not in EXECUTION_PAIRS:
            raise CryptoDataError("crypto_execution_pair_not_usd_or_unlisted")
        body = self.get("/v1beta3/crypto/us/latest/quotes", {"symbols":symbol})
        quote = _checked_quote(body.get("quotes", {}).get(symbol), datetime.now(UTC))
        return quote["bid"], quote["ask"], quote["observed_at"]

    def latest_entry_quote(self, symbol):
        """Independent, uncached bid/ask with *positive* visible top-of-book sizes.

        Bid/ask sizes are mandatory for NEW paper BUYs only, never for existing
        position stop/target exits. Unknown depth blocks new entries.
        """
        if symbol not in EXECUTION_PAIRS:
            raise CryptoDataError("crypto_execution_pair_not_usd_or_unlisted")
        body = self.get("/v1beta3/crypto/us/latest/quotes", {"symbols": symbol})
        received = body.get("quotes")
        if not isinstance(received, dict):
            raise CryptoDataError("crypto_quote_missing")
        raw = received.get(symbol)
        quote = _checked_quote(raw, datetime.now(UTC))
        try:
            quote["bid_size"] = _number(raw.get("bs"))
            quote["ask_size"] = _number(raw.get("as"))
        except (AttributeError, CryptoDataError):
            raise CryptoDataError("crypto_entry_depth_missing_or_invalid") from None
        return quote


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


def refresh_recent_hourly(data,now,*,symbols=None):
    """Refresh completed hourly bars for all or selected verified USD pairs."""
    symbols=tuple(EXECUTION_PAIRS if symbols is None else symbols)
    if not symbols or len(set(symbols))!=len(symbols) or any(sym not in PAIRS for sym in symbols):
        raise CryptoDataError("crypto_recent_hourly_symbols_invalid")
    end=_floor(now,"1Hour")
    start=end-timedelta(hours=5)
    batch=[]
    for symbol in symbols:
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


# At each UTC hour boundary the old 10-minute refresh can lag a full hour.
# The paper engine can catch up only the missing symbols, rate-limited to
# one attempt per 90 seconds; no direct order follows missing history.
_recent_lock=threading.Lock()
_recent_last_key=None
_recent_last_attempt=0.0

def ensure_latest_completed_hourly(data,now):
    """GET-only freshness catch-up; returns a stable status for the journal."""
    global _recent_last_key,_recent_last_attempt
    expected=(_floor(now,"1Hour")-timedelta(hours=1)).isoformat()
    # Historical bars are immutable once complete; never fake a missing bar.
    observed={r["symbol"]:r["stamp"] for r in rows(
        "SELECT symbol,MAX(ts) stamp FROM ac_bars WHERE timeframe='1Hour' GROUP BY symbol")}
    missing=tuple(sym for sym in EXECUTION_PAIRS if observed.get(sym)!=expected)
    if not missing:
        return "crypto_hourly_current"
    if now-_floor(now,"1Hour")<timedelta(seconds=30):
        return "crypto_waiting_for_completed_hour_finalization"
    with _recent_lock:
        tick=time.monotonic()
        if _recent_last_key==expected and tick-_recent_last_attempt<90:
            return "crypto_latest_hourly_retry_cooldown"
        _recent_last_key=expected
        _recent_last_attempt=tick
        # Exactly the missing markets are fetched, not the whole archive.
        refresh_recent_hourly(data,now,symbols=missing)
    observed_after={r["symbol"]:r["stamp"] for r in rows(
        "SELECT symbol,MAX(ts) stamp FROM ac_bars WHERE timeframe='1Hour' GROUP BY symbol")}
    return ("crypto_hourly_caught_up" if all(observed_after.get(sym)==expected for sym in EXECUTION_PAIRS)
            else "crypto_latest_completed_hourly_not_published")


def backfill_step(data,now):
    cutoff=(now-timedelta(minutes=5)).isoformat()
    job=one("""SELECT * FROM ac_jobs
      WHERE state IN ('PENDING','RUNNING','RETRY')
        AND (state!='RETRY' OR updated_at<?)
      -- Hourly data is the bottleneck for 220-hour research eligibility.
      -- Previously daily windows were exhausted first, leaving all configured pairs
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


def warmup_expansion(data, now=None, *, symbols=EXPANSION_PAIRS, on_progress=None):
    """Download 300 completed daily + 300 completed hourly candles for new pairs.

    This is a deliberately explicit, one-off readiness accelerator, not a
    trading action. It writes only validated Alpaca historical OHLCV rows using
    INSERT OR IGNORE. The existing durable ac_jobs archive is NOT cleared or
    marked complete: the normal worker completes the full 735d/35d range.

    A per-pair/timeframe read checks existing coverage, so a rerun is
    idempotent. The caller must handle CryptoDataError/transport failures; no
    synthetic candles or guessed prices are ever created.
    """
    now=now or datetime.now(UTC)
    if any(pair not in (*EXPANSION_PAIRS, *EXPANSION50_PAIRS) for pair in symbols):
        raise CryptoDataError("crypto_warmup_requires_expansion_pair")
    output=[]
    for symbol in symbols:
        for tf, delta in (("1Hour",timedelta(hours=300)),
                          ("1Day",timedelta(days=300))):
            end=_floor(now,tf)
            start=end-delta
            initial_count=one(
                "SELECT COUNT(*) AS n FROM ac_bars WHERE symbol=? AND timeframe=? AND ts>=? AND ts<?",
                (symbol,tf,start.isoformat(),end.isoformat())
            )["n"]
            if initial_count>=260:
                record={"symbol":symbol,"timeframe":tf,"status":"already_ready",
                        "count":initial_count,"new_rows":0}
            else:
                job={"symbol":symbol,"timeframe":tf,
                     "start_at":start.isoformat(),
                     "end_at":end.isoformat(),"token":None}
                new_rows=0
                pages=0
                try:
                    while pages<4:
                        raw,token=data.bars(job)
                        pages+=1
                        with connect() as conn:
                            conn.execute("BEGIN IMMEDIATE")
                            before_changes=conn.total_changes
                            conn.executemany(
                                "INSERT OR IGNORE INTO ac_bars VALUES(?,?,?,?,?,?,?,?,?,?)",
                                raw
                            )
                            new_rows+=conn.total_changes-before_changes
                            conn.commit()
                        if not token:
                            break
                        job["token"]=token
                    # Never claim sufficient history on a truncated feed.
                    fresh_count=one(
                        "SELECT COUNT(*) AS n FROM ac_bars WHERE symbol=? AND timeframe=? AND ts>=? AND ts<?",
                        (symbol,tf,start.isoformat(),end.isoformat())
                    )["n"]
                    record={"symbol":symbol,"timeframe":tf,
                            "status":"ready" if fresh_count>=220 else "insufficient_history",
                            "count":fresh_count,"new_rows":new_rows,
                            "pagination_complete":token is None}
                except CryptoDataError as exc:
                    record={"symbol":symbol,"timeframe":tf,"status":"data_error",
                            "reason":str(exc),"count":initial_count,"new_rows":new_rows}
            output.append(record)
            if on_progress is not None:
                on_progress(record)
            time.sleep(0.6)
    return output


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


def continuation_enabled():
    """Persisted crypto-only control; no changes to stock order permissions."""
    from pathlib import Path
    from .storage import DB_PATH
    try:
        switch = Path(DB_PATH).parent / "alpaca-crypto-continuation-enabled"
        return switch.read_text(encoding="utf-8").strip() == "alpaca-crypto-continuation-v1"
    except (OSError, UnicodeError):
        return False


def evaluate_completed_bars(symbol, hourly, daily, now, *, allow_continuation=False):
    """Pure candle evaluation shared by live signals and offline replay."""
    if symbol not in PAIRS:
        raise CryptoDataError("crypto_pair_not_allowed")
    bar_end=_floor(now,"1Hour").isoformat()
    day_end=_floor(now,"1Day").isoformat()
    # Never include a candle that is still forming at evaluation time.
    if (any(row["ts"]>=bar_end for row in hourly) or
            any(row["ts"]>=day_end for row in daily)):
        raise CryptoDataError("crypto_incomplete_candle_refused")
    def observation(action,why,score=0,stop=None,target=None,gates=None):
        result={"symbol":symbol,"action":action,"reason":why,"score":round(score,3),
          "price":hourly[-1]["c"] if hourly else None,
          "stop":stop,"target":target,
          "bar_at":hourly[-1]["ts"] if hourly else None,"as_of":now.isoformat()}
        if gates is not None:
            result["gates"]=gates
        return result
    if len(hourly)<220 or len(daily)<220:
        return observation("WAIT","insufficient_completed_history")
    last=_stamp(hourly[-1]["ts"])
    # Require the most recently completed UTC hour; the old three-hour
    # tolerance could evaluate outdated candles as fresh BUY evidence.
    expected=_floor(now,"1Hour")-timedelta(hours=1)
    if last != expected:
        return observation("WAIT","latest_completed_hourly_bar_missing")
    # Alpaca may emit midpoint-only candles with no trades. A zero-volume
    # >12% excursion is not executable price confirmation (TRUMP-like spike).
    # Keep raw evidence intact. Block a fake close while it could distort
    # the 200h EMA; block a fake wick while it distorts 20h breakout/14h ATR.
    from .crypto_trade_safety import untraded_quote_outlier
    bad = untraded_quote_outlier(hourly)
    if bad:
        return observation("WAIT", "crypto_" + bad["reason"], gates={
            "market_data_quality": "BLOCKED", "outlier_bar_at": bad["bar_at"],
        })
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
    gates={
      "hourly_uptrend":bool(trend),"daily_above_ema200":bool(macro),
      "20_hour_breakout":bool(breakout),"rsi_volatility_healthy":bool(healthy),
      "rsi14":round(rsi,3),"atr_pct":round(volatility*100,4),
      "breakout_reference_high":max(b["h"] for b in hourly[-21:-1]),
      "completed_hour_volume":hourly[-1]["v"],
      "hourly_close":h[-1],"daily_close":d[-1],
      "daily_ema200":round(d200,9),
    }
    # This is a separate research-tested path, not a weakening of breakout.
    # The continuation control is checked per evaluation; it can be disabled
    # without changing the shared StocksWatch container or any broker orders.
    from .crypto_continuation import evaluate_pullback
    continuation = evaluate_pullback(hourly, e20, atr, rsi)
    gates["continuation_enabled"] = bool(allow_continuation)
    gates["continuation_candidate"] = bool(continuation["passed"])
    gates.update({"continuation_" + key: value
                  for key, value in continuation["checks"].items()})
    # Cross-quoted BTC/USDT, ETH/BTC, etc. are strictly research-only.
    if symbol in RESEARCH_ONLY_PAIRS:
        return observation("HOLD","non_usd_quote_research_only",score,gates=gates)
    if not (trend and macro and healthy):
        return observation("HOLD","no_confirmed_spot_long_setup",score,gates=gates)
    breakout_entry = bool(breakout)
    continuation_entry = bool(allow_continuation and continuation["passed"])
    if not (breakout_entry or continuation_entry):
        return observation("HOLD","no_confirmed_spot_long_setup",score,gates=gates)
    if hourly[-1]["v"]<=0:
        return observation("HOLD","quote_only_breakout_no_trade_volume",score,gates=gates)
    stop=h[-1]-2.5*atr
    target=h[-1]+4.5*atr
    if stop<=0:
        return observation("WAIT","invalid_stop_distance")
    reason = ("daily_uptrend_hourly_breakout_healthy_volatility" if breakout_entry
              else "daily_uptrend_hourly_pullback_reclaim")
    gates["entry_strategy"] = "breakout" if breakout_entry else "continuation"
    return observation("BUY",reason,score,round(stop,8),round(target,8),gates=gates)


def signal(symbol, now=None):
    """Causal strategy signal using only stored completed bars."""
    now=now or datetime.now(UTC)
    if symbol not in PAIRS:
        raise CryptoDataError("crypto_pair_not_allowed")
    bar_end=_floor(now,"1Hour").isoformat()
    day_end=_floor(now,"1Day").isoformat()
    hourly=rows("""SELECT * FROM ac_bars WHERE symbol=? AND timeframe='1Hour'
       AND ts<? ORDER BY ts DESC LIMIT 260""",(symbol,bar_end))[::-1]
    daily=rows("""SELECT * FROM ac_bars WHERE symbol=? AND timeframe='1Day'
       AND ts<? ORDER BY ts DESC LIMIT 260""",(symbol,day_end))[::-1]
    return evaluate_completed_bars(symbol, hourly, daily, now,
                                   allow_continuation=continuation_enabled())

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
                c.execute("""INSERT INTO ac_signal_gates(symbol,bar_at,evaluated_at,gates_json)
                    VALUES(?,?,?,?)
                    ON CONFLICT(symbol,bar_at) DO UPDATE SET
                     evaluated_at=excluded.evaluated_at,gates_json=excluded.gates_json""",
                    (symbol,s["bar_at"],now.isoformat(),json.dumps(s.get("gates") or {},sort_keys=True)))
                if symbol in EXECUTION_PAIRS:
                    c.execute("""INSERT OR IGNORE INTO ac_signal_audit
                        (symbol,bar_at,first_evaluated_at,action,reason,score,price,stop,target,gates_json)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (symbol,s["bar_at"],now.isoformat(),s["action"],s["reason"],
                         s["score"],s["price"],s["stop"],s["target"],
                         json.dumps(s.get("gates") or {},sort_keys=True)))
    with connect() as c:
        c.execute("UPDATE ac_state SET last_cycle=?,last_error=NULL WHERE id=1",(now.isoformat(),))
    return evaluated


def record_admission(symbol,bar_at,outcome,details=None,now=None):
    """Append first occurrence of each candidate rejection/approval per hour."""
    now=now or datetime.now(UTC)
    if (symbol not in EXECUTION_PAIRS or not bar_at or not isinstance(outcome,str)
            or not outcome or len(outcome)>100):
        raise CryptoDataError("crypto_admission_audit_invalid")
    with connect() as c:
        c.execute("""INSERT OR IGNORE INTO ac_admission_audit
          (symbol,bar_at,first_checked_at,outcome,details_json)
          VALUES(?,?,?,?,?)""",
          (symbol,bar_at,now.isoformat(),outcome,
           json.dumps(details or {},sort_keys=True,separators=(",",":"))))


def record_execution_outcome(outcome, now=None):
    """Durable, bounded order-admission outcome, only for AlpacaCrypto."""
    now=now or datetime.now(UTC)
    if not isinstance(outcome,str) or not outcome or len(outcome)>150:
        raise CryptoDataError("crypto_execution_outcome_invalid")
    with connect() as c:
        c.execute("INSERT INTO ac_execution_cycles(evaluated_at,outcome) VALUES(?,?)",
                  (now.isoformat(),outcome))
        c.execute("DELETE FROM ac_execution_cycles WHERE evaluated_at<?",
                  ((now-timedelta(days=7)).isoformat(),))


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
    gates=rows("""SELECT s.symbol,g.gates_json,g.evaluated_at FROM ac_signal_gates g
      JOIN (SELECT symbol,MAX(bar_at) bar_at FROM ac_signal_gates GROUP BY symbol) s
        ON g.symbol=s.symbol AND g.bar_at=s.bar_at ORDER BY s.symbol""")
    outcomes=rows("SELECT evaluated_at,outcome FROM ac_execution_cycles ORDER BY id DESC LIMIT 30")
    signal_audit=rows("""SELECT symbol,bar_at,first_evaluated_at,action,reason,score,price,stop,target,gates_json
         FROM ac_signal_audit ORDER BY first_evaluated_at DESC LIMIT 80""")
    admission_audit=rows("""SELECT symbol,bar_at,first_checked_at,outcome,details_json
         FROM ac_admission_audit ORDER BY first_checked_at DESC LIMIT 80""")
    broker=one("SELECT * FROM ac_broker_snapshot WHERE id=1")
    usd_signals=[x for x in signals if x["symbol"] in EXECUTION_PAIRS]
    nonusd_signals=[x for x in signals if x["symbol"] in RESEARCH_ONLY_PAIRS]
    gate_map={x["symbol"]:json.loads(x["gates_json"]) for x in gates}
    gate_keys=("hourly_uptrend","daily_above_ema200",
               "20_hour_breakout","rsi_volatility_healthy",
               "continuation_candidate")
    usd_gate_passes={name:sum(bool(gate_map.get(x["symbol"],{}).get(name))
                               for x in usd_signals) for name in gate_keys}
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
      "universe_pairs":len(PAIRS),
      "execution_pairs":len(EXECUTION_PAIRS),
      "research_only_pairs":len(RESEARCH_ONLY_PAIRS),
      "continuation_enabled":continuation_enabled(),
      "usd_signal_actions":{name:sum(x["action"]==name for x in usd_signals)
                             for name in ("BUY","HOLD","WAIT")},
      "research_only_wait_count":sum(x["action"]=="WAIT" for x in nonusd_signals),
      "usd_gate_passes":usd_gate_passes,
      "quote_currencies":sorted({p.split("/")[1] for p in PAIRS}),
      "signal_gate_evidence":[{"symbol":r["symbol"],"evaluated_at":r["evaluated_at"],
        "gates":json.loads(r["gates_json"])} for r in gates],
      "crypto_execution_outcomes":outcomes,
      "immutable_signal_audit":signal_audit,
      "immutable_admission_audit":admission_audit,
      "legacy_crypto_source_preserved":True,
      "disclaimer":"Historical bars are midpoint quotes, not executable prices. Crypto and stocks may share the existing Alpaca Paper account, but order journals stay separate. Short selling crypto is unsupported.",
    }
