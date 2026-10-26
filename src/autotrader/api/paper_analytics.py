"""Read-only attribution, outside the frozen order-admission runtime."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from autotrader.api.dashboard import account_assets
from autotrader.api.trade_reports import linked_attribution, trade_reports
from autotrader.domain import utc_now
from autotrader.persistence.accounting import aware
from autotrader.persistence.models import OrderModel, PositionModel
from autotrader.research.data import canonical, digest

D = Decimal


async def attributed_summary(service: Any) -> dict[str, Any]:
    result: dict[str, Any] = await service.detail()
    repo = await service.repository()
    if repo is None:
        return result
    result.update(await account_assets(repo))
    async with repo.session_factory() as session:
        positions = (await session.scalars(select(PositionModel))).all()
        entries = (await session.scalars(select(OrderModel))).all()
        linked = await linked_attribution(session)
    result['trade_reports'] = await trade_reports(repo)
    origin=repo.manifest.get('account_origin',repo.manifest)
    def profile(evidence: dict[str,Any]) -> str:
        return str(evidence.get('execution_profile') or (origin['version'] if evidence.get('paper_manifest')==digest(canonical(origin)) else 'UNATTRIBUTED'))
    payloads = {o.position_id:json.loads(o.execution_json) for o in entries if o.position_id and o.side=='BUY'}
    order_payloads = {o.order_id:json.loads(o.execution_json) if o.side=='BUY' else payloads.get(o.position_id or '',{}) for o in entries}
    for order in result.get('orders',[]):
        evidence = order_payloads.get(order['order_id'],{}).get('strategy_evidence',{})
        order['execution_profile'] = profile(evidence)
        raw = order.get('strategy_id')
        model = next((o for o in entries if o.order_id==order['order_id']),None)
        order['raw_strategy_id'] = raw
        order['strategy_id'] = linked.get(model.position_id,raw) if model else raw
        order['attribution_corrected'] = order['strategy_id'] != raw
    by_order = {o.order_id:o for o in entries}
    for fill in result.get('fills',[]):
        order = by_order.get(fill['order_id'])
        if order:
            fill['strategy_id'] = linked.get(order.position_id, json.loads(order.execution_json).get('strategy_id'))
    grouped: dict[str, dict[str, list[Any]]] = {k:defaultdict(list) for k in ('asset','strategy','timeframe','regime','execution_profile')}
    for p in positions:
        payload = payloads.get(p.position_id,{})
        evidence = payload.get('strategy_evidence',{})
        keys = {'asset':p.symbol,'strategy':payload.get('strategy_id','UNKNOWN'),
            'timeframe':evidence.get('timeframe','UNKNOWN'),'regime':evidence.get('regime','UNKNOWN'),
            'execution_profile':profile(evidence)}
        for category,key in keys.items():grouped[category][key].append(p)
    groups = {}
    for category, buckets in grouped.items():
        rows=[]
        for key, samples in sorted(buckets.items()):
            closed=[p for p in samples if p.state=='CLOSED']
            pnl=sum((p.realized_pnl for p in closed),D(0))
            wins=[p.realized_pnl for p in closed if p.realized_pnl>0]
            losses=[p.realized_pnl for p in closed if p.realized_pnl<0]
            rows.append({'key':key,'open_positions':sum(p.state=='OPEN' for p in samples),
                'closed_positions':len(closed),'realized_closed_net_pnl':str(pnl),
                'win_rate':len(wins)/len(closed) if closed else None,
                'expectancy':str(pnl/len(closed)) if closed else None,
                'profit_factor':str(sum(wins)/-sum(losses)) if losses else None,
                'average_holding_seconds':sum((aware(p.closed_at)-aware(p.opened_at)).total_seconds() for p in closed)/len(closed) if closed else None})
        groups[category]=rows
    portfolio=result['portfolio']
    elapsed=(utc_now()-aware(datetime.fromisoformat(repo.manifest.get('account_origin',repo.manifest)['frozen_at']))).total_seconds()/86400
    result['attribution']=groups
    result['performance'].update(capital_utilization=str(D(portfolio['open_exposure'])/D(portfolio['equity'])) if portfolio['equity'] and portfolio['open_exposure'] and D(portfolio['equity'])>0 else None,
        closed_positions_per_day=result['performance']['closed_positions']/elapsed if elapsed>0 else None,
        age_days=elapsed,frequency_limit='Rate since experiment creation; unstable in short windows.')
    return result
