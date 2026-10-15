from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from autotrader.domain import new_id, utc_now
from autotrader.persistence.accounting import aware
from autotrader.persistence.models import SystemStateModel


class AIEventMixin:
    session_factory: Any
    _lock_account: Any

    async def claim_ai_event(self, key: str) -> tuple[str | None, dict[str, Any] | None]:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            row = await session.get(SystemStateModel, key)
            payload = json.loads(row.payload_json) if row else {}
            expires = payload.get("expires_at")
            if expires:
                from datetime import datetime
                if aware(datetime.fromisoformat(expires)) > utc_now():
                    return None, payload.get("assessment") if row.state == "READY" else None
            claim = new_id("aie")
            encoded = json.dumps({"claim": claim, "expires_at": (utc_now() + timedelta(seconds=60)).isoformat()})
            if row is None:
                session.add(SystemStateModel(key=key, state="PENDING", reason="event_driven_ai", payload_json=encoded))
            else:
                row.state, row.reason, row.payload_json = "PENDING", "event_driven_ai", encoded
            return claim, None

    async def finish_ai_event(self, key: str, claim: str, assessment: dict[str, Any], *, ttl: int) -> None:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            row = await session.get(SystemStateModel, key)
            if row is None or json.loads(row.payload_json).get("claim") != claim:
                return
            row.state = "READY"
            row.payload_json = json.dumps({"claim": claim, "assessment": assessment,
                "expires_at": (utc_now() + timedelta(seconds=ttl)).isoformat()})
