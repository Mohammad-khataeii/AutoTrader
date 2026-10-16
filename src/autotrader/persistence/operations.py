"""Durable coordinator ownership and explicit operational states, separate from P&L."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any

from autotrader.domain import new_id, utc_now
from autotrader.persistence.accounting import aware
from autotrader.persistence.ai_budget import quota_now
from autotrader.persistence.models import SystemIncidentModel, SystemStateModel

STATES={'INITIALIZING','DATA_SYNCING','RESEARCH_ONLY','PAPER_READY','PAPER_TRADING',
    'ENTRY_SUSPENDED','RISK_HALTED','DATA_DEGRADED','RECOVERY_REQUIRED','SYSTEM_ERROR'}


class LeaseLostError(RuntimeError):
    pass


async def verify_worker_lease(session: Any, owner: str | None) -> None:
    if owner is None:
        return  # Authenticated API / isolated service tests have independent entry gates.
    row=await session.get(SystemStateModel,'coordinator_lease')
    payload=json.loads(row.payload_json) if row else {}
    now=await quota_now(session)
    if payload.get('owner')!=owner or aware(datetime.fromisoformat(payload['expires_at']))<=now:
        raise LeaseLostError('Worker ownership expired; economic mutation refused.')


class OperationsMixin:
    session_factory: Any
    _lock_account: Any
    worker_owner_id: str | None = None

    async def authentication_attempt(self, client: str, *, failed: bool = False) -> int | None:
        key='auth:'+sha256(client.encode()).hexdigest()[:54]
        async with self.session_factory() as session,session.begin():
            await self._lock_account(session)
            now=(await quota_now(session)).timestamp()
            row=await session.get(SystemStateModel,key)
            events=[t for t in json.loads(row.payload_json).get('failures',[]) if t>now-60] if row else []
            if len(events)>=5:
                return int(max(1,math.ceil(events[0]+60-now)))
            if failed:
                events.append(now)
                if row:
                    row.payload_json=json.dumps({'failures':events})
                else:
                    session.add(SystemStateModel(key=key,state='AUTH_THROTTLE',reason='shared_login_failures',payload_json=json.dumps({'failures':events})))
            return None

    async def claim_coordinator(self, owner: str, *, seconds: int = 15) -> bool:
        async with self.session_factory() as session,session.begin():
            await self._lock_account(session)
            now=await quota_now(session)
            row=await session.get(SystemStateModel,'coordinator_lease')
            payload=json.loads(row.payload_json) if row else {}
            if payload.get('owner') not in {None,owner} and aware(datetime.fromisoformat(payload['expires_at']))>now:
                return False
            encoded=json.dumps({'owner':owner,'heartbeat':now.isoformat(),'expires_at':(now+timedelta(seconds=seconds)).isoformat()})
            if row:
                row.payload_json,row.state=encoded,'OWNED'
            else:
                session.add(SystemStateModel(key='coordinator_lease',state='OWNED',reason='single_active_coordinator',payload_json=encoded))
            self.worker_owner_id=owner
            return True

    async def release_coordinator(self, owner: str) -> None:
        async with self.session_factory() as session,session.begin():
            await self._lock_account(session)
            row=await session.get(SystemStateModel,'coordinator_lease')
            if row and json.loads(row.payload_json).get('owner')==owner:
                row.state='RELEASED'
                row.payload_json=json.dumps({'owner':None,'expires_at':utc_now().isoformat()})

    async def operation_state(self, state: str, reason: str, payload: dict[str, Any] | None = None) -> None:
        if state not in STATES:
            raise ValueError('Unknown operational state.')
        async with self.session_factory() as session,session.begin():
            await self._lock_account(session)
            row=await session.get(SystemStateModel,'operation')
            changed=row is None or row.state!=state or row.reason!=reason
            encoded=json.dumps({'observed_at':utc_now().isoformat(),**(payload or {})},default=str)
            if row:
                row.state,row.reason,row.payload_json=state,reason,encoded
            else:
                session.add(SystemStateModel(key='operation',state=state,reason=reason,payload_json=encoded))
            if changed:
                session.add(SystemIncidentModel(incident_id=new_id('operation'),severity='ERROR' if state=='SYSTEM_ERROR' else 'WARNING' if state in {'DATA_DEGRADED','RECOVERY_REQUIRED'} else 'INFO',
                    status=state,message=reason,payload_json=encoded))
