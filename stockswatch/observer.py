"""Durable read-only scanner telemetry for the isolated USD paper engine.

A run event is committed before starting each potentially slow operation. No secrets,
request bodies, raw company news, or account credentials are written to telemetry.
The pre-existing bars/decisions/orders/fills remain the accounting authorities.
"""
from __future__ import annotations
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from .storage import connect, connect_readonly, one, rows, utc

SCHEMA = '''
CREATE TABLE IF NOT EXISTS sw_scan_runs (
 id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT,
 state TEXT NOT NULL, stage TEXT NOT NULL,
 asset_count INTEGER NOT NULL, batch_size INTEGER NOT NULL DEFAULT 0,
 completed INTEGER NOT NULL DEFAULT 0, summary_json TEXT NOT NULL DEFAULT '{}',
 failure_code TEXT
);
CREATE INDEX IF NOT EXISTS idx_sw_scan_runs_started ON sw_scan_runs(started_at DESC);
CREATE TABLE IF NOT EXISTS sw_scan_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
 at TEXT NOT NULL, stage TEXT NOT NULL, severity TEXT NOT NULL,
 symbol TEXT, message TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}',
 elapsed_ms INTEGER, FOREIGN KEY(run_id) REFERENCES sw_scan_runs(id)
);
CREATE INDEX IF NOT EXISTS idx_sw_scan_events_time ON sw_scan_events(id DESC);
CREATE INDEX IF NOT EXISTS idx_sw_scan_events_run ON sw_scan_events(run_id,id);
CREATE TABLE IF NOT EXISTS sw_scan_live (
 id INTEGER PRIMARY KEY CHECK(id=1), run_id TEXT,
 state TEXT NOT NULL, stage TEXT NOT NULL,
 symbol TEXT, completed INTEGER NOT NULL DEFAULT 0,
 batch_size INTEGER NOT NULL DEFAULT 0, asset_count INTEGER NOT NULL DEFAULT 0,
 started_at TEXT, updated_at TEXT NOT NULL, next_due_at TEXT
);
CREATE TABLE IF NOT EXISTS sw_signal_snapshots (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
 symbol TEXT NOT NULL, signal_day TEXT NOT NULL,
 policy_version TEXT NOT NULL, score REAL NOT NULL, regime TEXT NOT NULL,
 action TEXT NOT NULL, source TEXT NOT NULL, adjustment TEXT NOT NULL,
 features_json TEXT NOT NULL, signals_json TEXT NOT NULL, reasons_json TEXT NOT NULL,
 recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sw_signal_snapshots_symbol_day ON sw_signal_snapshots(symbol,signal_day DESC);
CREATE INDEX IF NOT EXISTS idx_sw_signal_snapshots_run ON sw_signal_snapshots(run_id);
'''

def init_journal():
    with connect() as c:
        c.executescript(SCHEMA)
        stamp = utc()
        c.execute("""INSERT OR IGNORE INTO sw_scan_live
          (id,state,stage,updated_at) VALUES(1,'IDLE','WAITING',?)""",(stamp,))
        # A process killed during a scan leaves an accurate interrupted record.
        c.execute("""UPDATE sw_scan_runs SET state='INTERRUPTED',ended_at=?,
                    failure_code='PROCESS_RESTARTED' WHERE ended_at IS NULL""",(stamp,))
        c.execute("""UPDATE sw_scan_live SET state='INTERRUPTED',stage='RESTARTED',
                    symbol=NULL,updated_at=? WHERE state='RUNNING'""",(stamp,))


def _details(d):
    """Strictly bounded structured metadata; callers supply known, non-sensitive fields."""
    clean={}
    for k,v in (d or {}).items():
        if not isinstance(k,str) or len(k)>48 or not k.replace('_','').isalnum():continue
        if isinstance(v,bool) or v is None:clean[k]=v
        elif isinstance(v,(int,float)) and math.isfinite(v):clean[k]=v
        elif isinstance(v,str):clean[k]=v[:180]
    return json.dumps(clean,separators=(',',':'),sort_keys=True)


