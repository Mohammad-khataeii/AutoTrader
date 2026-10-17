"""Run via SSH stdin in backend: SELECT-only snapshots, no remote files or API writes."""
import json
from datetime import UTC, datetime

import psycopg
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from autotrader.config import Settings

settings = Settings()
url = make_url(settings.database_url).set(drivername="postgresql")
result = {"captured_at": datetime.now(UTC).isoformat(), "read_only": True,
          "window_hours": 24, "live_trading_enabled": settings.live_trading_enabled,
          "accounts": {}}

def snapshot(database):
    # Server-enforced READ ONLY; attempts to mutate fail, including triggers.
    with psycopg.connect(url.set(database=database).render_as_string(hide_password=False),
                         row_factory=dict_row, options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '30s'")
        def rows(query):
            if database == url.database and ('FROM market_features WHERE' in query or 'FROM strategy_signals WHERE' in query or 'FROM trading_decisions WHERE' in query):
                query = query.split(' LIMIT ')[0] + ' LIMIT 3'
            return conn.execute(query).fetchall()
        data = {"states": rows("SELECT key,state,reason,payload_json,updated_at FROM system_state WHERE key IN ('worker','scanner','runtime_health','shadow_reconciliation','operation','coordinator_lease','position_monitor') OR key LIKE 'market_data:%' OR key LIKE 'shadow_candle:%' ORDER BY key LIMIT 200"),
                "counts": {t: rows('SELECT count(*) AS n FROM '+t)[0]['n'] for t in
                           ('trading_decisions','orders','fills','positions','financial_journal')},
                "decisions": rows("SELECT * FROM trading_decisions WHERE created_at >= now()-interval '24 hours' ORDER BY created_at LIMIT 1000"),
                "features": rows("SELECT * FROM market_features WHERE created_at >= now()-interval '24 hours' ORDER BY created_at LIMIT 1000"),
                "signals": rows("SELECT * FROM strategy_signals WHERE created_at >= now()-interval '24 hours' ORDER BY created_at LIMIT 6000"),
                "explanations": rows("SELECT key,payload_json FROM system_state WHERE key LIKE 'shadow_explanation:%' AND updated_at >= now()-interval '24 hours' ORDER BY updated_at LIMIT 1000"),
                "incidents": rows("SELECT severity,status,message,created_at FROM system_incidents ORDER BY created_at DESC LIMIT 100"),
                "positions": rows("SELECT symbol,quantity,closed_at FROM positions"),
                "orders": rows("SELECT symbol,status,simulated FROM orders"),
                "candle_sources": rows("SELECT source,symbol,timeframe,count(*),min(timestamp),max(timestamp) FROM market_candles GROUP BY source,symbol,timeframe"),
                "window_decision_counts": rows("SELECT action,accepted,rejected_reason,count(*) FROM trading_decisions WHERE created_at >= now()-interval '24 hours' GROUP BY action,accepted,rejected_reason"),
                "reconciliation": None}
        if database == url.database:
            data['registry'] = rows("SELECT experiment_id,state,manifest_json,database_name FROM shadow_experiments ORDER BY created_at")
            data['candles'] = rows("SELECT DISTINCT ON (symbol,timestamp) symbol,timeframe,timestamp,open,high,low,close,volume,source FROM market_candles WHERE timestamp >= now()-interval '85 hours' ORDER BY symbol,timestamp,id DESC LIMIT 4000")
        return data

official = snapshot(url.database)
registry = official.pop('registry')
print(json.dumps({'kind':'metadata', **{k:v for k,v in result.items() if k != 'accounts'}}, default=str), flush=True)
for record in registry:
    manifest = json.loads(record.pop('manifest_json'))
    record['manifest'] = {k:v for k,v in manifest.items() if k not in ('database_name','official_database','name')}
print(json.dumps({'kind':'account','identity':'official', 'data': official}, default=str), flush=True)
for record in registry:
    database = record.pop('database_name')
    print(json.dumps({'kind':'account','identity':record['experiment_id'], 'record':record,
                      'data':snapshot(database)}, default=str), flush=True)
