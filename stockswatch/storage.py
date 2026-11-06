"""StockWatch-only durable ledger. No access to crypto's PostgreSQL or trading models."""
from __future__ import annotations
import json
import os
import sqlite3
from contextlib import contextmanager
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

ASSETS = [
('AAPL','Apple','Technology'),('MSFT','Microsoft','Technology'),('GOOGL','Alphabet','Communication'),
('AMZN','Amazon','Consumer Discretionary'),('NVDA','NVIDIA','Technology'),('META','Meta','Communication'),
('AMD','AMD','Technology'),('TSM','TSMC ADR','Technology'),('QCOM','Qualcomm','Technology'),
('AVGO','Broadcom','Technology'),('JPM','JPMorgan Chase','Financials'),('V','Visa','Financials'),
('MA','Mastercard','Financials'),('UNH','UnitedHealth','Healthcare'),('JNJ','Johnson & Johnson','Healthcare'),
('ABBV','AbbVie','Healthcare'),('LLY','Eli Lilly','Healthcare'),('XOM','Exxon Mobil','Energy'),
('CVX','Chevron','Energy'),('COST','Costco','Consumer Staples'),('WMT','Walmart','Consumer Staples'),
('PG','Procter & Gamble','Consumer Staples'),('KO','Coca-Cola','Consumer Staples'),
('CAT','Caterpillar','Industrials'),('GE','GE Aerospace','Industrials'),('DIS','Disney','Communication'),
('NFLX','Netflix','Communication'),('UBER','Uber','Industrials'),('ORCL','Oracle','Technology'),
('CRM','Salesforce','Technology'),('SPY','S&P 500 ETF','Benchmark'),('QQQ','Nasdaq-100 ETF','Benchmark'),
]

@contextmanager
def connect():
    path=Path(DB_PATH);path.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(str(path),timeout=15,isolation_level=None)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA busy_timeout=10000')
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
