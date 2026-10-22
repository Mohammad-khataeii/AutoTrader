"""Authenticated bounded research observations, with no account or execution mutation."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Query
from sqlalchemy import select

from autotrader.domain import utc_now
from autotrader.opportunity.engine import SUCCESSOR_REGISTRY
from autotrader.opportunity.status import freshness, qualification
from autotrader.persistence.models import SystemStateModel


def comparison_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Routine comparison does not transmit training grids or source-file inventories."""
    metrics = {'net_profit','trades','fills_count','max_drawdown','sharpe_ratio','profit_factor','win_rate',
        'average_gain','average_loss','expectancy','average_holding_seconds','fees','spread_cost','slippage_cost',
        'average_exposure_eur','opportunity_counts','first_blocking_stages','costs','start','end_exclusive'}
    def result(value: dict[str, Any]) -> dict[str, Any]:
        return {k:v for k,v in value.items() if k in metrics}
    hypotheses = {}
    for identity,value in report.get('successors',{}).items():
        hypotheses[identity] = {k:v for k,v in value.items() if k in {'parameters','validation_gates','status'}}
        hypotheses[identity].update({k:result(value[k]) for k in ('validation','test','cost_stress','new_interval','rc1_new_interval') if k in value})
    registration = report.get('preregistered',{})
    return {'schema':report.get('schema'),'evidence_class':report.get('evidence_class'),
        'baseline':{k:result(v) for k,v in report.get('baseline',{}).items()}, 'successors':hypotheses,
        'limitations':registration.get('limits',[]),'source_fingerprint':registration.get('final_source_fingerprint',registration.get('source_fingerprint',registration.get('code_fingerprint'))),
        'promotions':report.get('promotions',[]),'verdict':report.get('verdict'),
        'details_omitted':['Training grid','Per-regime and symbol outcomes','Entry timing and sizing sensitivities','Source and data provenance']}


def install(app: FastAPI, repository: Any, require_user: Any, research_root: str) -> None:
    @app.get('/api/opportunities', dependencies=[Depends(require_user)])
    async def opportunities(limit: int = Query(12, ge=1, le=50), cursor: int = Query(0, ge=0, le=10000)) -> dict[str, Any]:
        async with repository.session_factory() as session:
            records = {r.key: r for r in await session.scalars(select(SystemStateModel).where(
                SystemStateModel.key.in_(['opportunity_snapshot', 'worker', 'worker_instance', 'scanner', 'operation'])))}
        row = records.pop('opportunity_snapshot', None)
        body = json.loads(row.payload_json) if row else {}
        states = freshness(body, row.state if row else 'NOT_RECORDED', row.updated_at if row else None, records, utc_now())
        rows = sorted(body.get('rows', []), key=lambda r: (not r['economic_eligible'], not r['technical_eligible'], -float(r['score']), r['symbol']))
        for candidate in rows:
            candidate['qualification_state'] = qualification(candidate)
        snapshot = {k: v for k, v in body.items() if k != 'rows'}
        current = states['research_freshness']['current']
        return {**snapshot, **states, 'status': row.state if row else 'NOT_RECORDED',
            'runtime_incident': row.reason if row and row.state == 'ERROR' else None,
            'updated_at': states['research_freshness']['observed_at'],
            'age_seconds': states['research_freshness']['age_seconds'], 'stale': not current,
            'quote_status': states['market_freshness']['state'],
            'technical_candidates': body.get('technical_candidates'),
            'economically_viable_candidates': body.get('economically_viable_candidates'),
            'rows': rows[cursor:cursor + limit], 'total': len(rows),
            'next_cursor': cursor + limit if cursor + limit < len(rows) else None,
            'read_only': True, 'predictive_edge': 'UNVALIDATED'}

    @app.get('/api/strategies/comparison', dependencies=[Depends(require_user)])
    async def strategy_comparison(detail: bool = False) -> dict[str, Any]:
        path = Path(research_root) / 'comparison-v46-rc2.json'
        provenance = 'local_research_store'
        if not path.is_file():
            path = Path('/app/evidence/v46/comparison-v46-rc2.json')
            provenance = 'immutable_release_research_snapshot'
        report = json.loads(path.read_text()) if path.is_file() else None
        return {'successors': [asdict(s) for s in SUCCESSOR_REGISTRY], 'research': report if detail or report is None else comparison_summary(report),
            'research_detail': 'FULL' if detail else 'SUMMARY', 'details_url': '/api/strategies/comparison?detail=true',
            'research_provenance': provenance if report else None,
            'status': 'RECORDED_RESEARCH' if report else 'NOT_RECORDED', 'read_only': True,
            'promotion': 'No automatic promotion or capital allocation; existing research approval policy remains authoritative.'}
