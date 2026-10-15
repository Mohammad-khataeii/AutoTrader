"""One clock source for runtime and deterministic historical replay."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

_event_time: ContextVar[datetime | None] = ContextVar("autotrader_event_time", default=None)


def now() -> datetime:
    return _event_time.get() or datetime.now(tz=UTC)


@contextmanager
def at(timestamp: datetime) -> Iterator[None]:
    if timestamp.tzinfo is None:
        raise ValueError("Replay clock requires an aware timestamp.")
    token = _event_time.set(timestamp)
    try:
        yield
    finally:
        _event_time.reset(token)
