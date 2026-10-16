"""Priority applies at the next request boundary; in-flight HTTP is not preempted."""

import asyncio
import heapq
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from itertools import count

request_priority: ContextVar[int] = ContextVar("market_request_priority", default=10)


class PriorityGate:
    def __init__(self) -> None:
        self._busy = False
        self._queue: list[tuple[int, int, asyncio.Future[None]]] = []
        self._sequence = count()

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        future = asyncio.get_running_loop().create_future()
        heapq.heappush(self._queue, (request_priority.get(), next(self._sequence), future))
        self._wake()
        acquired = False
        try:
            await future
            acquired = True
            yield
        finally:
            if acquired:
                self._busy = False
            else:
                # Cancellation can race with dispatch; release a granted slot.
                if future.done() and not future.cancelled():
                    self._busy = False
                future.cancel()
            self._wake()

    def _wake(self) -> None:
        if self._busy:
            return
        while self._queue:
            _, _, future = heapq.heappop(self._queue)
            if not future.cancelled():
                self._busy = True
                future.set_result(None)
                return


@asynccontextmanager
async def protective_priority() -> AsyncIterator[None]:
    token = request_priority.set(0)
    try:
        yield
    finally:
        request_priority.reset(token)
