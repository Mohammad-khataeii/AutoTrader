"""Append-only decision-time candidates and separate future path assessments."""
from __future__ import annotations

import itertools
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from autotrader.domain import utc_now
from autotrader.persistence.accounting import aware
from autotrader.persistence.models import MarketCandle, SystemStateModel
from autotrader.persistence.repository import _json
from autotrader.research.data import canonical, digest

D = Decimal


def risk_stage(pipeline: list[dict[str,Any]], reached: bool, accepted: bool, reason: str | None) -> None:
    pipeline[6].update(reached=reached,passed=accepted if reached else None,
        state='PASSED' if reached and accepted else 'FAILED' if reached else 'NOT_REACHED',reason=reason)


async def record_candidate(repo: Any, signal: Any, decision: Any) -> None:
    # One event per strategy/asset/half-hour. All repeated decisions remain in
    # trading_decisions; this event series must not count them as independent.
    group = [signal.strategy_id,signal.symbol,int(signal.timestamp.timestamp())//1800,repo.manifest['version']]
    key='raoe_event:'+digest(canonical(group))[:48]
    body={'event_id':key,'strategy_id':signal.strategy_id,'symbol':signal.symbol,
        'profile':repo.manifest['version'],'decision_id':decision.decision_id,
        'observed_at':utc_now().isoformat(),'candle_at':signal.timestamp.isoformat(),
        'horizon_seconds':21600,'accepted':decision.accepted,'rejection':decision.rejected_reason,
        'evidence':signal.evidence,'evidence_category':repo.manifest['data_kind'],
        'grouping':'first observation per strategy/asset/30min; overlapping 6h outcomes are dependent'}
    async with repo.session_factory() as session,session.begin():
        await repo._lock_account(session)
        if not await session.get(SystemStateModel,key):
            session.add(SystemStateModel(key=key,state='RECORDED',reason='immutable_decision_time_candidate',payload_json=_json(body)))


def classify(event: dict[str,Any], candles: list[Any]) -> dict[str,Any]:
    start=aware(datetime.fromisoformat(event['observed_at']))
    horizon=start+timedelta(seconds=event['horizon_seconds'])
    # Exclude the candle that was forming at observation time: its low/high
    # could precede the decision. No hindsight fill within that candle.
    bars=sorted([c for c in candles if aware(c.timestamp)>=start and aware(c.timestamp)+timedelta(minutes=5)<=horizon],key=lambda c:c.timestamp)
    unique={aware(c.timestamp):c for c in bars}
    bars=list(unique.values())
    expected=int(horizon.timestamp()//300-(start.timestamp()+299)//300)
    if len(bars)<expected or any(aware(b.timestamp)-aware(a.timestamp)!=timedelta(minutes=5) for a,b in itertools.pairwise(bars)):
        return {'classification':'MISSING_MARKET_DATA','bars':len(bars),'required':expected}
    plan=event['evidence']['entry_plan']
    targets=plan.get('targets',[])
    if not targets or D(plan['stop'])<=0:
        return {'classification':'INCONCLUSIVE','reason':'No defensible entry plan at decision time'}
    stop,target=D(plan['stop']),D(targets[0])
    for c in bars:
        if c.low<=stop:
            return {'classification':'CORRECT_REJECTION' if not event['accepted'] else 'INCONCLUSIVE',
                'reason':'Conservative stop-first recorded path; no actual alternate order',
                'ambiguous_stop_and_target':c.high>=target,'outcome_at':aware(c.timestamp).isoformat()}
        if c.high>=target:
            return {'classification':'POTENTIAL_FAVORABLE_MOVE_NOT_PROVEN_EXECUTABLE',
                'reason':'Mid-price candle path; no historical bid depth or passive queue evidence',
                'outcome_at':aware(c.timestamp).isoformat()}
    return {'classification':'INCONCLUSIVE','reason':'Neither original barrier reached within fixed horizon'}


async def assess_due(repo: Any, limit: int = 12) -> None:
    now=utc_now()
    async with repo.session_factory() as session:
        events=(await session.scalars(select(SystemStateModel).where(SystemStateModel.key.like('raoe_event:%'),
            SystemStateModel.created_at<=now-timedelta(hours=6)).order_by(SystemStateModel.created_at.desc()).limit(100))).all()
        due=[]
        for event in events:
            result_key='raoe_outcome:'+event.key.removeprefix('raoe_event:')
            if not await session.get(SystemStateModel,result_key): due.append((event,result_key))
        for event,result_key in due[:limit]:
            body=json.loads(event.payload_json)
            start=aware(datetime.fromisoformat(body['observed_at']))
            rows=(await session.scalars(select(MarketCandle).where(MarketCandle.symbol==body['symbol'],
                MarketCandle.timeframe=='5m',MarketCandle.timestamp>=start,
                MarketCandle.timestamp<=start+timedelta(hours=6)).order_by(MarketCandle.timestamp))).all()
            result={**classify(body,rows),'event_id':event.key,'assessed_at':now.isoformat(),
                'evidence_category':'PROSPECTIVE_OBSERVATIONS_HYPOTHETICAL_PATH_ANALYSIS',
                'profitability_proven':False}
            async with repo.session_factory() as writer,writer.begin():
                await repo._lock_account(writer)
                if not await writer.get(SystemStateModel,result_key):
                    writer.add(SystemStateModel(key=result_key,state='ASSESSED',reason='separate_fixed_horizon_outcome',payload_json=_json(result)))
