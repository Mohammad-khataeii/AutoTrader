"""Authenticated learning status; never starts training on an HTTP read."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI

from autotrader.domain import utc_now
from autotrader.learning.features import stamp


def read_status(root: Path) -> dict[str, Any]:
    path = root/'status.json'
    if not path.is_file():
        return {'status': 'WAITING_FOR_COLLECTOR', 'warnings': ['No research-worker learning heartbeat'],
                'approved_model': 'DETERMINISTIC_FROZEN_BASELINE_NO_APPROVED_ML', 'live_authorized': False}
    if path.stat().st_size > 4*1024*1024:
        return {'status': 'INVALID_RESEARCH_STATUS', 'warnings': ['Research status exceeds bounded read size']}
    try:
        body: dict[str, Any] = json.loads(path.read_text())
        age = (utc_now()-stamp(body['observed_at'])).total_seconds()
        body['collector_age_seconds'] = age
        body['collector_stale'] = not 0 <= age <= 300
        if body['collector_stale']:
            body['warnings'] = [*body.get('warnings', []), 'Learning collector heartbeat is stale']
        error = root/'collector-error.json'
        if error.is_file():
            failure = json.loads(error.read_text())
            if stamp(failure['observed_at']) > stamp(body['observed_at']):
                body['collection_failure'] = failure
                body['warnings'] = [*body.get('warnings', []), 'Latest collection attempt failed']
        body.update(primary_promotion_automatic=False, live_authorized=False, read_only=True)
        return body
    except (ValueError, KeyError, TypeError, OSError):
        return {'status': 'INVALID_RESEARCH_STATUS', 'warnings': ['Research status cannot be verified'], 'live_authorized': False}


def install(app: FastAPI, service: Any, require_user: Any, settings: Any) -> None:
    @app.get('/api/personal-paper/learning', dependencies=[Depends(require_user)])
    async def learning() -> dict[str, Any]:
        import asyncio
        root = Path('/app/reports/learning') if settings.research_root == '/app/research' else Path(settings.research_root).parent/'reports'/'learning'
        body = await asyncio.to_thread(read_status, root)
        record = await service.record()
        body['backend_version'] = app.version
        body['approved_execution_profile'] = record.get('version') if record else None
        body['evidence_labels'] = ['ACTUAL_PRIMARY_PAPER_LEDGER', 'HISTORICAL_MODELED_EXECUTION',
                                   'SHADOW_FORWARD_PREDICTIONS', 'SYNTHETIC_TEST_FIXTURES']
        return body
