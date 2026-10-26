"""Read-only primary paper views; controls act only on its isolated ledger."""
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException

from autotrader.api.dashboard import install as install_dashboard
from autotrader.api.paper_activity import activity_feed
from autotrader.api.paper_analytics import attributed_summary
from autotrader.personal_paper.service import PersonalPaperService


def install(app: FastAPI, service: PersonalPaperService, require_user: Any) -> None:
    install_dashboard(app, service, require_user)
    @app.get('/api/personal-paper', dependencies=[Depends(require_user)])
    async def paper() -> dict[str, Any]:
        return await attributed_summary(service)

    @app.get('/api/personal-paper/activity', dependencies=[Depends(require_user)])
    async def activity() -> dict[str, Any]:
        return await activity_feed(service)

    @app.get('/api/personal-paper/research', dependencies=[Depends(require_user)])
    async def research() -> dict[str, Any]:
        paths = [Path('/app/evidence/v47/research-results.json'), Path(__file__).parents[3]/'docs/evidence/v4_7/research-results.json']
        for path in paths:
            if path.is_file():
                return dict(json.loads(path.read_text()))
        return {'status':'RESEARCH_NOT_PUBLISHED','results':[]}

    @app.post('/api/personal-paper/control/{action}', dependencies=[Depends(require_user)])
    async def control(action: Literal['pause', 'resume', 'emergency']) -> dict[str, Any]:
        repo = await service.repository()
        if not repo:
            raise HTTPException(409, 'Paper portfolio not initialized')
        try:
            await repo.set_control(action)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return await attributed_summary(service)
