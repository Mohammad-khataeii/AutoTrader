"""Bounded, read-only trade gate dashboard routes."""
from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select

from autotrader.persistence import models as m
from autotrader.shadow import views
from autotrader.shadow.gates import aggregate
from autotrader.shadow.versions import compatibility


def install(app: FastAPI, repository: Any, lab: Any, require_user: Any) -> None:
    @app.get('/api/trade-gates/{identity}', dependencies=[Depends(require_user)])
    async def trade_gates(identity: str, limit: int = Query(100, ge=1, le=100),
                          cursor: str | None = Query(None, max_length=2048)) -> dict[str, Any]:
        record = next((r for r in await lab.records() if r['experiment_id'] == identity), None)
        if record is None:
            raise HTTPException(404, detail='unknown_shadow_experiment')
        repo = await lab.repository(identity)
        try:
            page = await views.page(repo, 'decisions', limit, cursor)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from None
        async with repo.session_factory() as session:
            counts = {name: await session.scalar(select(func.count()).select_from(model))
                      for name, model in (('paper_fills', m.FillModel), ('orders', m.OrderModel))}
            counts['open_positions'] = await session.scalar(select(func.count()).select_from(m.PositionModel).where(m.PositionModel.quantity > 0))
            counts['closed_positions'] = await session.scalar(select(func.count()).select_from(m.PositionModel).where(m.PositionModel.closed_at.is_not(None)))
            scan = await session.get(m.SystemStateModel, 'shadow_scan_observation')
            allocation_rows = (await session.scalars(select(m.SystemStateModel).where(
                m.SystemStateModel.key.in_(['alloc:' + r['decision_id'] for r in page['items']])))).all()
            allocations = {r.key.removeprefix('alloc:'): json.loads(r.payload_json) for r in allocation_rows}
        unannotated = sum(not r.get('explanation') for r in page['items'])
        rows = []
        for decision in page['items']:
            row = decision.get('explanation') or {
                'schema': 'unannotated-record/1', 'decision_id': decision['decision_id'],
                'symbol': decision['symbol'], 'action': decision['action'],
                'decision_accepted': decision['accepted'],
                'reason': decision['rejected_reason'] or 'Accepted decision; execution outcome unrecorded',
                'notes': 'Original decision has no structured explanation. Allocation evidence joined independently; execution remains unobserved.',
            }
            if decision['decision_id'] in allocations and decision['accepted'] and decision['action'] == 'BUY':
                advice = allocations[decision['decision_id']]
                row['allocation'] = {'reached': True, 'accepted': advice['accepted'], 'reason': advice.get('reasons')}
            decision['explanation'] = row
            rows.append(row)
        return {'account': identity, 'strategy_id': record['manifest']['strategy_id'],
                'state': record['state'], 'runtime_compatibility': compatibility(record['manifest']),
                'window': {'limit': limit, 'as_of': page['as_of'], 'unannotated': unannotated},
                **aggregate(rows), 'lifetime_financial_counts': counts,
                'last_scan_observation': json.loads(scan.payload_json) if scan else None,
                'safety': (await views.account_summary(repo))['reconciliation_status'],
                'decisions': page['items'], 'next_cursor': page['next_cursor'], 'read_only': True}
