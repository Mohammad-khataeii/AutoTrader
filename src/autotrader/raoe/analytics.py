"""Append-only decision-time candidates and separate future path assessments."""
from __future__ import annotations

import itertools
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, literal, select
from sqlalchemy.orm import aliased

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
    # Per-signal identity; episode statistics are derived separately. Historical
    # half-hour event records and assessments remain immutable.
    group = [signal.signal_id,repo.manifest['version'],'v49-per-signal']
    key='raoe_event:'+digest(canonical(group))[:48]
    body={'event_id':key,'strategy_id':signal.strategy_id,'symbol':signal.symbol,
        'profile':repo.manifest['version'],'decision_id':decision.decision_id,
        'observed_at':utc_now().isoformat(),'candle_at':signal.timestamp.isoformat(),
        'horizon_seconds':int(signal.evidence.get('holding_seconds',21600)),'accepted':decision.accepted,'rejection':decision.rejected_reason,
        'evidence':signal.evidence,'evidence_category':repo.manifest['data_kind'],
        'grouping':'per signal; same-asset overlapping holding windows grouped separately',
        'analytics_version':'4.9.0-evidence.1'}
    async with repo.session_factory() as session,session.begin():
        await repo._lock_account(session)
        if not await session.get(SystemStateModel,key):
            session.add(SystemStateModel(key=key,state='RECORDED',reason='immutable_decision_time_candidate',payload_json=_json(body)))


