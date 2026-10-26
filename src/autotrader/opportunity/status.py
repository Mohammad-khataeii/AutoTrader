"""Research cadence, executable prices and process health are independent facts."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from autotrader.persistence.accounting import aware


def timestamp(value: Any) -> datetime | None:
    try:
        return aware(datetime.fromisoformat(str(value)))
    except (ValueError, TypeError):
        return None


def freshness(body: dict[str, Any], state: str, updated: datetime | None,
              health: dict[str, Any], now: datetime) -> dict[str, Any]:
    cadence = int(body.get('evaluation_interval_seconds', 300))
    cadence = cadence if 60 <= cadence <= 3600 else 300
    grace = int(body.get('evaluation_grace_seconds', 90))
    grace = max(15, min(grace, 300))
    observed = timestamp(body.get('updated_at')) or (aware(updated) if updated else None)
    age = (now-observed).total_seconds() if observed else None
    bucket = body.get('cycle_bucket')
    due = datetime.fromtimestamp((int(bucket)+1)*cadence+grace, UTC) if isinstance(bucket, int) else None
    valid = observed is not None and age is not None and age >= -5 and due is not None and now <= due and isinstance(bucket, int) and bucket <= int(now.timestamp())//cadence and int(observed.timestamp())//cadence in {bucket,bucket+1}
    research_state = ('FAILED' if state == 'ERROR' else 'NOT_RECORDED' if observed is None
                      else 'INVALID_TIMESTAMP' if age is not None and age < -5
                      else 'DELAYED' if not valid else 'PARTIAL' if state == 'DEGRADED'
                      else 'WAITING_NEXT_CANDLE' if int(now.timestamp())//cadence > int(bucket or 0) else 'CURRENT')
    instance = health.get('worker_instance')
    worker = health.get('worker')
    # worker_instance records startup, not a periodic heartbeat. Prefer the
    # newest observation so a healthy long-running worker never ages from boot.
    if instance is not None and (worker is None or aware(instance.updated_at) > aware(worker.updated_at)):
        worker = instance
    scan = health.get('scanner')
    operation = health.get('operation')
    def observation(row: Any, threshold: int) -> dict[str, Any]:
        if row is None:
            return {'state': 'UNKNOWN', 'age_seconds': None, 'reason': 'No persisted health observation'}
        seconds = (now-aware(row.updated_at)).total_seconds()
        payload = json.loads(row.payload_json)
        failed = row.state in {'ERROR','FAILED','SYSTEM_ERROR','RECOVERY_REQUIRED','DATA_UNAVAILABLE'}
        result = 'INVALID_TIMESTAMP' if seconds < -5 else 'FAILED' if failed else 'DEGRADED' if payload.get('provider_errors') else 'DELAYED' if seconds > threshold else 'HEALTHY'
        return {'state': result, 'reported_state': row.state, 'age_seconds': max(0, seconds),
                'reason': row.reason, 'process_id': payload.get('process_id')}
    worker_state = observation(worker, max(90, grace*2))
    scan_state = observation(scan, cadence+grace)
    if operation is not None and operation.state in {'INITIALIZING','DATA_SYNCING','RECOVERY_REQUIRED','SYSTEM_ERROR'}:
        op_age = (now-aware(operation.updated_at)).total_seconds()
        if -5 <= op_age < cadence+grace:
            worker_state['state'] = 'FAILED' if operation.state == 'SYSTEM_ERROR' else 'RECOVERING'
            worker_state['reason'] = operation.reason
    source_pid = body.get('observer_process_id')
    # Container processes commonly restart with PID 1 again. The persisted
    # startup timestamp distinguishes that restart from the prior observation.
    restarted = instance is not None and observed is not None and observed < aware(instance.updated_at) <= now
    changed_pid = source_pid and worker_state.get('process_id') and source_pid != worker_state['process_id']
    if (restarted or changed_pid) and worker_state['state']=='HEALTHY':
        worker_state.update(state='RECOVERING', reason='Worker restarted; prior research remains historical evidence')
    quote_times = [timestamp(r.get('quote_observed_at')) for r in body.get('rows', [])]
    quote_ages = [(now-t).total_seconds() for t in quote_times if t is not None]
    quotes_current = bool(quote_ages) and len(quote_ages)==len(quote_times) and all(-5<=a<=90 for a in quote_ages)
    return {'research_freshness': {'state': research_state, 'current': valid and state!='ERROR',
                'observed_at': observed.isoformat() if observed else None, 'age_seconds': max(0, age) if age is not None else None,
                'next_evaluation_due_at': due.isoformat() if due else None, 'interval_seconds': cadence, 'grace_seconds': grace},
            'market_freshness': {'state': 'RECENT_OBSERVATION' if quotes_current else 'STALE_QUOTES' if quote_ages else 'NOT_RECORDED',
                'oldest_quote_age_seconds': max(quote_ages) if quote_ages else None,
                'execution_authorized': False, 'reason': 'Every order requires a new executable book and current account admission'},
            'worker_health': worker_state, 'scanner_health': scan_state}


def qualification(evidence: dict[str, Any], *, fill_count: int | None = None,
                  execution_rejected: bool = False, paper_admission_verified: bool = False) -> str:
    if fill_count is not None and fill_count>0:
        return 'EXECUTED_IN_SIMULATION'
    if execution_rejected:
        return 'REJECTED'
    if paper_admission_verified:
        return 'PAPER_ELIGIBLE'
    pipeline = evidence.get('pipeline') or []
    if evidence.get('data_errors') or (pipeline and pipeline[0].get('stage')=='DATA_VALIDATION' and pipeline[0].get('passed') is False):
        return 'TECHNICAL_CANDIDATE' if evidence.get('technical_eligible') else 'DATA_UNAVAILABLE'
    if evidence.get('technical_eligible') is not True:
        return 'WATCH'
    economics = evidence.get('economics') or {}
    if not economics.get('measurements',{}).get('estimates_available'):
        return 'TECHNICAL_CANDIDATE'
    return 'RESEARCH_CANDIDATE' if evidence.get('economic_eligible') else 'COST_CONSTRAINED'
