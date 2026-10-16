from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from autotrader.domain import new_id, utc_now
from autotrader.persistence.models import (
    MarketFeature,
    PositionModel,
    SystemIncidentModel,
    SystemStateModel,
)
from autotrader.research.artifacts import load_latest, source_fingerprint
from autotrader.research.data import canonical, digest
from autotrader.research.strategies import VERSION, StrategyParameters


def promotion_error(policy: dict[str, Any], strategy: str, evidence: dict[str, Any],
                    fee_bps: Any, slippage_bps: Any) -> str | None:
    if not policy.get('require_validation'):
        return None
    member=policy.get('members',{}).get(strategy)
    if strategy not in policy.get('allowed_strategy_ids',[]) or not member:
        return 'strategy_not_approved_and_validated'
    current,_=source_fingerprint()
    if current!=member['source_fingerprint']:
        return 'strategy_source_mismatch'
    if evidence.get('timeframe')!='5m' or evidence.get('strategy_version')!=member['strategy_version']:
        return 'strategy_timeframe_or_version_mismatch'
    if evidence.get('parameters')!=member['frozen_parameters']:
        return 'strategy_parameter_mismatch'
    costs={'fee_bps':str(fee_bps),'slippage_bps':str(slippage_bps),'spread_bps':'10','volume_participation':'.01'}
    if digest(canonical(costs))!=member['execution_assumptions_hash']:
        return 'strategy_execution_assumptions_mismatch'
    return None