class Observer:
    def __init__(self):
        self.id='swscan-'+uuid4().hex
        self.started=time.monotonic()
        self.stage_started=self.started
        self.batch_size=0
        self.completed=0
        self.asset_count=0

    def start(self):
        self.asset_count=one('SELECT COUNT(*) AS n FROM assets WHERE enabled=1')['n']
        now=utc()
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('''INSERT INTO sw_scan_runs(id,started_at,state,stage,asset_count)
                         VALUES(?,?,?,?,?)''',(self.id,now,'RUNNING','START',self.asset_count))
            c.execute('''UPDATE sw_scan_live SET run_id=?,state='RUNNING',stage='START',
                         symbol=NULL,completed=0,batch_size=0,asset_count=?,started_at=?,
                         updated_at=?,next_due_at=NULL WHERE id=1''',
                         (self.id,self.asset_count,now,now))
            c.commit()
        self.event('START','RUNNING','Scan cycle started',asset_count=self.asset_count)

    def event(self,stage,severity,message,symbol=None,completed=None,batch_size=None,**details):
        if completed is not None:self.completed=int(completed)
        if batch_size is not None:self.batch_size=int(batch_size)
        now=utc()
        elapsed=int((time.monotonic()-self.stage_started)*1000)
        self.stage_started=time.monotonic()
        clean_symbol=symbol if symbol is None or (symbol.isascii() and len(symbol)<=12 and symbol.replace('-','').replace('.','').isalnum()) else None
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('''INSERT INTO sw_scan_events(run_id,at,stage,severity,symbol,message,details_json,elapsed_ms)
                         VALUES(?,?,?,?,?,?,?,?)''',
                         (self.id,now,stage,severity,clean_symbol,message[:220],_details(details),elapsed))
            c.execute('''UPDATE sw_scan_runs SET stage=?,completed=?,batch_size=? WHERE id=?''',
                         (stage,self.completed,self.batch_size,self.id))
            c.execute('''UPDATE sw_scan_live SET state='RUNNING',stage=?,symbol=?,completed=?,
                         batch_size=?,updated_at=? WHERE id=1''',
                         (stage,clean_symbol,self.completed,self.batch_size,now))
            c.commit()

    def finish(self,state,summary=None,failure_code=None):
        now=utc()
        seconds=max(120,min(86400,int(os.getenv('STOCKSWATCH_TICK_SECONDS','900'))))
        next_due=(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat(timespec='seconds')
        metadata={'result':state, 'duration_ms':int((time.monotonic()-self.started)*1000)}
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('''INSERT INTO sw_scan_events(run_id,at,stage,severity,symbol,message,details_json,elapsed_ms)
                         VALUES(?,?,?,?,?,?,?,?)''',
                      (self.id,now,'CYCLE_END','ERROR' if failure_code else 'OK',None,
                       'Scanner cycle '+state.lower(),_details(metadata),metadata['duration_ms']))
            c.execute('''UPDATE sw_scan_runs SET ended_at=?,state=?,stage='CYCLE_END',
                         completed=?,batch_size=?,summary_json=?,failure_code=? WHERE id=?''',
                      (now,state,self.completed,self.batch_size,_details(summary),failure_code,self.id))
            c.execute('''UPDATE sw_scan_live SET state=?,stage='CYCLE_END',symbol=NULL,completed=?,
                         batch_size=?,updated_at=?,next_due_at=? WHERE id=1''',
                      (state,self.completed,self.batch_size,now,next_due))
            c.commit()


def scanner_snapshot():
    live=one('SELECT * FROM sw_scan_live WHERE id=1') or {'state':'NOT_READY'}
    recent=rows('''SELECT id,run_id,at,stage,severity,symbol,message,details_json,elapsed_ms
                   FROM sw_scan_events ORDER BY id DESC LIMIT 85''')
    for event in recent:
        event['details']=json.loads(event.pop('details_json'))
    history=rows('''SELECT id,started_at,ended_at,state,asset_count,batch_size,
                          completed,failure_code FROM sw_scan_runs ORDER BY started_at DESC LIMIT 15''')
    counts={}
    for table,name in [('assets','assets'),('bars','bars'),('decisions','decisions'),
                       ('sw_signal_snapshots','feature_snapshots'),('sw_scan_events','events'),
                       ('sw_scan_runs','runs'),('fills','fills'),('filings','filings'),
                       ('facts','facts'),('macro','macro'),('research_runs','research_runs'),
                       ('model_runs','model_runs'),('ai_insights','ai_insights')]:
        counts[name]=one('SELECT COUNT(*) n FROM '+table)['n']
    counts['assets_with_history']=one('SELECT COUNT(DISTINCT symbol) n FROM bars')['n']
    return {'live':live,'events':recent,'runs':history,'counts':counts,
            'sampled_at':utc(),'paper_only':True,'feed_kind':'DAILY_COMPLETED_BARS',
            'warning':'Scanner activity is current; Alpaca price bars are end-of-day, not live quotes.'}

# Values in these tables are internal stock research evidence, never secrets.
EXPORT_TABLES={
    'assets':'assets','bars':'bars','sources':'sources','filings':'filings',
    'facts':'facts','macro':'macro','portfolio':'portfolio','positions':'positions',
    'orders':'pending_orders','fills':'fills','decisions':'decisions',
    'equity':'equity_curve','research':'research_runs','ml':'model_runs',
    'ai':'ai_insights','scanner_runs':'sw_scan_runs','scanner_events':'sw_scan_events',
    'signal_features':'sw_signal_snapshots',
    'order_outcomes':'sw_order_outcomes','execution_cycles':'sw_trade_cycles',
    'intraday_cycles':'sw_intraday_cycles','intraday_observations':'sw_intraday_observations',
    'intraday_followups':'sw_intraday_followups',
}

def export_jsonl(kind):
    if kind != 'all' and kind not in EXPORT_TABLES:
        raise ValueError('unsupported_export_kind')
    # Database snapshot is read on the same WAL transaction for consistency.
    # Stream bounded row batches; never buffer a large dataset in service memory.
    with connect_readonly(check_same_thread=False) as c:
        datasets=list(EXPORT_TABLES.items()) if kind=='all' else [(kind,EXPORT_TABLES[kind])]
        for label,table in datasets:
            if label.startswith('intraday_') and not c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                continue
            cursor=c.execute('SELECT * FROM '+table+' ORDER BY rowid')
            while True:
                batch=cursor.fetchmany(256)
                if not batch:break
                if kind=='all':
                    yield ''.join(json.dumps({'dataset':label,'row':dict(r)},separators=(',',':'),allow_nan=False,default=str)+'\n' for r in batch).encode()
                else:
                    yield ''.join(json.dumps(dict(r),separators=(',',':'),allow_nan=False,default=str)+'\n' for r in batch).encode()
