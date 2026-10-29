"""Linked read-only position explanations. Executed records are never relabeled in storage."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text

from autotrader.persistence.accounting import aware
from autotrader.persistence.models import (
    ExitIntentModel,
    ExitPlanModel,
    ExitTargetModel,
    FillModel,
    JournalEventModel,
    OrderModel,
    PositionModel,
    SystemStateModel,
)

D = Decimal


def explain_position(p: Any, plan: Any, orders: list[Any], fills: list[Any],
                     targets: list[Any], intents: list[Any], journal: list[Any], assessments: list[dict[str, Any]]) -> dict[str, Any]:
    orders = sorted(orders, key=lambda o:(o.created_at,o.order_id))
    buys = [o for o in orders if o.side=='BUY' and o.filled_quantity>0]
    entry = json.loads(buys[0].execution_json) if buys else {}
    evidence = entry.get('strategy_evidence', {})
    strategy = plan.strategy_id if plan else entry.get('strategy_id','UNATTRIBUTED')
    fees = sum((f.fee for f in fills),D(0))
    # Separate FEE postings are included exactly once in the net cash sum.
    net_cash = sum((j.cash_delta for j in journal), D(0))
    gross_price = net_cash+fees if p.state=='CLOSED' else None
    planned_risk = D(str((evidence.get('economics') or {}).get('measurements',{}).get('expected_net_stop_loss_eur',0)))
    buy_ids = {o.order_id for o in buys}
    debit = -sum((j.cash_delta for j in journal if j.order_id in buy_ids),D(0))
    original_quantity = sum((f.quantity for f in fills if f.side=='BUY'),D(0))
    exit_impact = D(str((evidence.get('economics') or {}).get('measurements',{}).get('exit_now',{}).get('depth_impact_bps',0)))
    factor = (1-D(entry.get('fee_bps','0'))/10000)*(1-D(entry.get('slippage_bps','0'))/10000)*(1-exit_impact/10000)
    risk = debit-original_quantity*p.initial_stop*factor if p.initial_stop is not None else D(0)
    by_order = {o.order_id:o for o in orders}
    legs = []
    modeled = D(0)
    issues = []
    for f in sorted(fills,key=lambda f:f.created_at):
        o = by_order[f.order_id]
        payload = json.loads(o.execution_json)
        book = payload.get('book', {})
        levels = book.get('asks' if f.side=='BUY' else 'bids',[])
        reference = D(levels[0][0]) if levels else None
        cost = f.quantity*((f.price-reference) if f.side=='BUY' else (reference-f.price)) if reference else None
        if cost is not None:
            modeled += cost
        intent = next((i for i in intents if i.exit_intent_id==o.exit_intent_id),None)
        if f.side=='SELL' and payload.get('strategy_id')!=strategy:
            issues.append('Historical SELL label differs from entry plan; linked attribution corrected, raw record retained.')
        legs.append({'order_id':o.order_id,'fill_id':f.fill_id,'side':f.side,'timestamp':aware(f.created_at).isoformat(),
            'quantity':str(f.quantity),'price':str(f.price),'fee_eur':str(f.fee),
            'strategy_id':strategy,'raw_strategy_id':payload.get('strategy_id'),
            'exit_reason':intent.reason if intent else None,'book':book,
            'execution_quality':payload.get('execution_quality'),
            'modeled_slippage_and_impact_eur':str(cost) if cost is not None else None,
            'slippage_bps_assumption':payload.get('slippage_bps')})
    if p.state=='CLOSED' and net_cash != p.realized_pnl:
        issues.append('Position P&L differs from linked journal cash flow; investigate reconciliation.')
    exit_context = sorted([a for a in assessments if a.get('position_id')==p.position_id], key=lambda a:a.get('as_of',''))
    exit_context = [a for a in exit_context if not p.closed_at or a['as_of']<=aware(p.closed_at).isoformat()]
    reasons = list(dict.fromkeys(i.reason for i in intents if i.status in {'FILLED','COMPLETED'})) or list(dict.fromkeys(leg['exit_reason'] for leg in legs if leg['exit_reason']))
    measurements = (evidence.get('economics') or {}).get('measurements',{})
    higher = evidence.get('regime_assessment',{}).get('timeframes',{})
    overhead = [D(c['resistance']) for c in higher.values() if isinstance(c,dict) and c.get('ready') and c.get('resistance') and D(c['resistance'])>p.average_entry_price]
    concerns = []
    recorded_regime = evidence.get('raoe_regime') or evidence.get('regime_assessment') or {}
    recorded_frames = recorded_regime.get('timeframes', {})
    if strategy == 'RAOE_EARLY_RECOVERY' and recorded_frames.get('15', {}).get('trend') == 'BEARISH':
        concerns.append('The early-recovery entry preceded a bullish fifteen-minute reversal; a short bounce was not proof of a new trend.')
    if recorded_frames.get('60', {}).get('trend') == 'BEARISH':
        concerns.append('The asset had a bearish completed hourly trend at entry.')
    if recorded_regime.get('benchmark') == 'MIXED':
        concerns.append('MIXED described short-term Bitcoin/Ether agreement, not confirmed favorable hourly market structure.')
    if evidence.get('regime_assessment',{}).get('benchmark')=='ADVERSE':
        concerns.append('BTC/ETH context was adverse at entry.')
    original_targets = entry.get('targets',[]) or [str(t.target_price) for t in sorted(targets,key=lambda t:t.target_number)]
    if overhead and original_targets and D(original_targets[0])>min(overhead):
        concerns.append('TP1 was above nearby recorded higher-timeframe resistance.')
    detailed_exit_reason = exit_context[-1].get('reason') if exit_context else None
    explanation = ('Price moved against the position and the protective stop executed. ' if 'STOP' in reasons else 'Exit followed '+', '.join(reasons)+'. ' if reasons else 'Exit reason unavailable. ')
    if detailed_exit_reason == 'regime_exit' and 'MARKET_RISK' in reasons:
        explanation += 'The recorded cause was a position-specific completed-candle reversal; MARKET_RISK is the generic historical intent label. '
    if gross_price is not None:
        explanation += ('The price move lost money before fees. ' if gross_price<0 else 'The price move made money before fees. ')
    sell_quantity = sum((f.quantity for f in fills if f.side=='SELL'),D(0))
    exit_price = sum((f.price*f.quantity for f in fills if f.side=='SELL'),D(0))/sell_quantity if sell_quantity else None
    return {'position_id':p.position_id,'symbol':p.symbol,'state':p.state,'strategy_id':strategy,
        'execution_profile':evidence.get('execution_profile'),'entry_reason':evidence.get('conditions',{}),
        'entry_concerns_known_then':concerns,'entry_regime':evidence.get('regime_assessment'),
        'exit_regime':exit_context[-1] if exit_context else None,
        'exit_regime_status':'RECORDED_POSITION_SPECIFIC' if exit_context else 'NOT_RECORDED_AT_EXIT',
        'opened_at':aware(p.opened_at).isoformat(),'closed_at':aware(p.closed_at).isoformat() if p.closed_at else None,
        'planned_holding_seconds':entry.get('holding_seconds') or json.loads(plan.settings_json).get('holding_seconds') if plan else entry.get('holding_seconds'),
        'actual_holding_seconds':(aware(p.closed_at)-aware(p.opened_at)).total_seconds() if p.closed_at else None,
        'entry_price':str(p.average_entry_price),'exit_price':str(exit_price) if exit_price is not None else None,
        'initial_stop':str(p.initial_stop) if p.initial_stop else None,'targets':original_targets,
        'target_semantics':json.loads(plan.settings_json).get('target_semantics') if plan else None,
        'broker_net_unit_targets':json.loads(plan.settings_json).get('net_unit_targets') if plan else None,
        'expected_net_reward_risk':measurements.get('net_reward_risk'),'planned_net_stop_risk_eur':str(planned_risk) if planned_risk else None,
        'actual_size_initial_net_stop_risk_eur':str(risk) if risk>0 else None,
        'realized_r':str(p.realized_pnl/risk) if risk>0 and p.state=='CLOSED' else None,
        'gross_price_pnl_eur':str(gross_price) if gross_price is not None else None,
        'fees_eur':str(fees),'modeled_slippage_and_impact_eur':str(modeled),
        'cost_note':'Modeled slippage/impact is already embedded in fill prices and gross price P&L. Do not subtract it again.',
        'net_pnl_eur':str(p.realized_pnl),'journal_net_cash_eur':str(net_cash),
        'exit_reasons':reasons,'detailed_exit_reason':detailed_exit_reason,'explanation':explanation,'issues':list(dict.fromkeys(issues)),
        'fills':legs,'entry_economics':measurements,'raw_records_preserved':True}


async def trade_reports(repo: Any) -> list[dict[str, Any]]:
    async with repo.session_factory() as session:
        if session.bind.dialect.name=='postgresql':
            await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        positions = (await session.scalars(select(PositionModel).where(PositionModel.state=='CLOSED').order_by(PositionModel.closed_at.desc()).limit(80))).all()
        ids = [p.position_id for p in positions]
        async def rows(model: Any) -> Any:
            return (await session.scalars(select(model).where(model.position_id.in_(ids)))).all()
        plans = {p.position_id:p for p in await rows(ExitPlanModel)}
        orders, fills, targets, intents, journal = [await rows(m) for m in (OrderModel,FillModel,ExitTargetModel,ExitIntentModel,JournalEventModel)]
        contexts = [json.loads(r.payload_json) for r in (await session.scalars(select(SystemStateModel).where(SystemStateModel.state=='EXIT_ASSESSMENT'))).all()]
        reports = []
        for p in positions:
            groups = [[r for r in group if r.position_id==p.position_id] for group in (orders,fills,targets,intents,journal)]
            reports.append(explain_position(p,plans.get(p.position_id),groups[0],groups[1],groups[2],groups[3],groups[4],contexts))
        return reports


async def linked_attribution(session: Any) -> dict[str, str]:
    return {p.position_id:p.strategy_id for p in (await session.scalars(select(ExitPlanModel))).all()}
