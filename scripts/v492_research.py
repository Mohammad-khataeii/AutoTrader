"""Run the causal pipeline against privately exported original decision snapshots.

A partial diagnostic stream is allowed only with explicit truncation provenance;
it never satisfies the complete ledger forensic gate.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from autotrader.learning.controller import ingest, mature, publish, run_training
from autotrader.learning.store import Store


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--signals',type=Path,required=True);parser.add_argument('--candles',type=Path,required=True)
    parser.add_argument('--store',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();store=Store(args.store);header=None;count=0;truncated=False
    try:
        with gzip.open(args.signals,'rt') as f:
            for line in f:
                r=json.loads(line,parse_float=str)
                if r.get('type')=='header':header=r
                if header and r.get('database')==header['registry']['primary']['database_name'] and r.get('section')=='signals':
                    row=r['row'];body=row['payload_json'];body=json.loads(body) if isinstance(body,str) else body
                    e=body.get('evidence') or {}
                    ingest(store,{'id':row['signal_id'],'symbol':row['symbol'],'strategy_id':row['strategy_id'],
                        'observed_at':row['created_at'],'evidence':e,'evidence_category':'REVOLUT_X_PROSPECTIVE_PAPER',
                        'baseline_eligible':e.get('entry_eligible') is True,'rejection':','.join(e.get('reasons',[]))},
                        datetime.now().astimezone().isoformat())
                    count+=1
                if count and count%200==0:store.db.commit()
    except EOFError:truncated=True
    store.db.commit()
    if not header:raise ValueError('missing_source_header')
    bars=defaultdict(list)
    with gzip.open(args.candles,'rt') as f:
        for line in f:
            c=json.loads(line,parse_float=str);bars[c['symbol']].append(c)
    now=header['until']
    pending=list(store.db.execute("SELECT payload FROM observations WHERE status='PENDING' ORDER BY observed_at,id"))
    for (payload,) in pending:
        event=json.loads(payload);mature(store,event,bars[event['symbol']],now)
    store.db.commit();run_training(store,now);result=publish(store,now)
    result['source_export']={'signals_read':count,'partial_stream':True,'gzip_truncated':truncated,
        'warning':'Original 24h collector timed out in a later section. These parsed immutable signals are development research; the separate complete 17-database export establishes financial forensics.',
        'source_sha256':hashlib.sha256(args.signals.read_bytes()).hexdigest(),
        'candles_sha256':hashlib.sha256(args.candles.read_bytes()).hexdigest()}
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    # Compact machine-readable training records; full originals remain private.
    with args.output.with_name('causal-dataset.jsonl').open('w') as f:
        for (row,) in store.db.execute("SELECT result FROM observations WHERE status='LABELED' ORDER BY observed_at,id"):
            f.write(row+'\n')
    store.close();print(json.dumps({'status':result['status'],'signals':count,'dataset':result['dataset']}))


if __name__=='__main__':main()