class ResearchPolicyMixin:
    session_factory: Any
    _lock_account: Any

    @staticmethod
    def _promotion_event(session: Any, candidate: dict[str, Any], state: str, actor: str, reason: str) -> None:
        session.add(SystemIncidentModel(incident_id=new_id('promotion'), severity='INFO', status=state,
            message='research_promotion_transition', payload_json=json.dumps({
                'candidate_id':candidate['candidate_id'], 'strategy_id':candidate['strategy_id'],
                'state':state, 'actor':actor, 'reason':reason, 'timestamp':utc_now().isoformat()})))

    async def configure_research_policy(self, root: Path, *, test_environment: bool,
                                         approved: set[str], execution_costs: dict[str, str] | None = None) -> None:
        summary, failure = None, None
        try:
            summary = load_latest(root)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            failure = type(exc).__name__ + ':' + str(exc)
        current_source, _ = source_fingerprint()
        source_matches = bool(summary and summary.get('source_fingerprint') == current_source)
        costs = execution_costs or {'fee_bps':'10','slippage_bps':'8','spread_bps':'10','volume_participation':'.01'}
        expected_costs = digest(canonical(costs))
        current_candidates: dict[str, dict[str, Any]] = {}
        if summary:
            for result in summary.get('timeframes', {}).values():
                for evidence in result.get('strategies', {}).values():
                    candidate = evidence.get('candidate')
                    if candidate:
                        current_candidates[candidate['candidate_id']] = {**candidate,
                            'gates_passed':bool(evidence.get('gates',{}).get('passed')),
                            'globally_passed':candidate['strategy_id'] in summary.get('passed_strategies',[]),
                            'parameters_verified':evidence.get('out_of_sample',{}).get('parameters')==candidate.get('frozen_parameters')}
        async with self.session_factory() as session, session.begin():
            if test_environment and session.bind.dialect.name=='postgresql' and not (session.bind.url.database or '').startswith(('autotrader_v34_','autotrader_v41_','autotrader_test_','autotrader_acceptance_')):
                raise ValueError('Test financial acceptance cannot share the production paper database.')
            await self._lock_account(session)
            rows = list((await session.scalars(select(SystemStateModel).where(SystemStateModel.key.like('candidate:%')))).all())
            by_id = {json.loads(r.payload_json)['candidate_id']:r for r in rows}
            for identity, candidate in current_candidates.items():
                if identity not in by_id:
                    initial = 'AWAITING_APPROVAL' if candidate['gates_passed'] else 'RESEARCH_REJECTED'
                    row = SystemStateModel(key='candidate:'+identity[:54],state=initial,reason='research_import',payload_json=json.dumps(candidate,sort_keys=True))
                    session.add(row)
                    by_id[identity] = row
                    self._promotion_event(session,candidate,'RESEARCH_CANDIDATE','research','immutable research artifact imported')
                    if candidate['gates_passed']:
                        self._promotion_event(session,candidate,'RESEARCH_PASSED','research','configured gates passed')
                    self._promotion_event(session,candidate,initial,'research','explicit review required' if candidate['gates_passed'] else 'validation gates failed')
            allowed, members = [], {}
            for identity, row in by_id.items():
                candidate = json.loads(row.payload_json)
                compatible = (identity in current_candidates and source_matches and
                    candidate['source_fingerprint']==current_source and candidate['research_timeframe']=='5m' and
                    candidate['strategy_version']==VERSION and candidate['gates_passed'] and candidate['globally_passed'] and candidate['parameters_verified'] and
                    candidate['execution_assumptions_hash']==expected_costs and
                    digest(canonical(candidate['frozen_parameters']))==candidate['parameter_hash'])
                if row.state in {'PAPER_APPROVED','PAPER_ACTIVE'} and not compatible:
                    row.state, row.reason = 'PAPER_SUSPENDED','research_identity_changed'
                    self._promotion_event(session,candidate,row.state,'system',row.reason)
                # Explicit environment approvals retain the original interface, but
                # cannot revive suspended identities or approve failed research.
                if compatible and row.state=='AWAITING_APPROVAL' and candidate['strategy_id'] in approved:
                    row.state='PAPER_APPROVED'
                    candidate.update(approved_at=utc_now().isoformat(),approving_authority='operator:APPROVED_STRATEGY_IDS')
                    row.payload_json=json.dumps(candidate,sort_keys=True)
                    self._promotion_event(session,candidate,row.state,'operator:APPROVED_STRATEGY_IDS','explicit configured approval')
                if compatible and row.state in {'PAPER_APPROVED','PAPER_ACTIVE'}:
                    if row.state!='PAPER_ACTIVE':
                        row.state='PAPER_ACTIVE'
                        self._promotion_event(session,candidate,row.state,'worker','matching runtime configuration activated')
                    allowed.append(candidate['strategy_id'])
                    members[candidate['strategy_id']] = candidate
            payload = {'require_validation':not test_environment,'allowed_strategy_ids':sorted(allowed),
                'mode':'TEST_FINANCIAL_ACCEPTANCE' if test_environment else 'VALIDATED_ONLY',
                'status':'PAPER_READY' if allowed else 'NO VALIDATED STRATEGY',
                'research_verdict':summary.get('verdict') if summary else 'NO_VERIFIED_RESEARCH_REPORT',
                'research_run_id':summary.get('run_id') if summary else None,'source_matches':source_matches,
                'source_fingerprint':current_source,'live_timeframe':'5m','members':members,
                'required_parameters':StrategyParameters().payload(),'execution_assumptions_hash':expected_costs,
                'execution_costs':costs,
                'promotion_requirement':'Matching timeframe, frozen per-member parameters, source, dataset, costs, validation and durable explicit approval',
                'failure':failure,'policy_version':'4.1.0'}
            encoded=json.dumps(payload,sort_keys=True)
            row=await session.get(SystemStateModel,'research_entry_policy')
            if row and row.payload_json==encoded:
                return
            if row is None:
                session.add(SystemStateModel(key='research_entry_policy',state=payload['mode'],reason='research_promotion_gate',payload_json=encoded))
            else:
                row.state,row.reason,row.payload_json=payload['mode'],'research_promotion_gate',encoded
            session.add(SystemIncidentModel(incident_id=new_id('inc'),severity='INFO',status='ENTRY_POLICY',
                message='research_strategy_promotion_policy',payload_json=encoded))

    async def promotion_candidates(self) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            rows=(await session.scalars(select(SystemStateModel).where(SystemStateModel.key.like('candidate:%')))).all()
            return [{**json.loads(r.payload_json),'state':r.state,'reason':r.reason} for r in rows]

    async def decide_promotion(self, candidate_id: str, *, approve: bool, actor: str, reason: str) -> None:
        async with self.session_factory() as session,session.begin():
            await self._lock_account(session)
            row=await session.get(SystemStateModel,'candidate:'+candidate_id[:54])
            if row is None:
                raise ValueError('unknown_research_candidate')
            candidate=json.loads(row.payload_json)
            if candidate['candidate_id']!=candidate_id:
                raise ValueError('candidate_identity_mismatch')
            policy=await session.get(SystemStateModel,'research_entry_policy')
            context=json.loads(policy.payload_json) if policy else {}
            current,_=source_fingerprint()
            if approve and not (row.state in {'AWAITING_APPROVAL','PAPER_SUSPENDED'} and
                candidate['gates_passed'] and candidate['globally_passed'] and candidate['parameters_verified'] and candidate['research_timeframe']=='5m' and
                candidate['source_fingerprint']==current and candidate['research_run_id']==context.get('research_run_id') and
                candidate['execution_assumptions_hash']==context.get('execution_assumptions_hash') and
                digest(canonical(candidate['frozen_parameters']))==candidate['parameter_hash']):
                raise ValueError('candidate_not_validated_for_current_runtime')
            row.state='PAPER_APPROVED' if approve else 'PAPER_SUSPENDED'
            row.reason=reason
            candidate.update(approved_at=utc_now().isoformat() if approve else candidate.get('approved_at'),approving_authority=actor)
            row.payload_json=json.dumps(candidate,sort_keys=True)
            self._promotion_event(session,candidate,row.state,actor,reason)
            # Suspension takes effect in this transaction, including pending BUYs.
            if not approve and policy:
                context['allowed_strategy_ids']=[s for s in context.get('allowed_strategy_ids',[]) if s!=candidate['strategy_id']]
                context.get('members',{}).pop(candidate['strategy_id'],None)
                policy.payload_json=json.dumps(context,sort_keys=True)

    async def frozen_runtime_parameters(self) -> dict[str, StrategyParameters]:
        async with self.session_factory() as session:
            policy=await session.get(SystemStateModel,'research_entry_policy')
            members=json.loads(policy.payload_json).get('members',{}) if policy else {}
            from decimal import Decimal
            return {s:StrategyParameters(**{k:Decimal(v) for k,v in c['frozen_parameters'].items()}) for s,c in members.items()}

    async def candidate_policy_reason(self, signals: list[Any]) -> str | None:
        async with self.session_factory() as session:
            row=await session.get(SystemStateModel,'research_entry_policy')
            policy=json.loads(row.payload_json) if row else {}
        if not policy.get('require_validation'):
            return None
        eligible=[s for s in signals if s.evidence.get('entry_eligible')]
        if not eligible:
            return None
        primary=min(eligible,key=lambda s:(-s.score,s.strategy_id))
        costs=policy.get('execution_costs',{})
        return promotion_error(policy,primary.strategy_id,primary.evidence,costs.get('fee_bps','10'),costs.get('slippage_bps','8'))

    async def allocation_context(self) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            positions = (await session.scalars(select(PositionModel).where(PositionModel.state == "OPEN"))).all()
            result = []
            for position in positions:
                row = await session.scalar(select(MarketFeature).where(MarketFeature.symbol == position.symbol,
                    MarketFeature.timestamp <= utc_now()).order_by(MarketFeature.timestamp.desc()).limit(1))
                if row:
                    metadata = json.loads(row.payload_json).get("metadata", {})
                    metadata["_feature_timestamp"] = row.timestamp.isoformat()
                    result.append(metadata)
                else:
                    result.append({})
            return result

    async def store_allocation_advice(self, decision_id: str, payload: dict[str, Any]) -> None:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            key = "alloc:" + decision_id
            row = await session.get(SystemStateModel, key)
            if row is None:
                session.add(SystemStateModel(key=key, state="ACCEPTED" if payload["accepted"] else "REJECTED",
                    reason="portfolio_allocation", payload_json=json.dumps(payload, default=str)))
