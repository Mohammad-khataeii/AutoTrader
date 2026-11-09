"""StockWatch-only durable ledger. No access to crypto's PostgreSQL or trading models."""
from __future__ import annotations
import json
import os
import sqlite3
from contextlib import contextmanager

from .universe import ASSETS
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.getenv('STOCKSWATCH_DB', '/stockswatch-data/stockswatch.sqlite3')

def utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS assets(symbol TEXT PRIMARY KEY, name TEXT NOT NULL, sector TEXT NOT NULL, cik INTEGER, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS bars(symbol TEXT NOT NULL,day TEXT NOT NULL,o REAL NOT NULL,h REAL NOT NULL,l REAL NOT NULL,c REAL NOT NULL,v REAL NOT NULL,source TEXT NOT NULL,adjustment TEXT NOT NULL,observed_at TEXT NOT NULL,PRIMARY KEY(symbol,day));
CREATE INDEX IF NOT EXISTS idx_bars_day ON bars(day,symbol);
CREATE TABLE IF NOT EXISTS sources(symbol TEXT PRIMARY KEY,last_attempt TEXT,last_success TEXT,last_bar_day TEXT,error TEXT,fail_until TEXT,source TEXT);
CREATE TABLE IF NOT EXISTS filings(id TEXT PRIMARY KEY,symbol TEXT NOT NULL,form TEXT NOT NULL,accepted_at TEXT NOT NULL,accession TEXT NOT NULL,description TEXT,url TEXT NOT NULL,observed_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_filings_symbol_time ON filings(symbol,accepted_at DESC);
CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY,symbol TEXT NOT NULL,tag TEXT NOT NULL,unit TEXT NOT NULL,start_day TEXT,end_day TEXT NOT NULL,filed_day TEXT NOT NULL,accepted_at TEXT NOT NULL,accession TEXT,value REAL NOT NULL,source_url TEXT NOT NULL,observed_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_facts_symbol_accepted ON facts(symbol,accepted_at);
CREATE TABLE IF NOT EXISTS macro(id TEXT PRIMARY KEY,series TEXT NOT NULL,observation_day TEXT NOT NULL,available_at TEXT NOT NULL,value REAL NOT NULL,source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS portfolio(id INTEGER PRIMARY KEY CHECK(id=1),cash REAL NOT NULL,initial_cash REAL NOT NULL,realized REAL NOT NULL,paused INTEGER NOT NULL,high_water REAL NOT NULL,day_buy_count INTEGER NOT NULL DEFAULT 0,buy_count_day TEXT,last_processed_day TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS positions(symbol TEXT PRIMARY KEY,qty INTEGER NOT NULL CHECK(qty>0),avg_cost REAL NOT NULL CHECK(avg_cost>0),stop REAL NOT NULL,entry_day TEXT NOT NULL,sector TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pending_orders(id TEXT PRIMARY KEY,symbol TEXT NOT NULL,side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),signal_day TEXT NOT NULL,decision TEXT NOT NULL,created_at TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('PENDING','FILLED','CANCELLED','EXPIRED')),fill_day TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS once_per_symbol_signal ON pending_orders(symbol,signal_day,side);
CREATE TABLE IF NOT EXISTS fills(id TEXT PRIMARY KEY,order_id TEXT UNIQUE NOT NULL,symbol TEXT NOT NULL,side TEXT NOT NULL,signal_day TEXT NOT NULL,fill_day TEXT NOT NULL,qty INTEGER NOT NULL,price REAL NOT NULL,slippage REAL NOT NULL,fee REAL NOT NULL,realized REAL NOT NULL,source TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY,symbol TEXT NOT NULL,signal_day TEXT NOT NULL,score REAL NOT NULL,regime TEXT NOT NULL,signals_json TEXT NOT NULL,reasons_json TEXT NOT NULL,action TEXT NOT NULL,policy_version TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_decisions_symbol_day ON decisions(symbol,signal_day);
CREATE TABLE IF NOT EXISTS equity_curve(day TEXT PRIMARY KEY,equity REAL NOT NULL,cash REAL NOT NULL,exposure REAL NOT NULL,drawdown REAL NOT NULL,spy_close REAL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS model_runs(id TEXT PRIMARY KEY,trained_at TEXT NOT NULL,cutoff_day TEXT NOT NULL,status TEXT NOT NULL,metrics_json TEXT NOT NULL,weights_json TEXT NOT NULL,source_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_runs(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,status TEXT NOT NULL,report_json TEXT NOT NULL,source_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ai_insights(id TEXT PRIMARY KEY,symbol TEXT NOT NULL,filing_id TEXT NOT NULL,model TEXT NOT NULL,analysis_json TEXT NOT NULL,generated_at TEXT NOT NULL,source_url TEXT NOT NULL,UNIQUE(symbol,filing_id,model));
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
'''


@contextmanager
def connect():
    path=Path(DB_PATH);path.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(str(path),timeout=15,isolation_level=None)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA busy_timeout=10000')
    # The service runs with a read-only container root filesystem. Queries
    # such as /api/stockswatch/status GROUP BY source need a temporary B-tree;
    # SQLite's default file-backed temp store raises SQLITE_IOERR_GETTEMPPATH
    # when /tmp and /var/tmp are not writable. Keep *only* ephemeral sort/temp
    # structures in process memory; the financial ledger and WAL remain on disk.
    # This PRAGMA is connection-local and does not migrate or modify the ledger.
    c.execute('PRAGMA temp_store=MEMORY')
    c.execute('PRAGMA foreign_keys=ON')
    try:
        yield c
    finally:
        c.close()

def init():
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript(SCHEMA)
        for sym,name,sector in ASSETS:
            c.execute('INSERT OR IGNORE INTO assets(symbol,name,sector) VALUES(?,?,?)',(sym,name,sector))
        initial=float(os.getenv('STOCKSWATCH_INITIAL_USD','10000'))
        assert 1000<=initial<=1_000_000
        c.execute('INSERT OR IGNORE INTO portfolio(id,cash,initial_cash,realized,paused,high_water,created_at) VALUES(1,?,?,?,?,?,?)',(initial,initial,0,0,initial,utc()))
        c.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('schema_version','stocks-v1')")

def rows(sql,params=()):
    with connect() as c:return [dict(r) for r in c.execute(sql,params)]

def one(sql,params=()):
    with connect() as c:
        r=c.execute(sql,params).fetchone();return dict(r) if r else None

def setting(key, default=None):
    r=one('SELECT value FROM metadata WHERE key=?',(key,))
    return json.loads(r['value']) if r else default

def set_setting(key,value):
    with connect() as c:c.execute('INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value,separators=(',',':'))))


def mounted_directory(path):
    # os.path.ismount() cannot see Linux bind mounts on the same filesystem.
    import re

    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.is_file():
        return path.is_mount()
    for line in mountinfo.read_text().splitlines():
        target = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), line.split()[4])
        if Path(target) == path:
            return True
    return False


@contextmanager
def worker_ownership():
    """Own the writable ledger for the process lifetime and validate its mount."""
    import fcntl

    path = Path(DB_PATH).resolve()
    # Allow initialization only for an explicitly provisioned disposable ledger
    # or a first install with an intentionally mounted empty directory.
    allow_init = os.getenv("STOCKSWATCH_ALLOW_INIT") == "1"
    if not mounted_directory(path.parent):
        raise RuntimeError("stockswatch_db_parent_not_mounted")
    if not path.is_file() and not allow_init:
        raise RuntimeError("stockswatch_existing_db_missing")
    with (path.parent / (path.name + ".worker.lock")).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("stockswatch_worker_already_running") from None
        if path.exists():
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as c:
                schema = c.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()
                account = c.execute("SELECT 1 FROM portfolio WHERE id=1").fetchone()
                if not schema or schema[0] != "stocks-v1" or not account:
                    raise RuntimeError("stockswatch_existing_ledger_unrecognized")
        yield


EXECUTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS sw_eod_observations (
    symbol TEXT NOT NULL, day TEXT NOT NULL,
    o REAL NOT NULL, h REAL NOT NULL, l REAL NOT NULL, c REAL NOT NULL, v REAL NOT NULL,
    source TEXT NOT NULL, adjustment TEXT NOT NULL, observed_at TEXT NOT NULL,
    PRIMARY KEY(symbol, day)
);
CREATE TABLE IF NOT EXISTS sw_price_checks (
    symbol TEXT PRIMARY KEY, day TEXT NOT NULL, checked_at TEXT NOT NULL,
    status TEXT NOT NULL, actions_since TEXT, actions_json TEXT
);
CREATE TABLE IF NOT EXISTS sw_order_evidence (
    order_id TEXT PRIMARY KEY REFERENCES pending_orders(id),
    policy_version TEXT NOT NULL, target_day TEXT NOT NULL, signal_source TEXT NOT NULL,
    signal_observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sw_order_outcomes (
    order_id TEXT PRIMARY KEY REFERENCES pending_orders(id),
    reason TEXT NOT NULL, recorded_at TEXT NOT NULL, detail_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sw_trade_cycles (
    id TEXT PRIMARY KEY, recorded_at TEXT NOT NULL, market_day TEXT NOT NULL,
    report_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sw_trade_cycles_time ON sw_trade_cycles(recorded_at);
-- Ancillary certification only: never holds positions, balances or order intents.
CREATE TABLE IF NOT EXISTS sw_historical_gap_proofs (
    symbol TEXT NOT NULL,
    gap_day TEXT NOT NULL,
    previous_day TEXT NOT NULL,
    raw_prev_close REAL NOT NULL,
    raw_next_open REAL NOT NULL,
    status TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY(symbol,gap_day)
);
"""


def init_execution():
    with connect() as c:
        c.executescript(EXECUTION_SCHEMA)
