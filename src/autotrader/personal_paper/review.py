"""Hourly frozen-evidence review. Proposals never rewrite active parameters."""
from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from autotrader.domain import utc_now
from autotrader.persistence.accounting import aware
from autotrader.persistence.models import (
    FillModel,
    PositionModel,
    StrategySignalModel,
    SystemStateModel,
)
from autotrader.persistence.repository import _json
from autotrader.research.data import canonical, digest


async def review_once(repo: Any) -> None:
    now = utc_now()
    async with repo.session_factory() as session, session.begin():
        await repo._lock_account(session)
        previous = await session.get(SystemStateModel, 'paper_research_review')
        if previous and json.loads(previous.payload_json).get('active_manifest_hash')==digest(canonical(repo.manifest)) and (now-aware(previous.updated_at)).total_seconds()<3600:
            return
        from datetime import datetime
        cutoff = max(now-timedelta(days=1), aware(datetime.fromisoformat(repo.manifest['frozen_at'])))
        signals = (await session.scalars(select(StrategySignalModel).where(StrategySignalModel.created_at>=cutoff))).all()
        positions = (await session.scalars(select(PositionModel).where(PositionModel.state=='CLOSED',PositionModel.closed_at>=cutoff))).all()
        fills = (await session.scalars(select(FillModel).where(FillModel.created_at>=cutoff))).all()
        blockers: Counter[str] = Counter()
        regimes: Counter[str] = Counter()
        for s in signals:
            evidence = json.loads(s.payload_json)['evidence']
            blockers.update(evidence.get('reasons', []))
            regimes.update([evidence.get('regime','UNKNOWN')])
        pnl = sum((p.realized_pnl for p in positions), Decimal(0))
        fees = sum((f.fee for f in fills), Decimal(0))
        proposals=[]
        if not fills and signals:
            proposals.append({'version':'4.7-research-proposal.1','hypothesis':'Test longer horizons and patient execution against dominant blockers',
                'trigger':'NO_QUALIFYING_BROKER_FILLS','dominant_blockers':dict(blockers.most_common(5)),
                'required_evaluation':'Separate chronological train/validation/unused holdout; compare cost stress and fill opportunity cost.'})
        if positions and pnl<=0:
            proposals.append({'version':'4.7-research-proposal.2','hypothesis':'Separate regime failure, stop/target geometry and transaction costs',
                'trigger':'NONPOSITIVE_CLOSED_POSITION_NET_RESULT','fees_in_window':str(fees),
                'required_evaluation':'Retain losing outcomes; stratify by asset, regime and holding time before a new version.'})
        body={'review_id':'paper-review-'+now.strftime('%Y%m%dT%H'), 'evidence_cutoff':now.isoformat(),
            'window_hours':24,'evidence_category':repo.manifest['data_kind'], 'active_manifest_hash':digest(canonical(repo.manifest)),
            'signal_observations':len(signals),'closed_positions':len(positions),'realized_closed_position_pnl':str(pnl),
            'fees_paid_in_window':str(fees),'regime_observations':dict(regimes),'dominant_blockers':dict(blockers.most_common(10)),
            'proposals':proposals,'automatic_activation':False,'parameter_trials_started':0,
            'conclusion':'Insufficient independent prospective evidence' if len(positions)<30 else 'Independent chronological and regime review required; no automatic promotion'}
        key=body['review_id']+'-'+digest(canonical(repo.manifest))[:12]
        body['review_id']=key
        if not await session.get(SystemStateModel,key):
            session.add(SystemStateModel(key=key,state='RESEARCH_REVIEW',reason='immutable_hourly_evidence_review',payload_json=_json(body)))
        if previous:
            previous.payload_json,previous.updated_at=_json(body),now
        else:
            session.add(SystemStateModel(key='paper_research_review',state='RESEARCH_REVIEW',reason='latest_hourly_review',payload_json=_json(body)))
