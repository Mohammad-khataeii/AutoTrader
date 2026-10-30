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
from autotrader.learning.controller import mature, publish, run_training
from autotrader.learning.features import stamp
from autotrader.learning.lifecycle import ingest
from autotrader.learning.lifecycle import mature as mature_market
from autotrader.learning.market_model import tick as train_market
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
        provider_rows = official.execute("SELECT key,payload_json FROM system_state WHERE key='market_metrics' OR key LIKE 'market_window:%%' ORDER BY created_at DESC LIMIT 5").fetchall()
    database = manifest['database_name']
    if not re.fullmatch('autotrader_paper_[a-f0-9]{32}', database) or database == url.database:
        raise ValueError('research_source_scope_failed')
    store = Store(root)
    try:
        from autotrader.research.data import digest
        store.set('baseline_manifest', {'version': manifest['version'], 'sha256': digest(canonical(manifest))})
        store.set('provider_measurements', {r['key']: json.loads(r['payload_json']) for r in provider_rows})
        fresh_default = [(stamp(now)-timedelta(minutes=5)).isoformat(), '']
        with connect(url.set(database=database)) as source:
            # Prioritize contemporary inference independently of historical repair.
            # Additive cursors leave the legacy observations and cursor untouched.
            for key, default, limit in [('v493_fresh_cursor', fresh_default, 400),
                                         ('v493_backfill_cursor', ['1970-01-01T00:00:00+00:00',''], 800)]:
                cursor = store.get(key, default)
                signals = source.execute('SELECT signal_id,strategy_id,symbol,created_at,payload_json FROM strategy_signals WHERE (created_at,signal_id)>(%s::timestamptz,%s) AND created_at<=%s::timestamptz ORDER BY created_at,signal_id LIMIT %s', [*cursor,now,limit]).fetchall()
                for row in signals:
                    payload = json.loads(row['payload_json']);e = payload.get('evidence') or {}
                    event = {'id':row['signal_id'],'symbol':row['symbol'],'strategy_id':row['strategy_id'],
                             'observed_at':row['created_at'].isoformat(),'evidence':e,
                             'evidence_category':manifest['data_kind'],'baseline_eligible':e.get('entry_eligible') is True,
                             'rejection':','.join(e.get('reasons',[]))}
                    ingest(store,event,now)
                    cursor = [row['created_at'].isoformat(),row['signal_id']]
                store.set(key,cursor)
            # Rows and cursors commit together; duplicate replay is harmless.
            store.db.commit()
            due=(stamp(now)-timedelta(hours=4)).isoformat()
            market_pending=store.db.execute("SELECT payload FROM market_observations WHERE status='PENDING' AND observed_at<=? AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY observed_at,id LIMIT 600",(due,now)).fetchall()
            plan_pending=store.db.execute("SELECT payload FROM observations WHERE status='PENDING' AND observed_at<=? AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY observed_at,id LIMIT 80",(due,now)).fetchall()
            tasks=[('market',json.loads(r[0])) for r in market_pending]+[('plan',json.loads(r[0])) for r in plan_pending]
            # Fetch one bounded completed path per asset, shared by its tasks.
            by_symbol: dict[str,list[tuple[str,dict[str,Any]]]]={}
            for kind,event in tasks:by_symbol.setdefault(event['symbol'],[]).append((kind,event))
            for symbol,items in by_symbol.items():
                start=min(stamp(e['observed_at']) for _,e in items)
                end=max(stamp(e['observed_at']) for _,e in items)+timedelta(hours=4)
                rows=source.execute("SELECT symbol,timestamp,open,high,low,close,source FROM market_candles WHERE symbol=%s AND timeframe='5m' AND timestamp>=%s AND timestamp<=%s ORDER BY timestamp,id LIMIT 5000",(symbol,start,end)).fetchall()
                candles=[{k:v.isoformat() if k=='timestamp' else str(v) if k in ('open','high','low','close') else v for k,v in r.items()} for r in rows]
                for kind,event in items:
                    if kind=='market':mature_market(store,event,candles,now)
                    else:
                        mature(store,event,candles,now)
                        store.db.execute("UPDATE observations SET next_attempt_at=? WHERE id=? AND status='PENDING'",((stamp(now)+timedelta(minutes=30)).isoformat(),event['id']))
            # Link actual stages to persisted decisions/orders; eligibility is not a fill.
            actual = source.execute("SELECT d.decision_id,d.created_at,d.payload_json,o.order_id,o.status,o.position_id,o.filled_quantity,p.closed_at FROM trading_decisions d LEFT JOIN orders o ON o.decision_id=d.decision_id LEFT JOIN positions p ON p.position_id=o.position_id ORDER BY (o.order_id IS NOT NULL) DESC,d.created_at DESC LIMIT 1000").fetchall()
            for row in actual:
                decision=json.loads(row['payload_json'])
                actual_stage=('CLOSED_POSITION' if row['closed_at'] else 'FILLED_POSITION' if row['filled_quantity'] and row['filled_quantity']>0 else 'ORDER_REJECTED' if row['order_id'] and row['status'] in {'REJECTED','CANCELLED'} else 'ACCEPTED_PAPER_ORDER' if row['order_id'] else 'DECISION_REJECTED' if not decision.get('accepted') else 'ACCEPTED_DECISION')
                result={'decision_id':row['decision_id'],'signal_ids':decision.get('signal_ids',[]),
                        'stage':actual_stage,'order_id':row['order_id'],'order_status':row['status'],
                        'position_id':row['position_id'],'observed_at':row['created_at'].isoformat(),
                        'category':'ACTUAL_PRIMARY_PAPER_LEDGER','reason':decision.get('rejected_reason')}
                store.db.execute('INSERT INTO actual_events VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(row['decision_id'],canonical(result).decode()))
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
        run_training(store, now);train_market(store, now);publish(store, now)
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
