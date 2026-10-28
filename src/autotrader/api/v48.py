"""Authenticated opportunity intelligence. Reads never advance experiments."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from fastapi import Depends, FastAPI, Query
from sqlalchemy import select

from autotrader.domain import utc_now
from autotrader.persistence.accounting import aware
from autotrader.persistence.models import FillModel, OrderModel, PositionModel, SystemStateModel
from autotrader.raoe.analytics import episodes


def execution_stages(pipeline: list[dict[str,Any]], orders: list[Any], filled_orders: set[str], closed: set[str]) -> list[dict[str,Any]]:
    projected=[dict(stage) for stage in pipeline]
    has_fill=any(o.order_id in filled_orders for o in orders)
    admitted=[o for o in orders if o.status!='REJECTED']
    fill_passed=True if has_fill else None if any(o.status in {'PENDING','ACCEPTED'} for o in admitted) else False
    observations=[(7,bool(orders),bool(admitted)),(8,bool(admitted),fill_passed),
        (9,has_fill,True if any(o.position_id in closed for o in orders) else None)]
    for index,reached,passed in observations:
        projected[index].update(reached=reached,passed=passed if reached else None,
            state='NOT_REACHED' if not reached else 'UNKNOWN' if passed is None else 'PASSED' if passed else 'FAILED')
    return projected


def install(app: FastAPI, service: Any, lab: Any, require_user: Any) -> None:
    @app.get('/api/intelligence',dependencies=[Depends(require_user)])
    async def intelligence(limit: int = Query(30,ge=1,le=100), cursor: int = Query(0,ge=0,le=100000)) -> dict[str, Any]:
        repo=await service.repository()
        if not repo: return {'status':'NOT_INITIALIZED','rows':[],'read_only':True}
        async with service.official.session_factory() as session:
            row=await session.get(SystemStateModel,'raoe_discovery')
            discovery=json.loads(row.payload_json) if row else {}
            states=(await session.scalars(select(SystemStateModel).where(SystemStateModel.key.in_(['benchmark_sync','market_metrics','scanner','worker','worker_instance'])))).all()
            runtime={r.key:{'updated_at':aware(r.updated_at).isoformat(),'state':r.state,'payload':json.loads(r.payload_json)} for r in states}
        async with repo.session_factory() as session:
            row=await session.get(SystemStateModel,'paper_scan')
            scan=json.loads(row.payload_json) if row else {}
            events=(await session.scalars(select(SystemStateModel).where(SystemStateModel.key.like('raoe_event:%'))
                .order_by(SystemStateModel.created_at.desc()).offset(cursor).limit(limit))).all()
            outcomes=(await session.scalars(select(SystemStateModel).where(SystemStateModel.key.in_(
                ['raoe49_outcome:'+r.key.removeprefix('raoe_event:') for r in events])))).all()
            episode_models=(await session.scalars(select(SystemStateModel).where(SystemStateModel.key.like('raoe_event:%'),SystemStateModel.created_at>=utc_now()-timedelta(hours=48)).order_by(SystemStateModel.created_at).limit(10000))).all()
            orders=(await session.scalars(select(OrderModel).order_by(OrderModel.created_at.desc()).limit(500))).all()
            fills=(await session.scalars(select(FillModel).order_by(FillModel.created_at.desc()).limit(500))).all()
            closed=set((await session.scalars(select(PositionModel.position_id).where(PositionModel.state=='CLOSED'))).all())
        age=(utc_now()-aware(datetime.fromisoformat(scan['observed_at']))).total_seconds() if scan.get('observed_at') else None
        fresh=age is not None and 0<=age<=180
        summaries_by_symbol={r['symbol']:r for r in discovery.get('rows',[])}
        payloads={o.order_id:json.loads(o.execution_json) for o in orders}
        filled_orders={f.order_id for f in fills}
        rows=[]
        for observation in scan.get('rows',[]):
            if not observation['strategy_id'].startswith('RAOE_'): continue
            row=dict(observation)
            ticker=summaries_by_symbol.get(row['symbol'],{})
            row.update(market_price=ticker.get('price'),movement_since_summary=ticker.get('movement_since_summary'),
                spread_bps=ticker.get('spread_bps'),quote_volume_24h=ticker.get('quote_volume_24h'),
                relative_return_30m=(row.get('raoe_regime') or {}).get('relative_return_30m'),
                completed_return_30m=ticker.get('completed_return_30m'),short_window_source=ticker.get('short_window_source'),
                execution_depth=(row.get('raoe_regime') or {}).get('near_liquidity'))
            matches=[o for o in orders if o.symbol==row['symbol'] and payloads[o.order_id].get('strategy_id')==row['strategy_id']
                and payloads[o.order_id].get('strategy_evidence',{}).get('as_of')==row.get('as_of')
                and payloads[o.order_id].get('strategy_evidence',{}).get('execution_profile')==repo.manifest['version']]
            row['pipeline']=execution_stages(row['pipeline'],matches,filled_orders,closed)
            row['status']='STALE' if not fresh else 'READY' if row.get('entry_eligible') else 'REJECTED' if row.get('technical') else 'WATCHING'
            if fresh and matches:
                row['status']='CLOSED' if any(o.position_id in closed for o in matches) else 'OPEN_PAPER_POSITION' if any(o.order_id in filled_orders for o in matches) else 'REJECTED_AT_BROKER' if all(o.status=='REJECTED' for o in matches) else 'PAPER_ORDER_PENDING'
            elif fresh and row['pipeline'][6].get('state')=='FAILED':row['status']='REJECTED_PORTFOLIO_RISK'
            rows.append(row)
        watched={r['symbol'] for r in rows}
        summaries=[{**r,'status':'STALE' if not discovery.get('observed_at') or (utc_now()-aware(datetime.fromisoformat(discovery['observed_at']))).total_seconds()>180 else r['status']} for r in discovery.get('rows',[]) if r['symbol'] not in watched]
        mapped={r['event_id']:r for r in [json.loads(o.payload_json) for o in outcomes]}
        missed=[]
        for event in events:
            b=json.loads(event.payload_json)
            decision_orders=[o for o in orders if o.decision_id==b['decision_id']]
            b['evidence']['pipeline']=execution_stages(b['evidence']['pipeline'],decision_orders,filled_orders,closed)
            outcome=mapped.get(b['event_id'],{'classification':'PENDING_FIXED_HORIZON','profitability_proven':False})
            actual=[f for f in fills if any(o.order_id==f.order_id for o in decision_orders)]
            outcome['actual_prospective_paper_trade']={'status':'FILLED' if actual else 'NO_FILL_IN_RECENT_LEDGER_WINDOW',
                'order_count':len(decision_orders),'fill_count':len(actual),'scope':'Latest 500 orders and fills; full history available in experiment detail/export'}
            missed.append({**b,'outcome':outcome})
        return {'status':'CURRENT' if fresh else 'STALE_OR_UNAVAILABLE','observed_at':scan.get('observed_at'),
            'rows':sorted(rows,key=lambda r:(not r.get('entry_eligible'),not r.get('technical'),r['symbol'])),
            'unscanned_or_excluded':summaries,'discovery':discovery,'missed':missed,
            'episodes':episodes([json.loads(e.payload_json) for e in episode_models]),
            'episode_scope':{'hours':48,'signals':len(episode_models),'possibly_truncated':len(episode_models)==10000},
            'runtime_diagnostics':runtime,'benchmark_sync':scan.get('benchmark_sync'),
            'next_cursor':cursor+limit if len(events)==limit else None,'data_failures':scan.get('data_failures',[]),
            'estimated_edge':'UNKNOWN','read_only':True,'live_authorized':False}

    @app.get('/api/intelligence/competition',dependencies=[Depends(require_user)])
    async def competition() -> dict[str,Any]:
        primary=await service.detail()
        experiments=[]
        for record in await lab.records():
            if record['state']=='CREATING': continue
            detail=await lab.detail(record['experiment_id'])
            scoped=await lab.repository(record['experiment_id'])
            async with scoped.session_factory() as session:
                models=(await session.scalars(select(OrderModel))).all()
            books={o.order_id:json.loads(o.execution_json).get('book',{}) for o in models}
            impact=Decimal(0)
            for fill in detail['fills']:
                levels=books.get(fill['order_id'],{}).get('asks' if fill['side']=='BUY' else 'bids',[])
                if levels:
                    top=Decimal(levels[0][0]);price=Decimal(fill['price']);q=Decimal(fill['quantity'])
                    impact+=q*(price-top if fill['side']=='BUY' else top-price)
            closed_positions=[p for p in detail['positions'] if p['closed_at'] is not None]
            durations=[(aware(p['closed_at'])-aware(p['opened_at'])).total_seconds() for p in closed_positions]
            detail['performance'].update(win_count=sum(p['realized_pnl']>0 for p in closed_positions),
                loss_count=sum(p['realized_pnl']<0 for p in closed_positions),
                median_holding_seconds=median(durations) if durations else None,
                modeled_slippage_and_impact_eur=str(impact),exposure_eur=detail['portfolio'].get('open_exposure'))
            experiments.append({'experiment_id':record['experiment_id'],'strategy_id':record['manifest']['strategy_id'],
                'version':record['manifest']['strategy_version'],'archived_at':record.get('archived_at'),
                'exit_policy':record['manifest'].get('exit_policy',{'status':'LEGACY_UNBOUND_SEE_ORIGINAL_ORDERS'}),
                'forward_evidence_seconds':max(0,(utc_now()-aware(datetime.fromisoformat(record['created_at']))).total_seconds()),
                'orders':len(models),'fills':len(detail['fills']),'fills_scope':'Latest 500',
                'rejection_reasons':dict(Counter(json.loads(o.execution_json).get('rejection_reason','UNKNOWN') for o in models if o.status=='REJECTED')),
                'evidence_category':record['manifest']['data_kind'],
                'portfolio':detail['portfolio'],'performance':detail['performance'],
                'confidence':'INSUFFICIENT_INDEPENDENT_EVIDENCE','runtime_compatibility':detail['runtime_compatibility'],
                'reconciliation':detail['reconciliation']})
        path=Path('/app/evidence/v49/research-results.json')
        if not path.is_file(): path=Path(__file__).parents[3]/'docs/evidence/v4_9/research-results.json'
        return {'primary_strategies':primary.get('strategies',[]),'experiments':experiments,
            'historical':json.loads(path.read_text()) if path.is_file() else {'status':'NOT_PUBLISHED'},
            'allocation':'One primary cash pool; experimental EUR500 ledgers are separate and never added to primary equity',
            'estimated_edge':'UNKNOWN','automatic_promotion':False,'read_only':True}
