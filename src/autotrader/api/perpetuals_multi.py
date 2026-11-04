"""Authenticated views/control of separate, virtual multi-coin experiments."""
from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, StrictBool
from sqlalchemy import select
from autotrader.perpetuals.multi.models import MultiEvent
from autotrader.perpetuals.market import clock_ms

from autotrader.config import Settings
from autotrader.perpetuals.multi.ledger import MultiLedger,Refused
from autotrader.perpetuals.multi.policy import encode
from autotrader.perpetuals.service import available,flag
import json


class MultiControl(BaseModel):
    enabled: StrictBool


def install(app: FastAPI, ledger: MultiLedger, settings: Settings, require_user: Callable[...,Any]) -> None:
    def enabled():return available(settings) and flag('PAPER_MULTI_PERPETUALS_ENABLED')

    @app.get('/api/perpetuals/multi',dependencies=[Depends(require_user)])
    async def snapshot():
        body=await ledger.snapshot()
        body.update(feature_enabled=enabled(),paper_only=True,real_orders_enabled=False)
        return json.loads(encode(body))

    @app.get('/api/perpetuals/multi/history',dependencies=[Depends(require_user)])
    async def history(cursor: int | None = Query(None,ge=1), limit: int = Query(30,ge=1,le=100), kind: str | None = None):
        if not await ledger.provisioned():return {'rows':[],'next_cursor':None}
        query=select(MultiEvent).order_by(MultiEvent.id.desc()).limit(limit+1)
        if cursor is not None:query=query.where(MultiEvent.id<cursor)
        if kind:query=query.where(MultiEvent.kind==kind)
        async with ledger.factory() as session:rows=(await session.scalars(query)).all()
        return {'rows':[{'id':row.id,**json.loads(row.payload)} for row in rows[:limit]],
                'next_cursor':rows[limit-1].id if len(rows)>limit else None}

    @app.post('/api/perpetuals/multi/entries',dependencies=[Depends(require_user)])
    async def entries(request: MultiControl):
        if not enabled():raise HTTPException(409,'Multi-coin paper feature is disabled')
        try:
            if not await ledger.provisioned():raise Refused('Separate multi-coin schema is not provisioned')
            if request.enabled:
                state=await ledger.snapshot()
                if (not state.get('scan_fresh') or not state.get('monitor') or state['monitor'].get('errors')
                        or not 0<=clock_ms()-state['monitor']['at']<=15000):
                    raise Refused('Fresh complete scan and healthy protective monitor required')
            await ledger.control(request.enabled)
        except Refused as error:raise HTTPException(409,str(error)) from None
        return {'entries_enabled':request.enabled,'paper_only':True}
