"""Successor paper runtime, using the existing allocation/risk/financial gateway."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from autotrader.decision import DecisionEngine
from autotrader.domain import DataQuality, DecisionAction, StrategySignal, TradingDecision, utc_now
from autotrader.opportunity.engine import SuccessorOpportunityEngine, SuccessorParameters
from autotrader.opportunity.features import enrich
from autotrader.persistence.models import (
    StrategySignalModel,
    SystemStateModel,
    TradingDecisionModel,
)
from autotrader.persistence.repository import _json
from autotrader.portfolio import Portfolio
from autotrader.research.data import digest

D = Decimal


def restore_decision(raw: str) -> TradingDecision:
    body = json.loads(raw)
    body.update(timestamp=datetime.fromisoformat(body['timestamp']), action=DecisionAction(body['action']))
    for key in ('proposed_quote_amount', 'proposed_quantity', 'entry_price', 'stop_loss'):
        body[key] = D(body[key]) if body[key] is not None else None
    body['take_profit_targets'] = tuple(D(v) for v in body['take_profit_targets'])
    return TradingDecision(**body)


def restore_signal(raw: str) -> StrategySignal:
    body = json.loads(raw)
    body.update(timestamp=datetime.fromisoformat(body['timestamp']), data_quality=DataQuality(body['data_quality']),
        score=D(body['score']), estimated_cost_bps=D(body['estimated_cost_bps']))
    return StrategySignal(**body)


async def scan_successor(runtime: Any, repo: Any, manifest: dict[str, Any], candidates: list[Any]) -> None:
    prepared = []
    for candidate in candidates:
        market = candidate.market
        if manifest['data_kind'] == 'LIVE_MARKET_SHADOW' and (not market.order_book.source.startswith('revolut-x') or any(not c.source.startswith('revolut-x') for c in market.candles)):
            raise ValueError('live_shadow_rejects_non_live_observations')
        if not market.usable_for_entry:
            continue
        features = enrich(candidate.features, market.candles, market.order_book.timestamp)
        features.metadata.update(best_bid=market.order_book.best_bid, best_ask=market.order_book.best_ask,
            last_price=market.metrics.mid, liquidity_quote=market.metrics.liquidity_quote, order_book_age_seconds=market.metrics.age_seconds)
        prepared.append(replace(candidate, features=features))
    context = {c.features.symbol: c.features for c in prepared}
    engine = SuccessorOpportunityEngine(SuccessorParameters.from_payload(manifest['parameters']),
        D(manifest['fee_bps']), D(manifest['slippage_bps']))
    completed_decisions = []
    for candidate in prepared:
        f, market = candidate.features, candidate.market
        key = 'opportunity_candle:' + f.symbol
        stamp = f.timestamp.isoformat()
        async with repo.session_factory() as session:
            completed = await session.get(SystemStateModel, key)
            if completed and json.loads(completed.payload_json)['stamp'] >= stamp:
                continue
        await repo.record_mark(market.order_book)
        snapshot = await repo.snapshot()
        portfolio = Portfolio(D(snapshot['available_cash']))
        portfolio.balances['EUR'].reserved = D(snapshot['reserved_cash'])
        portfolio.positions = {p.symbol: p for p in await repo.list_positions() if p.closed_at is None and p.quantity > 0}
        signal = engine.evaluate(manifest['strategy_id'], f, market.pair, market.order_book,
            context.get('BTC-EUR'), context.get('ETH-EUR'), market.candles,
            sizing_scope='ACCOUNT_CONSTRAINED_PROPOSAL',
            sizing_context={'cash': portfolio.cash, 'exposure': portfolio.open_exposure, 'limits': runtime.risk.limits})
        identity = 'dec_' + digest((manifest['experiment_id'] + ':' + signal.signal_id).encode())[:40]
        async with repo.session_factory() as session:
            stored = await session.get(TradingDecisionModel, identity)
            original = await session.get(StrategySignalModel, signal.signal_id) if stored else None
        if stored and original:
            # Resume the exact committed decision after an interrupted gateway;
            # fresh book/risk/coordinator admission still runs below.
            decision, signal = restore_decision(stored.payload_json), restore_signal(original.payload_json)
        else:
            decision = replace(DecisionEngine(runtime.risk).decide(market.pair, f, [signal], portfolio, None), decision_id=identity)
            signal.evidence['pipeline'][-2] = {'stage': 'PORTFOLIO_RISK', 'reached': signal.evidence['entry_eligible'],
                'passed': decision.accepted if signal.evidence['entry_eligible'] else None, 'reason': decision.rejected_reason or 'risk_checks_passed'}
        await repo.store_market_analysis(market.candles, f, market.order_book)
        await repo.store_analysis([signal], None, decision)
        gateway = runtime.gateway(repo)
        allocated, _ = await gateway.allocate_candidate(replace(candidate, features=f, signals=[signal], decision=decision, score=signal.score))
        if allocated is not None:
            await gateway.execute_entry_decision(market.pair, allocated, market.order_book,
                'shadow:' + digest((manifest['experiment_id'] + ':' + identity).encode())[:56])
        async with repo.session_factory() as session, session.begin():
            await repo._lock_account(session)
            row = await session.get(SystemStateModel, key)
            body = _json({'stamp': stamp, 'decision_id': identity, 'completed_at': utc_now().isoformat(), 'pattern_state': signal.evidence.get('pattern_state')})
            if row:
                row.payload_json, row.updated_at = body, utc_now()
            else:
                session.add(SystemStateModel(key=key, state='COMPLETED', reason='successor_candle_completed_after_gateway', payload_json=body))
        completed_decisions.append(identity)
    if completed_decisions:
        async with repo.session_factory() as session, session.begin():
            incident = await session.get(SystemStateModel, 'shadow_runtime_incident')
            if incident and incident.state == 'ERROR' and json.loads(incident.payload_json).get('phase') == 'scan':
                incident_body = json.loads(incident.payload_json)
                incident_body.update(resolved_at=utc_now().isoformat(), resolution='successor_scan_completed_with_durable_gateway_outcomes', decision_ids=completed_decisions)
                incident.state, incident.payload_json, incident.updated_at = 'RESOLVED', _json(incident_body), utc_now()
