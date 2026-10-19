"""Bounded retries for rolled-back PostgreSQL conflicts and ambiguous disconnects.

Only methods with durable idempotency keys may use this decorator.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any

from sqlalchemy.exc import DBAPIError


def retry_economic[T](function: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
    @wraps(function)
    async def wrapped(*args: Any, **kwargs: Any) -> T:
        for attempt in range(4):
            try:
                return await function(*args, **kwargs)
            except DBAPIError as exc:
                original = exc.orig
                code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
                transient = code in {"40001", "40P01", "08000", "08003", "08006", "57P01"} or exc.connection_invalidated
                if not transient or attempt == 3:
                    raise
                await asyncio.sleep(0.05 * 2 ** attempt)
        raise AssertionError("Unreachable retry branch")
    return wrapped