def classify(event: dict[str,Any], candles: list[Any]) -> dict[str,Any]:
    start=aware(datetime.fromisoformat(event['observed_at']))
    horizon=start+timedelta(seconds=event['horizon_seconds'])
    bars=sorted([c for c in candles if aware(c.timestamp)>=start and aware(c.timestamp)+timedelta(minutes=5)<=horizon],key=lambda c:c.timestamp)
    unique: dict[datetime,Any]={}
    conflicting=False
    for candle in bars:
        stamp=aware(candle.timestamp)
        previous=unique.get(stamp)
        if previous and any(getattr(previous,k)!=getattr(candle,k) for k in ('open','high','low','close')):conflicting=True
        if event.get('symbol') and candle.symbol!=event['symbol']:conflicting=True
        unique[stamp]=candle
    bars=list(unique.values())
    expected=int(horizon.timestamp()//300-(start.timestamp()+299)//300)
    base: dict[str,Any]={'analytics_version':'4.9.0-evidence.1','bars':len(bars),'required':expected,
        'profitability_proven':False,'executable_quote_observation':{'status':'MISSING_EVIDENCE'},
        'modeled_paper_execution':{'status':'MISSING_EVIDENCE','reason':'No saved future depth replay'},
        'strategy_counterfactual':{'status':'NOT_RUN','reason':'Barrier touch is not a versioned strategy simulation'},
        'actual_prospective_paper_trade':{'status':'NOT_ESTABLISHED','reason':'Requires order and fill ledger joins'}}
    if conflicting:return {**base,'classification':'MISSING_EVIDENCE','reason':'Conflicting or mixed-asset candle versions','price_path_observation':{'status':'CONFLICTING_MARKET_DATA'}}
    if len(bars)<expected or any(aware(b.timestamp)-aware(a.timestamp)!=timedelta(minutes=5) for a,b in itertools.pairwise(bars)):
        return {**base,'classification':'MISSING_EVIDENCE','price_path_observation':{'status':'MISSING_MARKET_DATA'}}
    plan=event['evidence']['entry_plan']
    targets=plan.get('targets',[])
    entry=D(plan.get('entry') or 0)
    stop=D(plan.get('stop') or 0)
    path={'status':'OBSERVED','maximum_high':str(max((c.high for c in bars),default=D(0))),
          'minimum_low':str(min((c.low for c in bars),default=D(0))),
          'entry_reference':str(entry),'first_bar_at':aware(bars[0].timestamp).isoformat() if bars else None,
          'execution':'UNPROVEN; candles may be mid-price rather than traded bids'}
    base['price_path_observation']=path
    economic=bool(event['evidence'].get('economic_eligible'))
    if not targets or not 0<stop<entry:
        return {**base,'classification':'INCONCLUSIVE','reason':'No defensible original barriers; subsequent movement cannot validate a trade'}
    target=D(targets[0])
    for c in bars:
        if c.low<=stop:
            path.update(first_barrier='STOP',ambiguous_stop_and_target=c.high>=target,outcome_at=aware(c.timestamp).isoformat())
            return {**base,'classification':'INCONCLUSIVE','ambiguous_stop_and_target':c.high>=target,
                'reason':'Conservative stop-first price path; correctness of rejection or executable loss is unproven'}
        if c.high>=target:
            path.update(first_barrier='TARGET',outcome_at=aware(c.timestamp).isoformat())
            return {**base,'classification':'POTENTIALLY_FAVORABLE_PRICE_PATH' if economic and target>entry else 'INCONCLUSIVE',
                'reason':'Price barrier observed; no historical executable bid depth' if economic else 'Original plan failed economics; touching its target does not establish a missed profit'}
    return {**base,'classification':'INCONCLUSIVE','reason':'Neither original barrier reached within fixed horizon'}


def episodes(events: list[dict[str,Any]]) -> list[dict[str,Any]]:
    """Fixed first-observation windows avoid counting repeats as independent wins.

    The 90 minute suppression also applies to shorter strategies. A longer
    holding policy groups overlapping proposals, even across different entries.
    A later repeated signal never extends the episode indefinitely.
    """
    groups: list[dict[str,Any]]=[]
    active: dict[str,dict[str,Any]]={}
    for event in sorted(events,key=lambda e:(e['observed_at'],e.get('event_id',''))):
        stamp=aware(datetime.fromisoformat(event['observed_at']))
        symbol=event['symbol'];group=active.get(symbol)
        if group is None or stamp>=datetime.fromisoformat(group['end_exclusive']):
            group={'episode_id':'episode:'+digest(canonical([symbol,event['observed_at']]))[:32],
                'symbol':symbol,'first_observed_at':event['observed_at'],
                'end_exclusive':(stamp+timedelta(seconds=max(5400,int(event.get('horizon_seconds',21600))))).isoformat(),
                'first_actionable_observation':None,'signal_count':0,'strategies':[],
                'signal_ids':[],'position_conflicts':0,'independent_win':False,
                'scope':'Supplied event window only; earlier events may belong to the same episode'}
            groups.append(group);active[symbol]=group
        group['signal_count']+=1
        group['signal_ids'].append(event.get('event_id'))
        if event.get('strategy_id') not in group['strategies']:group['strategies'].append(event.get('strategy_id'))
        if event.get('evidence',{}).get('entry_eligible') and group['first_actionable_observation'] is None:
            group['first_actionable_observation']=event['observed_at']
        if 'position' in str(event.get('rejection','')).lower() or 'exposure' in str(event.get('rejection','')).lower():
            group['position_conflicts']+=1
    return groups


async def assess_due(repo: Any, limit: int = 12) -> None:
    now=utc_now()
    async with repo.session_factory() as session:
        outcome=aliased(SystemStateModel)
        result_identity=literal('raoe49_outcome:')+func.substr(SystemStateModel.key,len('raoe_event:')+1)
        unassessed=~select(outcome.key).where(outcome.key==result_identity).exists()
        events=(await session.scalars(select(SystemStateModel).where(SystemStateModel.key.like('raoe_event:%'),
            SystemStateModel.created_at<=now-timedelta(hours=6),unassessed).order_by(SystemStateModel.created_at).limit(limit))).all()
        due=[]
        for event in events:
            result_key='raoe49_outcome:'+event.key.removeprefix('raoe_event:')
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
