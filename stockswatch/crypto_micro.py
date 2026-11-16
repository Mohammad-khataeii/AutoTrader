"""Causal 5-minute AlpacaCrypto PAPER opportunity sampler.

Alpaca's crypto candles are quote midpoints, including zero-volume intervals.
This scanner NEVER submits orders; paper broker admission separately validates
fresh bid/ask/depth, account, ownership and risk. No leverage or live trading.
"""
from __future__ import annotations

import json
import math
import os
import threading
from datetime import datetime, timedelta, timezone

from . import alpaca_crypto as ac
from .storage import connect

PAIRS = ("BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "LINK/USD")
UTC = timezone.utc
FIVE = timedelta(minutes=5)
_CACHE_LOCK = threading.Lock()
_CACHE_SLOT = None
_CACHE_SIGNALS = []
_CACHE_LAST_REQUEST = None
SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_micro_audit (
 symbol TEXT NOT NULL, bar_at TEXT NOT NULL, evaluated_at TEXT NOT NULL,
 action TEXT NOT NULL, reason TEXT NOT NULL, price REAL,
 details_json TEXT NOT NULL,
 PRIMARY KEY(symbol, bar_at, action, reason));
CREATE INDEX IF NOT EXISTS ac_micro_audit_recent
 ON ac_micro_audit(evaluated_at, action);
"""


def mode():
    val = os.getenv("ALPACA_CRYPTO_MICRO_MODE", "research").lower().strip()
    if val == "paper" and (os.getenv("ALPACA_CRYPTO_ALLOW_PAPER_ORDERS") != "1"
                            or os.getenv("LIVE_TRADING_ENABLED", "false").lower()
                            in ("1", "true", "yes")):
        return "research"
    return val if val in ("off", "research", "paper") else "off"


def bucket(now):
    now = now.astimezone(UTC)
    return now.replace(minute=5 * (now.minute // 5), second=0, microsecond=0)


def _ema(values, n):
    if len(values) < n:
        return None
    v = sum(values[:n]) / n
    k = 2.0 / (n + 1)
    for c in values[n:]:
        v += k * (c - v)
    return v


def _rsi(values):
    changes = [b-a for a,b in zip(values[-15:-1], values[-14:])]
    gains = sum(max(d,0) for d in changes) / 14
    losses = sum(max(-d,0) for d in changes) / 14
    if gains + losses == 0:
        return 50.0
    return 100 - 100 / (1 + gains / losses) if losses else 100.0


def evaluate(symbol, candles, asof, *, btc_recent=None):
    """Use only 5m candles completed strictly before asof, no future bars."""
    checks = {}
    result = {"symbol": symbol, "action": "HOLD", "reason": "micro_no_entry",
              "score": 0.0, "price": None, "stop": None, "target": None,
              "bar_at": None, "gates": {"entry_strategy": "micro_5m"}}
    def fail(why):
        result["reason"] = why
        result["gates"]["checks"] = dict(checks)
        return result
    if symbol not in PAIRS or asof.tzinfo is None:
        return fail("micro_invalid_symbol_or_time")
    if len(candles) < 36:
        return fail("micro_insufficient_5m_bars")
    c = list(candles[-36:])
    expected = bucket(asof) - FIVE
    try:
        ts = [ac._stamp(x["ts"]) for x in c]
        if ts[-1] != expected or any(ts[i] - ts[i-1] != FIVE for i in range(1,len(ts))):
            return fail("micro_5m_stale_or_gapped")
        for row in c:
            vals = [float(row[k]) for k in ("o","h","l","c","v")]
            o,h,l,close,vol = vals
            if (not all(math.isfinite(x) for x in vals) or
                    min(o,h,l,close) <= 0 or vol < 0 or
                    h < max(o,close,l) or l > min(o,close,h)):
                return fail("micro_invalid_ohlcv")
            if vol == 0 and abs(close/o - 1) > 0.04:
                return fail("micro_untraded_quote_spike")
        v = [float(x["v"]) for x in c]
        close = [float(x["c"]) for x in c]
        low = [float(x["l"]) for x in c]
        hi = [float(x["h"]) for x in c]
        op = [float(x["o"]) for x in c]
        now_close = close[-1]
        ema8 = _ema(close,8); prev_ema8=_ema(close[:-1],8)
        atr = sum(max(hi[i]-low[i],abs(hi[i]-close[i-1]),
                      abs(low[i]-close[i-1])) for i in range(len(c)-14,len(c))) / 14
        rsi = _rsi(close)
        recent_btc_ok = True
        if symbol != "BTC/USD":
            if btc_recent is None or len(btc_recent) < 7:
                recent_btc_ok = False
            else:
                b = list(btc_recent[-7:])
                bts = [ac._stamp(x["ts"]) for x in b]
                recent_btc_ok = (bts[-1] == expected and
                    all(bts[i]-bts[i-1] == FIVE for i in range(1,len(bts))) and
                    all(float(x["c"])>0 and float(x["v"])>=0 for x in b) and
                    float(b[-1]["c"])/float(b[0]["c"]) >= 0.988)
        checks["btc_30m_not_liquidating"] = bool(recent_btc_ok)
        checks["trade_volume"] = v[-1]>0 and sum(x>0 for x in v[-6:])>=3
        checks["ema_reclaim"] = now_close>ema8 and ema8>=prev_ema8
        checks["positive_5m_candle"] = now_close>op[-1] and now_close>close[-2]
        checks["three_bar_momentum"] = 0.001 <= now_close / close[-3] - 1 <= 0.022
        checks["breakout_or_higher_lows"] = (now_close > max(close[-7:-1])
              or low[-1]>low[-2]>low[-3])
        checks["not_extended"] = 0 <= now_close-ema8 <= 1.5*atr
        checks["volatility_and_rsi"] = 0.0006 <= atr/now_close <= 0.025 and 45 <= rsi <= 78
        risk = max(1.7*atr,0.0045*now_close)
        stop = now_close-risk
        target = now_close+2.3*risk
        checks["exit_levels"] = stop>0 and target>now_close>stop
        result.update(price=now_close,bar_at="micro:"+ts[-1].isoformat(),
                      score=round(sum(checks.values())/len(checks),4))
        result["gates"].update(checks=checks,atr_pct=round(atr/now_close*100,4),
                              rsi14=round(rsi,2),ema8=round(ema8,8),
                              reported_5m_volume=v[-1])
        if not all(checks.values()):
            result["reason"] = "micro_no_entry:" + ",".join(k for k,ok in checks.items() if not ok)
            return result
        result.update(action="BUY",reason="micro_5m_momentum_paper",
                      stop=round(stop,10),target=round(target,10))
        return result
    except (KeyError,TypeError,ValueError,OverflowError,ZeroDivisionError):
        return fail("micro_invalid_5m_data")


def fetch(data, now):
    """Bounded 5m Alpaca US GET; only completed candles are returned."""
    end = bucket(now)
    start = end - timedelta(hours=6)
    response = data.get("/v1beta3/crypto/us/bars", {
        "symbols": ",".join(PAIRS), "timeframe": "5Min",
        "start": start.isoformat(), "end": end.isoformat(),
        "sort": "asc", "limit": 10000})
    records = response.get("bars")
    if not isinstance(records,dict) or set(records)-set(PAIRS):
        raise ac.CryptoDataError("micro_bars_unexpected_symbols")
    if response.get("next_page_token"):
        raise ac.CryptoDataError("micro_bars_pagination_incomplete")
    out = {}
    for symbol in PAIRS:
        source = records.get(symbol, [])
        if not isinstance(source,list) or len(source)>150:
            raise ac.CryptoDataError("micro_bars_invalid_shape")
        arr=[]
        previous = None
        for bar in source:
            t=ac._stamp(bar.get("t"))
            if t>=end:
                continue
            if t<start or (previous is not None and t<=previous):
                raise ac.CryptoDataError("micro_bars_order")
            previous=t
            o,h,l,c=[ac._number(bar.get(k)) for k in ("o","h","l","c")]
            v=ac._number(bar.get("v",0),positive=False)
            if h < max(o,l,c) or l>min(o,h,c):
                raise ac.CryptoDataError("micro_bars_invalid_ohlcv")
            arr.append({"ts":t.isoformat(),"o":o,"h":h,"l":l,"c":c,"v":v})
        out[symbol]=arr
    return out


def scan(data, now):
    """One minute-bounded GET batch. Research mode logs but cannot place orders."""
    global _CACHE_SLOT,_CACHE_SIGNALS,_CACHE_LAST_REQUEST
    current=mode()
    if current=="off":
        return []
    slot=bucket(now)
    with _CACHE_LOCK:
        if _CACHE_SLOT == slot:
            return list(_CACHE_SIGNALS) if current=="paper" else []
        if (_CACHE_LAST_REQUEST is not None and
                now - _CACHE_LAST_REQUEST < timedelta(seconds=55)):
            return []
        _CACHE_LAST_REQUEST=now
        observations=fetch(data,now)
        bench=observations.get("BTC/USD",[])
        outcomes=[evaluate(symbol,observations.get(symbol,[]),now,btc_recent=bench)
                  for symbol in PAIRS]
        # Finalized signal rows only: empty bars cannot be mistaken for a trade.
        with connect() as c:
            c.executescript(SCHEMA)
            for outcome in outcomes:
                if outcome["bar_at"]:
                    c.execute("""INSERT OR IGNORE INTO ac_micro_audit
                    (symbol,bar_at,evaluated_at,action,reason,price,details_json)
                    VALUES(?,?,?,?,?,?,?)""",(outcome["symbol"],outcome["bar_at"],
                      now.isoformat(),outcome["action"],outcome["reason"],
                      outcome["price"],json.dumps(outcome["gates"],sort_keys=True)))
        with connect() as c:
            c.execute("DELETE FROM ac_micro_audit WHERE evaluated_at<?",
                      ((now-timedelta(days=30)).isoformat(),))
        _CACHE_SLOT=slot
        _CACHE_SIGNALS=[x for x in outcomes if x["action"]=="BUY"]
        return list(_CACHE_SIGNALS) if current=="paper" else []


def read_only_status():
    """Summarize observed completed 5m decisions; never contacts a broker."""
    from .storage import one, rows
    if not one("SELECT name FROM sqlite_master WHERE type='table' AND name='ac_micro_audit'"):
        return {"mode":mode(),"state":"AWAITING_FIRST_SCANNER_PASS","observations":0}
    decisions=rows("""SELECT action,COUNT(*) n FROM ac_micro_audit
        WHERE evaluated_at>=? GROUP BY action""",
        ((datetime.now(UTC)-timedelta(days=7)).isoformat(),))
    recent=rows("""SELECT symbol,bar_at,evaluated_at,action,reason,price
        FROM ac_micro_audit ORDER BY evaluated_at DESC LIMIT 12""")
    return {"mode":mode(),"state":"AUDIT_AVAILABLE","observations":sum(x["n"] for x in decisions),
            "counts":{x["action"]:x["n"] for x in decisions},"recent":recent}


if __name__ == "__main__":
    print(json.dumps(read_only_status(),indent=2,sort_keys=True))
