"""Read compact episode inputs without transferring historical trade-plan payloads."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# json_to_record parses each selected event once on the database side. The
# window/limit applies before JSON expansion; neither full evidence nor a JSON
# aggregate is returned to the application. Recent event pages retain evidence.
PROJECTION = text("""
SELECT event.event_id, event.observed_at, event.symbol, event.strategy_id,
       CAST(event.horizon_seconds AS text) AS horizon_seconds_json, event.rejection,
       CAST(event.evidence -> 'entry_eligible' AS text) AS entry_eligible_json
FROM (
    SELECT key, created_at, payload_json
    FROM system_state
    WHERE key LIKE 'raoe_event:%' AND created_at >= :since
    ORDER BY created_at, key
    LIMIT :row_limit
) AS selected
CROSS JOIN LATERAL json_to_record(CAST(selected.payload_json AS json)) AS event(
    event_id text, observed_at text, symbol text, strategy_id text,
    horizon_seconds json, rejection text, evidence json
)
ORDER BY selected.created_at, selected.key
""")


async def project_episode_events(session: AsyncSession, since: datetime,
                                 limit: int = 10000) -> list[dict[str, Any]]:
    if since.tzinfo is None or not 1 <= limit <= 10000:
        raise ValueError('bounded_aware_episode_window_required')
    if session.get_bind().dialect.name != 'postgresql':
        raise ValueError('isolated_personal_history_requires_postgresql')
    rows = (await session.execute(PROJECTION, {'since': since, 'row_limit': limit})).mappings()
    events = []
    for row in rows:
        event = {k: row[k] for k in ('event_id', 'observed_at', 'symbol', 'strategy_id', 'rejection')
                 if row[k] is not None}
        if row['horizon_seconds_json'] is not None:
            event['horizon_seconds'] = json.loads(row['horizon_seconds_json'])
        raw = row['entry_eligible_json']
        event['evidence'] = {'entry_eligible': json.loads(raw) if raw is not None else False}
        events.append(event)
    return events
