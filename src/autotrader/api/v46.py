"""Authenticated bounded research observations, with no account or execution mutation."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Query

from autotrader.domain import utc_now
from autotrader.opportunity.engine import SUCCESSOR_REGISTRY
from autotrader.persistence.accounting import aware
from autotrader.persistence.models import SystemStateModel


def install(app: FastAPI, repository: Any, require_user: Any, research_root: str) -> None:
    @app.get('/api/opportunities', dependencies=[Depends(require_user)])
    async def opportunities(limit: int = Query(12, ge=1, le=50), cursor: int = Query(0, ge=0, le=10000)) -> dict[str, Any]:
        async with repository.session_factory() as session:
            row = await session.get(SystemStateModel, 'opportunity_snapshot')
        if row is None:
            return {'status': 'NOT_RECORDED', 'rows': [], 'read_only': True, 'next_cursor': None,
                'reason': 'No successor opportunity observation is available yet.', 'predictive_edge': 'UNVALIDATED'}
        body = json.loads(row.payload_json)
        updated = datetime.fromisoformat(body['updated_at']) if body.get('updated_at') else row.updated_at
        age = max(0, (utc_now() - aware(updated)).total_seconds())
        rows = sorted(body.pop('rows', []), key=lambda r: (not r['economic_eligible'], not r['technical_eligible'], -float(r['score']), r['symbol']))
        return {**body, 'status': row.state, 'runtime_incident': row.reason if row.state == 'ERROR' else None,
            'updated_at': aware(updated).isoformat(), 'age_seconds': age, 'stale': age > 90 or row.state == 'ERROR',
            'quote_status': 'ERROR_WATCH_ONLY' if row.state == 'ERROR' else 'STALE_WATCH_ONLY' if age > 90 else 'OBSERVED_NOT_AN_ENTRY_INSTRUCTION',
            'rows': rows[cursor:cursor + limit], 'total': len(rows), 'next_cursor': cursor + limit if cursor + limit < len(rows) else None,
            'read_only': True, 'predictive_edge': 'UNVALIDATED'}

    @app.get('/api/strategies/comparison', dependencies=[Depends(require_user)])
    async def strategy_comparison() -> dict[str, Any]:
        path = Path(research_root) / 'comparison-v46.json'
        provenance = 'local_research_store'
        if not path.is_file():
            path = Path('/app/evidence/v46/comparison-v46.json')
            provenance = 'immutable_release_research_snapshot'
        report = json.loads(path.read_text()) if path.is_file() else None
        return {'successors': [asdict(s) for s in SUCCESSOR_REGISTRY], 'research': report,
            'research_provenance': provenance if report else None,
            'status': 'RECORDED_RESEARCH' if report else 'NOT_RECORDED', 'read_only': True,
            'promotion': 'No automatic promotion or capital allocation; existing research approval policy remains authoritative.'}
