"""Bounded read-only source collection in the dedicated research process.

No training or filesystem writes execute in the trading worker. The only writer
is a locked research-store process. Financial PostgreSQL sessions are READ ONLY.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from autotrader.domain import utc_now
from autotrader.learning.controller import ingest, mature, publish, run_training
from autotrader.learning.features import stamp
from autotrader.learning.store import Store
from autotrader.research.data import atomic_write, canonical

LOG = logging.getLogger(__name__)


def connect(url: Any) -> Any:
    return psycopg.connect(dbname=url.database, user=url.username, password=url.password,
        host=url.host, port=url.port or 5432, row_factory=dict_row,
        options='-c default_transaction_read_only=on -c statement_timeout=15000 -c work_mem=2MB',
        connect_timeout=5)


def tick(settings: Any) -> None:
    if not settings.personal_paper_enabled or settings.live_trading_enabled:
        return
    root = Path(settings.research_root).parent/'reports'/'learning' if settings.research_root != '/app/research' else Path('/app/reports/learning')
    root.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (root/'research.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        _locked_tick(settings, root)


def _locked_tick(settings: Any, root: Path) -> None:
    now = utc_now().isoformat();url = make_url(settings.database_url)
    if url.get_backend_name() != 'postgresql':
        return
    with connect(url) as official:
        origin = official.execute("SELECT payload_json FROM system_state WHERE key='personal_paper_v47'").fetchone()
        if not origin:
            return
        manifest = json.loads(origin['payload_json'])
        pointer = official.execute("SELECT payload_json FROM system_state WHERE key='personal_paper_active_profile'").fetchone()
        if pointer:
            profile = official.execute('SELECT payload_json FROM system_state WHERE key=%s', (json.loads(pointer['payload_json'])['key'],)).fetchone()
            if not profile:
                raise ValueError('missing_primary_profile')
            manifest = json.loads(profile['payload_json'])
    database = manifest['database_name']
    if not re.fullmatch('autotrader_paper_[a-f0-9]{32}', database) or database == url.database:
        raise ValueError('research_source_scope_failed')
    store = Store(root)
    try:
        from autotrader.research.data import digest
        store.set('baseline_manifest', {'version': manifest['version'], 'sha256': digest(canonical(manifest))})
        cursor = store.get('cursor', ['1970-01-01T00:00:00+00:00', ''])
        with connect(url.set(database=database)) as source:
            signals = source.execute('SELECT signal_id,strategy_id,symbol,created_at,payload_json FROM strategy_signals WHERE (created_at,signal_id)>(%s::timestamptz,%s) ORDER BY created_at,signal_id LIMIT 200', cursor).fetchall()
            for row in signals:
                payload = json.loads(row['payload_json']);e = payload.get('evidence') or {}
                event = {'id': row['signal_id'], 'symbol': row['symbol'], 'strategy_id': row['strategy_id'],
                    'observed_at': row['created_at'].isoformat(), 'evidence': e,
                    'evidence_category': manifest['data_kind'], 'baseline_eligible': e.get('entry_eligible') is True,
                    'rejection': ','.join(e.get('reasons', []))}
                ingest(store, event, now)
                cursor = [row['created_at'].isoformat(), row['signal_id']]
            # Cursor and imported rows commit together, so crashes replay idempotently.
            store.set('cursor', cursor);store.db.commit()
            pending = store.db.execute("SELECT payload FROM observations WHERE status='PENDING' AND observed_at<=? AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY observed_at,id LIMIT 80",
                ((stamp(now)-timedelta(hours=4)).isoformat(), now)).fetchall()
            for (payload,) in pending:
                event = json.loads(payload);start = stamp(event['observed_at'])
                rows = source.execute("SELECT symbol,timestamp,open,high,low,close,source FROM market_candles WHERE symbol=%s AND timeframe='5m' AND timestamp>=%s AND timestamp<=%s ORDER BY timestamp,id LIMIT 1000",
                    (event['symbol'], start, start+timedelta(hours=4))).fetchall()
                candles = [{k: v.isoformat() if k == 'timestamp' else str(v) if k in ('open', 'high', 'low', 'close') else v for k, v in r.items()} for r in rows]
                mature(store, event, candles, now)
                store.db.execute("UPDATE observations SET next_attempt_at=? WHERE id=? AND status='PENDING'",
                    ((stamp(now)+timedelta(minutes=30)).isoformat(), event['id']))
            # Actual closed trades are retained separately from modeled labels.
            # Original entry profile, fees, reasons and P&L are never overwritten.
            positions = source.execute("SELECT p.position_id,p.symbol,p.opened_at,p.closed_at,p.realized_pnl,o.created_at AS entry_observed_at,o.filled_quantity,o.average_fill_price,(SELECT sum(f.fee) FROM fills f WHERE f.position_id=p.position_id) AS total_fees,(SELECT sum(f.fee) FROM fills f WHERE f.position_id=p.position_id AND f.side='BUY') AS buy_fee,o.execution_json FROM positions p JOIN orders o ON o.position_id=p.position_id AND o.side='BUY' AND o.filled_quantity>0 WHERE p.state='CLOSED' ORDER BY p.closed_at DESC LIMIT 1000").fetchall()
            for row in positions:
                e = json.loads(row['execution_json']).get('strategy_evidence', {})
                result = {k: v.isoformat() if hasattr(v, 'isoformat') else str(v) for k, v in row.items() if k != 'execution_json'}
                payload = json.loads(row['execution_json'])
                result.update(execution_profile=e.get('execution_profile'), strategy=payload.get('strategy_id'), evidence_category='ACTUAL_PRIMARY_PAPER_LEDGER')
                from autotrader.learning.features import build
                try:
                    result['features'] = build(e, payload['strategy_id'], row['entry_observed_at'].isoformat())
                    result['planned_risk_eur'] = e['economics']['measurements']['expected_net_stop_loss_eur']
                except (KeyError, ValueError, TypeError, ZeroDivisionError) as error:
                    result['feature_failure'] = type(error).__name__
                store.db.execute('INSERT OR IGNORE INTO realized VALUES (?,?)', (row['position_id'], canonical(result).decode()))
        run_training(store, now);publish(store, now)
    except Exception as error:
        store.db.rollback()
        # Exception strings may contain a credential-bearing DSN; expose type only.
        atomic_write(root/'collector-error.json', canonical({'observed_at': now, 'error_type': type(error).__name__, 'status': 'COLLECTION_FAILED', 'primary_unchanged': True}))
        raise
    finally:
        store.close()


async def run(settings: Any) -> None:
    while True:
        try:
            await asyncio.to_thread(tick, settings)
        except Exception as error:
            LOG.warning('ML research collection failed', extra={'error_type': type(error).__name__})
        await asyncio.sleep(60)
