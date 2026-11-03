"""Authenticated access to the isolated simulated perpetuals experiment."""
from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, StrictBool

from autotrader.config import Settings
from autotrader.perpetuals.service import Perpetuals, available


class EntryControl(BaseModel):
    enabled: StrictBool


def install(app: FastAPI, lab: Perpetuals, settings: Settings, require_user: Callable[..., Any]) -> None:
    @app.get("/api/perpetuals", dependencies=[Depends(require_user)])
    async def snapshot():
        return await lab.snapshot(enabled=available(settings))

    @app.post("/api/perpetuals/entries", dependencies=[Depends(require_user)])
    async def entries(request: EntryControl):
        if not available(settings):
            raise HTTPException(409, "Perpetuals paper mode is disabled")
        if not await lab.control(request.enabled):
            raise HTTPException(409, "Market data is not ready or the worker updated the account; try again")
        return {"entries_enabled": request.enabled}
