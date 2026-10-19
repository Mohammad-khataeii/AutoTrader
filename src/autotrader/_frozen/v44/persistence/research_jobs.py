from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from autotrader.domain import new_id, utc_now
from autotrader.persistence.accounting import aware
from autotrader.persistence.models import SystemStateModel


class ResearchJobsMixin:
    session_factory: Any
    _lock_account: Any

    async def queue_research(self, request: dict[str, Any]) -> str:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            pending = (await session.scalars(select(SystemStateModel).where(SystemStateModel.reason == "historical_research",
                SystemStateModel.state.in_(["QUEUED", "RUNNING"])))).all()
            if len(pending) >= 3:
                raise ValueError("research_queue_capacity_reached")
            job_id = new_id("rjob")
            session.add(SystemStateModel(key=job_id, state="QUEUED", reason="historical_research",
                payload_json=json.dumps({"job_id":job_id, "request":request, "created_at":utc_now().isoformat()})))
            return job_id

    async def claim_research(self, owner: str) -> dict[str, Any] | None:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            rows = (await session.scalars(select(SystemStateModel).where(SystemStateModel.reason == "historical_research",
                SystemStateModel.state.in_(["QUEUED", "RUNNING"])).order_by(SystemStateModel.created_at))).all()
            for row in rows:
                data = json.loads(row.payload_json)
                if row.state == "RUNNING" and aware(datetime.fromisoformat(data["lease_until"])) > utc_now():
                    return None
            if not rows:
                return None
            row = rows[0]
            data = json.loads(row.payload_json)
            data.update(owner=owner, lease_until=(utc_now() + timedelta(seconds=90)).isoformat())
            row.state, row.payload_json = "RUNNING", json.dumps(data)
            return dict(data)

    async def update_research_job(self, job_id: str, owner: str, result: dict[str, Any] | None = None) -> None:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            row = await session.get(SystemStateModel, job_id)
            if row is None:
                return
            data = json.loads(row.payload_json)
            if data.get("owner") != owner or row.state != "RUNNING":
                return
            data["lease_until"] = (utc_now() + timedelta(seconds=90)).isoformat()
            if result is not None:
                data["result"], data["completed_at"] = result, utc_now().isoformat()
                row.state = "FAILED" if "error" in result else "COMPLETED"
            row.payload_json = json.dumps(data)

    async def research_jobs(self) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            rows = (await session.scalars(select(SystemStateModel).where(SystemStateModel.reason == "historical_research").order_by(SystemStateModel.created_at.desc()).limit(30))).all()
            return [{"status":r.state, **json.loads(r.payload_json)} for r in rows]
