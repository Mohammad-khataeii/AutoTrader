"""Bounded, read-only trade gate dashboard routes."""
from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select

from autotrader.persistence import models as m
from autotrader.shadow import views
from autotrader.shadow.gates import aggregate
from autotrader.shadow.trace import STAGES, stage_states
from autotrader.shadow.trace import key as trace_key
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
            trace_rows = (await session.scalars(select(m.SystemStateModel).where(
                m.SystemStateModel.key.in_([trace_key(r['decision_id']) for r in page['items']])))).all()
            traces = {r.key: json.loads(r.payload_json) for r in trace_rows}
            order_rows = (await session.scalars(select(m.OrderModel).where(
                m.OrderModel.decision_id.in_([r['decision_id'] for r in page['items']])).order_by(m.OrderModel.created_at.desc()).limit(500))).all()
            incident_rows = (await session.scalars(select(m.SystemStateModel).where(
                m.SystemStateModel.key.in_(['shadow_runtime_incident', 'execution_trace_health']),
                m.SystemStateModel.state == 'ERROR'))).all()
        unannotated = sum(not r.get('explanation') for r in page['items'])
        rows = []
        for decision in page['items']:
            row = decision.get('explanation') or {
                'schema': 'unannotated-record/1', 'decision_id': decision['decision_id'],
                'symbol': decision['symbol'], 'action': decision['action'],
                'decision_accepted': decision['accepted'],
                'reason': decision['rejected_reason'] or 'Historical execution outcome not verified',
                'notes': 'Original decision has no structured explanation. Allocation evidence joined independently; execution remains unobserved.',
            }
            if decision['decision_id'] in allocations and decision['accepted'] and decision['action'] == 'BUY':
                advice = allocations[decision['decision_id']]
                row['allocation'] = {'reached': True, 'accepted': advice['accepted'], 'reason': advice.get('reasons')}
            decision['recorded_order_outcomes'] = [{'order_id': o.order_id, 'status': o.status, 'reason': json.loads(o.execution_json).get('rejection_reason'), 'created_at': o.created_at.isoformat(), 'evidence': 'DURABLE_ORDER_RECORD'} for o in order_rows if o.decision_id == decision['decision_id']]
            decision['explanation'] = row
            complete_trace = traces.get(trace_key(decision['decision_id']))
            decision['execution_trace'] = {**complete_trace, 'events': dict(list(complete_trace['events'].items())[:20]), 'total_events': len(complete_trace['events']), 'more_events': len(complete_trace['events']) > 20} if complete_trace else None
            decision['stage_states'] = stage_states(complete_trace)
            if row.get('schema') == 'shadow-decision-explanation/3':
                stages_now = decision['stage_states']
                preflight = stages_now['ENTRY_PREFLIGHT']
                row['opportunity']['pipeline'][-1] = {'stage': 'PAPER_EXECUTION',
                    'reached': preflight not in {'NOT_RECORDED', 'NEVER_REACHED'},
                    'passed': True if stages_now['ORDER_FILLED'] == 'SUCCEEDED' else False if preflight in {'REJECTED', 'EXCEPTION'} else None,
                    'reason': 'persisted_fill' if stages_now['ORDER_FILLED'] == 'SUCCEEDED' else row.get('execution', {}).get('reason') or preflight}
                if row.get('allocation', {}).get('reached') and not row['allocation'].get('accepted'):
                    row['opportunity']['pipeline'][-2] = {'stage': 'PORTFOLIO_RISK', 'reached': True, 'passed': False, 'reason': row['allocation'].get('reason')}
            if decision['stage_states']['ENTRY_PREFLIGHT'] not in {'NOT_RECORDED', 'NEVER_REACHED'}:
                row['trace_execution_state'] = decision['stage_states']['ENTRY_PREFLIGHT']
            if decision['execution_trace'] is None and decision['accepted'] and decision['action'] == 'BUY':
                decision['execution_evidence_status'] = 'Historical execution outcome not verified'
            rows.append(row)
        stages = {}
        for stage in STAGES:
            observed = [event for trace in traces.values() for event in trace['events'].values() if event['stage'] == stage]
            never_reached = sum(r['stage_states'][stage] == 'NEVER_REACHED' for r in page['items'])
            not_recorded = sum(r['stage_states'][stage] == 'NOT_RECORDED' for r in page['items'])
            stages[stage] = {
                'never_reached': never_reached, 'not_recorded': not_recorded,
                'succeeded': sum(e['status'] == 'SUCCEEDED' for e in observed) if observed else None,
                'rejected': sum(e['status'] == 'REJECTED' for e in observed) if observed else None,
                'outcome_unavailable': sum(e['status'] == 'ATTEMPTED' for e in observed) if observed else None,
                'exceptions': sum(e['status'] == 'EXCEPTION' for e in observed) if observed else None,
                'status': 'OBSERVED' if observed else 'NEVER_REACHED' if never_reached and not not_recorded else 'NOT_RECORDED',
            }
        def recent(predicate: Any) -> dict[str, Any] | None:
            item = next((r for r in page['items'] if predicate(r)), None)
            return {k: item[k] for k in ('decision_id', 'symbol', 'created_at')} | {'reason': item['explanation'].get('reason')} if item else None
        return {'account': identity, 'strategy_id': record['manifest']['strategy_id'],
                'state': record['state'], 'archived_at': record.get('archived_at'),
                'runtime_generation': compatibility(record['manifest'])['runner'],
                'runtime_compatibility': compatibility(record['manifest']),
                'window': {'limit': limit, 'as_of': page['as_of'], 'unannotated': unannotated},
                **aggregate(rows), 'lifetime_financial_counts': counts,
                'qualification_counts': {
                    'technical': sum(r.get('technical_eligible') is True for r in rows) if any('technical_eligible' in r for r in rows) else None,
                    'economic': sum(r.get('economic_eligible') is True for r in rows) if any('economic_eligible' in r for r in rows) else None},
                'execution_stages': stages,
                'runtime_incidents': [{'reason': r.reason, 'detail': json.loads(r.payload_json)} for r in incident_rows],
                'recent_in_window': {
                    'eligible': recent(lambda r: r['explanation'].get('signal_entry_eligible') is True),
                    'accepted_buy': recent(lambda r: r['accepted'] and r['action'] == 'BUY'),
                    'refusal': recent(lambda r: r['explanation'].get('final_state') == 'REJECTED' and r['explanation'].get('execution', {}).get('stage') == 'entry'),
                },
                'last_scan_observation': json.loads(scan.payload_json) if scan else None,
                'safety': (await views.account_summary(repo))['reconciliation_status'],
                'decisions': page['items'], 'next_cursor': page['next_cursor'], 'read_only': True}


    @app.get('/api/trade-gates/{identity}/traces/{decision_id}', dependencies=[Depends(require_user)])
    async def execution_trace(identity: str, decision_id: str,
                              limit: int = Query(50, ge=1, le=50),
                              cursor: int = Query(0, ge=0, le=1000000)) -> dict[str, Any]:
        if len(decision_id) > 64:
            raise HTTPException(422, detail='invalid_decision_id')
        if not any(r['experiment_id'] == identity for r in await lab.records()):
            raise HTTPException(404, detail='unknown_shadow_experiment')
        repo = await lab.repository(identity)
        async with repo.session_factory() as session:
            row = await session.get(m.SystemStateModel, trace_key(decision_id))
        if row is None:
            raise HTTPException(404, detail='execution_trace_not_recorded')
        body = json.loads(row.payload_json)
        events = list(body.pop('events').values())
        return {**body, 'events': events[cursor:cursor+limit], 'total': len(events),
                'next_cursor': cursor+limit if cursor+limit < len(events) else None, 'read_only': True}
