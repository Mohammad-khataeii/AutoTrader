"""Paced, resumable 50-market AlpacaCrypto historical warmup.

Downloads *completed* Alpaca US historical 1Day + 1Hour candles, using the
existing crypto midpoint observation tables. Quotes in BTC, USDT or USDC are
kept in their native quote unit; those 37 pairs are never sent for execution.

The background ac_jobs queue separately fills the full long-form archive.
No broker POST, settings edits, paper orders, or stock market data writes.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timedelta, timezone

from . import alpaca_crypto as ac
from .storage import connect

UTC=timezone.utc
PAIRS=ac.EXPANSION50_PAIRS
SCHEMA="""
CREATE TABLE IF NOT EXISTS ac_expansion50_warmup(
    symbol TEXT PRIMARY KEY,
    last_attempt TEXT,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    latest_result TEXT NOT NULL DEFAULT '{}'
);
"""

def initialize():
    ac.initialize()
    with connect() as db:
        db.executescript(SCHEMA)
        db.executemany(
            "INSERT OR IGNORE INTO ac_expansion50_warmup(symbol) VALUES(?)",
            ((s,) for s in PAIRS))

def counts(symbol,now):
    if symbol not in PAIRS:
        raise ValueError("crypto_expansion50_symbol_not_allowed")
    ends={"1Hour":ac._floor(now,"1Hour"),"1Day":ac._floor(now,"1Day")}
    result={}
    with connect() as db:
        for tf,end in ends.items():
            start=end-(timedelta(hours=300) if tf=="1Hour" else timedelta(days=300))
            row=db.execute("""SELECT COUNT(*) FROM ac_bars WHERE symbol=?
                AND timeframe=? AND ts>=? AND ts<?""",
                (symbol,tf,start.isoformat(),end.isoformat())).fetchone()
            result[tf]=int(row[0])
    return result

def ready(values):
    return values.get("1Hour",0)>=220 and values.get("1Day",0)>=220

def report(now=None):
    now=now or datetime.now(UTC)
    initialize()
    with connect() as db:
        states={r["symbol"]:dict(r) for r in db.execute(
            "SELECT * FROM ac_expansion50_warmup ORDER BY symbol")}
    result=[]
    for symbol in PAIRS:
        coverage=counts(symbol,now)
        previous=states[symbol]
        result.append({
            "symbol":symbol,
            "quote_currency":symbol.split("/")[1],
            "paper_execution_possible":symbol in ac.EXECUTION_PAIRS,
            "history_ready":ready(coverage),
            "daily":coverage["1Day"],"hourly":coverage["1Hour"],
            "status":previous["status"],
            "last_attempt":previous["last_attempt"]
        })
    return {"universe":len(ac.PAIRS),
            "new_pairs":len(PAIRS),
            "usd_eligible_universe":len(ac.EXECUTION_PAIRS),
            "research_only_universe":len(ac.RESEARCH_ONLY_PAIRS),
            "warmup_ready":sum(r["history_ready"] for r in result),
            "warmup_remaining":sum(not r["history_ready"] for r in result),
            "pairs":result}

def run(max_pairs=5,now=None):
    if type(max_pairs) is not int or not 1<=max_pairs<=5:
        raise ValueError("crypto_warmup_pair_limit")
    now=now or datetime.now(UTC)
    initialize()
    with connect() as db:
        state={r["symbol"]:dict(r) for r in db.execute(
            "SELECT * FROM ac_expansion50_warmup")}
    selected=[]
    for symbol in PAIRS:
        if ready(counts(symbol,now)):
            continue
        row=state[symbol]
        last=row["last_attempt"]
        if last:
            age=now-ac._stamp(last)
            # An incomplete listing or data outage should not trigger
            # 5-minute repeated remote pagination for the same asset.
            retry=timedelta(hours=12) if row["status"] in (
                "PARTIAL_HISTORY","PROVIDER_UNAVAILABLE") else timedelta(minutes=30)
            if age<retry:
                continue
        selected.append(symbol)
        if len(selected)>=max_pairs:
            break
    result=[]
    if selected:
        with ac.CryptoData() as data:
            for symbol in selected:
                stamp=datetime.now(UTC).isoformat()
                try:
                    evidence=ac.warmup_expansion(data,now,symbols=(symbol,))
                    observed=counts(symbol,datetime.now(UTC))
                    status="READY_HISTORY" if ready(observed) else "PARTIAL_HISTORY"
                    if any(x["status"]=="data_error" for x in evidence):
                        status="PROVIDER_UNAVAILABLE"
                    item={"symbol":symbol,"status":status,
                          "daily":observed["1Day"],"hourly":observed["1Hour"],
                          "data_pages":evidence}
                except (ac.CryptoDataError,ValueError,TypeError) as exc:
                    item={"symbol":symbol,"status":"PROVIDER_UNAVAILABLE",
                          "reason":str(exc)[:100]}
                with connect() as db:
                    db.execute("""UPDATE ac_expansion50_warmup
                        SET last_attempt=?,status=?,latest_result=?
                        WHERE symbol=?""",
                        (stamp,item["status"],json.dumps(item,separators=(",",":")),symbol))
                result.append(item)
    return {"attempted":result,"summary":{
        "new_pair_count":len(PAIRS),
        "attempted_this_run":len(selected),
        "note":"History readiness is not a trade signal; non-USD pairs are research only."}}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pairs",type=int,default=5)
    parser.add_argument("--report",action="store_true")
    args=parser.parse_args()
    payload=report() if args.report else run(max_pairs=args.max_pairs)
    print(json.dumps(payload,indent=2))

if __name__=="__main__":
    main()
