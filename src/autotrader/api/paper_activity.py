"""Bounded, read-only projections of real primary-account decisions and fills."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import or_, select, text

from autotrader.api.trade_reports import linked_attribution
from autotrader.domain import utc_now
from autotrader.persistence.accounting import aware
from autotrader.persistence.models import (
    FillModel,
    OrderModel,
    StrategySignalModel,
    TradingDecisionModel,
)


async def activity_feed(service: Any) -> dict[str, Any]:
    repo = await service.repository()
    if repo is None:
        return {'events': [], 'evaluations': [], 'observed_at': utc_now().isoformat()}
    async with repo.session_factory() as session:
        if session.bind.dialect.name == 'postgresql':
            await session.execute(text('SET TRANSACTION READ ONLY'))
        decisions = (await session.scalars(select(TradingDecisionModel).order_by(
            TradingDecisionModel.created_at.desc(), TradingDecisionModel.decision_id.desc()).limit(40))).all()
        bodies = {d.decision_id: json.loads(d.payload_json) for d in decisions}
        signal_ids = [s for d in bodies.values() for s in d.get('signal_ids', [])]
        signals = {s.signal_id: s for s in (await session.scalars(select(StrategySignalModel).where(
            StrategySignalModel.signal_id.in_(signal_ids)))).all()}
        recent_orders = select(OrderModel.order_id).order_by(OrderModel.created_at.desc()).limit(20)
        orders = (await session.scalars(select(OrderModel).where(or_(
            OrderModel.decision_id.in_(list(bodies)), OrderModel.order_id.in_(recent_orders))))).all()
        fills = (await session.scalars(select(FillModel).order_by(
            FillModel.created_at.desc(), FillModel.fill_id.desc()).limit(20))).all()
        linked = await linked_attribution(session)
    by_decision = {o.decision_id: o for o in orders if o.decision_id}
    evaluations: list[dict[str, Any]] = []
    for decision in decisions:
        body = bodies[decision.decision_id]
        signal = next((signals[s] for s in body.get('signal_ids', []) if s in signals), None)
        evidence = json.loads(signal.payload_json).get('evidence', {}) if signal else {}
        order = by_decision.get(decision.decision_id)
        evaluations.append({
            'id': decision.decision_id, 'kind': 'DECISION', 'timestamp': aware(decision.created_at).isoformat(),
            'candle_at': aware(signal.timestamp).isoformat() if signal else None,
            'symbol': decision.symbol, 'strategy_id': signal.strategy_id if signal else None,
            'execution_profile': evidence.get('execution_profile'), 'score': str(signal.score) if signal else None,
            'technical': evidence.get('technical_eligible'), 'economic': evidence.get('economic_eligible'),
            'accepted': decision.accepted, 'reasons': evidence.get('reasons', []),
            'decision_reason': decision.rejected_reason, 'economics': evidence.get('economics'),
            'quality_policy': evidence.get('quality_policy'), 'ranking_components': evidence.get('ranking_components'),
            'entry_plan': evidence.get('entry_plan'), 'sizing': evidence.get('sizing'),
            'quote_amount': body.get('proposed_quote_amount'),
            'entry_price': body.get('entry_price'), 'stop_loss': body.get('stop_loss'),
            'broker_status': order.status if order else None,
            'broker_reason': json.loads(order.execution_json).get('rejection_reason') if order else None,
            'order_id': order.order_id if order else None,
        })
    events = list(evaluations)
    for order in orders:
        payload = json.loads(order.execution_json)
        events.append({'id': order.order_id, 'kind': 'ORDER', 'timestamp': aware(order.created_at).isoformat(),
            'symbol': order.symbol, 'side': order.side, 'status': order.status,
            'strategy_id': linked.get(order.position_id, payload.get('strategy_id')),
            'raw_strategy_id': payload.get('strategy_id'), 'reason': payload.get('rejection_reason'),
            'quantity': str(order.quantity), 'filled_quantity': str(order.filled_quantity),
            'execution_profile': payload.get('strategy_evidence', {}).get('execution_profile'),
            'decision_id': order.decision_id})
    for fill in fills:
        events.append({'id': fill.fill_id, 'kind': 'FILL', 'timestamp': aware(fill.created_at).isoformat(),
            'symbol': fill.symbol, 'side': fill.side, 'quantity': str(fill.quantity),
            'strategy_id': linked.get(fill.position_id),
            'price': str(fill.price), 'fee_eur': str(fill.fee), 'order_id': fill.order_id})
    events.sort(key=lambda e: (e['timestamp'], e['id']), reverse=True)
    return {'events': events[:80], 'evaluations': evaluations, 'observed_at': utc_now().isoformat(),
        'evidence_category': repo.manifest['data_kind'], 'event_limit': 80,
        'execution_profile': repo.manifest['version'], 'read_only': True}
