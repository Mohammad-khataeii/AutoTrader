"""Read-only reporting and serialized active-shadow admission at the API boundary."""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import text

from autotrader.learning.consolidation_ops import CAP_LOCK, require_capacity


@asynccontextmanager
async def shadow_admission(repository, lab, *, experiment_id=None, request_id=None):
    async with repository.session_factory() as session, session.begin():
        if session.bind.dialect.name=="postgresql":
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"),{"key":CAP_LOCK})
        if request_id:
            experiment_id=await session.scalar(text("SELECT experiment_id FROM shadow_experiments WHERE request_id=:id"),
                                               {"id":request_id})
        records=await lab.records()
        # Existing request IDs are immutable; a retry does not acquire another slot.
        if not (request_id and experiment_id):
            require_capacity(records,os.getenv("PERSONAL_PLAN_ACTIVE_SHADOW_CAP","3"),existing=experiment_id)
        yield


def install(app, settings, require_user):
    @app.get("/api/research/consolidation",dependencies=[Depends(require_user)])
    def research_consolidation():
        from autotrader.learning.consolidation_service import root_for
        path=root_for(settings.research_root)/"consolidation-status.json"
        try:
            with path.open("rb") as stream: raw=stream.read(512*1024+1)
            if len(raw)>512*1024: raise ValueError("research_report_size_limit")
            body=json.loads(raw)
            if body.get("schema")!="consolidation-status/1":raise ValueError("research_report_schema")
            collected=(body.get("collection") or {}).get("observed_at")
            age=None
            if collected:
                age=(datetime.now(UTC)-datetime.fromisoformat(collected)).total_seconds()
            body["collector_age_seconds"]=age
            body["collection_stale"]=age is not None and not 0<=age<=300
            return {**body,"read_only":True,"live_authorized":False,"automatic_promotion":False}
        except FileNotFoundError:
            return {"status":"WAITING_FOR_FULL_READ_ONLY_COLLECTION","read_only":True,
                    "live_authorized":False,"automatic_promotion":False}
        except (ValueError,TypeError,OSError):
            return {"status":"RESEARCH_REPORT_UNAVAILABLE","read_only":True,
                    "live_authorized":False,"automatic_promotion":False}
