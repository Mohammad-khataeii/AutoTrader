"""Conservative batch accelerator for StocksWatch's existing resumable history queue.

No broker order routes. All job state and bar writes occur in one SQLite transaction.
If a provider page is truncated or any verification fails, fall back to the
original single-symbol journaled path; never mark an incomplete batch complete.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from . import backfill, storage
from .universe import REGISTRY
from .intraday_market import ObservationError
from .sessions import completed_day

# Keep the combined monthly daily payload below Alpaca's aggregate page limit.
MAX_DAILY_SYMBOLS = 20
MAX_MINUTE_SYMBOLS = 2


def interval_seconds():
    """Limit aggregate background frequency; provider GET itself has retry delays."""
    try:
        value = int(os.getenv("STOCKSWATCH_HISTORY_INTERVAL_SECONDS", "12"))
    except ValueError:
        return 12
    return max(8, min(120, value))


def _latest_window_cutoff(now):
    # A conservative 390 calendar days normally covers more than 201 XNYS
    # sessions. Old archives remain queued at lower priority.
    return (date.fromisoformat(completed_day(now)) - timedelta(days=390)).isoformat()


def _pending_group(now):
    cutoff = _latest_window_cutoff(now)
    # Prioritize the EOD readiness window, then recent intraday, then old
    # research. Preserve active/retry pagination ahead of new work.
    with storage.connect() as c:
        ongoing = c.execute("""SELECT EXISTS(SELECT 1 FROM sw_history_jobs
             WHERE state IN ('RUNNING','RETRY') AND (state='RUNNING' OR
               updated_at IS NULL OR updated_at<?))""",
             ((now - timedelta(minutes=5)).isoformat(),)).fetchone()[0]
        if ongoing:
            return None
        anchor = c.execute("""SELECT timeframe,feed,adjustment,first_at,end_at
            FROM sw_history_jobs WHERE state='PENDING'
            ORDER BY CASE WHEN timeframe='1Day' AND substr(end_at,1,10)>=? THEN 0
                          WHEN timeframe='1Min' THEN 1 ELSE 2 END,
                     end_at DESC,symbol LIMIT 1""", (cutoff,)).fetchone()
        if not anchor:
            return []
        timeframe, feed, adjustment, start, end = tuple(anchor)
        limit = MAX_DAILY_SYMBOLS if timeframe == '1Day' else MAX_MINUTE_SYMBOLS
        jobs = c.execute("""SELECT * FROM sw_history_jobs WHERE state='PENDING'
              AND timeframe=? AND feed=? AND adjustment=? AND first_at=? AND end_at=?
              ORDER BY symbol LIMIT ?""", (timeframe,feed,adjustment,start,end,limit)).fetchall()
        return [dict(row) for row in jobs]


def _group_fetch(data, now, jobs):
    if len(jobs) < 2:
        return False
    seed = jobs[0]
    symbols = [j['symbol'] for j in jobs]
    from .sessions import instant, NY
    start, end = instant(seed['first_at']), instant(seed['end_at'])
    page, token = data.bar_page(symbols,seed['feed'],start,end,seed['timeframe'],seed['adjustment'])
    # Provider pages cap rows across all symbols. Never finalize a partial page.
    # The existing single-symbol worker has durable page tokens and retries.
    if token:
        return False
    accepted = {}
    for job in jobs:
        accepted[job['symbol']] = backfill._bars(job,page.get(job['symbol'],[]),now)
    actions = {}
    if seed['timeframe']=='1Day':
        first = start.astimezone(NY).date().isoformat()
        last = (end.astimezone(NY).date() - timedelta(days=1)).isoformat()
        # Obtain all corporate-action evidence before modifying job state.
        for symbol in symbols:
            actions[symbol] = data.corporate_actions(symbol,first,last)
    # Race protection: never overwrite a job that another worker has started.
    with storage.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for job in jobs:
            matches = c.execute("""SELECT token,state,last_bar FROM sw_history_jobs
                   WHERE symbol=? AND timeframe=? AND feed=? AND adjustment=?
                     AND first_at=? AND end_at=?""",
                   tuple(job[k] for k in backfill.KEY)).fetchone()
            if not matches or tuple(matches)!=(None,'PENDING',None):
                c.rollback()
                return False
        for job in jobs:
            symbol = job['symbol']
            c.executemany('INSERT OR IGNORE INTO sw_historical_bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', accepted[symbol])
            c.executemany('INSERT OR IGNORE INTO sw_history_actions VALUES(?,?,?,?)',
                          [(symbol,a['day'],a['kind'],now.isoformat()) for a in actions.get(symbol,())])
            c.execute("""UPDATE sw_history_jobs SET token=NULL,last_bar=?,state='COMPLETE',
                       updated_at=?,error=NULL,attempts=0
                       WHERE symbol=? AND timeframe=? AND feed=? AND adjustment=?
                         AND first_at=? AND end_at=? AND state='PENDING'""",
                      (accepted[symbol][-1][4] if accepted[symbol] else None,
                       now.isoformat(),*tuple(job[k] for k in backfill.KEY)))
            if c.execute('SELECT changes()').fetchone()[0]!=1:
                c.rollback()
                return False
        c.commit()
    return True


def step(data, now):
    """One bounded batch/page; returns False only when there is no work."""
    group = _pending_group(now)
    if group is None or (group and len(group)<2):
        return backfill.step(data,now)
    if not group:
        return False
    try:
        if _group_fetch(data,now,group):
            return True
    except (ObservationError,KeyError,TypeError,ValueError):
        # Unverified corporate actions, malformed provider response, or a
        # rate limit cannot be recorded as a completed group.
        pass
    return backfill.step(data,now)

def progress_summary():
    """Read-only progress for the authenticated frontend; never blends legacy and archive counts."""
    from datetime import timezone
    now = datetime.now(timezone.utc)
    groups = storage.rows("""SELECT timeframe,feed,state,COUNT(*) AS jobs
         FROM sw_history_jobs GROUP BY timeframe,feed,state
         ORDER BY timeframe,feed,state""")
    archived = storage.rows("""SELECT timeframe,feed,COUNT(*) AS bars,
         COUNT(DISTINCT symbol) AS symbols FROM sw_historical_bars
         GROUP BY timeframe,feed ORDER BY timeframe,feed""")
    states = {}
    for group in groups:
        states[group['state']] = states.get(group['state'], 0) + group['jobs']
    total = sum(states.values())
    recent = storage.one("""SELECT MAX(updated_at) AS at FROM sw_history_jobs
         WHERE updated_at IS NOT NULL""") or {}
    errors = storage.rows("""SELECT symbol,timeframe,feed,error,attempts
         FROM sw_history_jobs WHERE state='ERROR' ORDER BY updated_at DESC LIMIT 12""")
    verify = storage.one("""SELECT COUNT(*) AS n FROM sw_asset_verification
         WHERE json_extract(evidence,'$.verified')=1""") or {}
    return {
        'as_of': now.isoformat(),
        'universe': len(REGISTRY),
        'jobs_total': total,
        'jobs_completed': states.get('COMPLETE',0),
        'jobs_pending': states.get('PENDING',0),
        'jobs_running': states.get('RUNNING',0),
        'jobs_retry': states.get('RETRY',0),
        'jobs_error': states.get('ERROR',0),
        'job_breakdown': groups,
        'historical_archive': archived,
        'verified_assets': verify.get('n',0),
        'last_job_activity': recent.get('at'),
        'recent_errors': errors,
        'worker_interval_seconds': interval_seconds(),
        'read_only': True,
        'note': 'New historical archive only; legacy EOD bars are tracked separately',
    }
