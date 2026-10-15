from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque


class AuthenticationThrottle:
    """Bounded per-client failed-auth throttle for the single-process API deployment."""
    def __init__(self, attempts: int = 5, window_seconds: int = 60) -> None:
        self.attempts, self.window = attempts, window_seconds
        self.clients: OrderedDict[str, deque[float]] = OrderedDict()
        self.lock = threading.Lock()

    def retry_after(self, client: str) -> int | None:
        now = time.monotonic()
        with self.lock:
            events = self.clients.get(client)
            if events is None:
                return None
            while events and events[0] <= now - self.window:
                events.popleft()
            return max(1, math.ceil(events[0] + self.window - now)) if len(events) >= self.attempts else None

    def failure(self, client: str) -> int | None:
        now = time.monotonic()
        with self.lock:
            events = self.clients.setdefault(client, deque())
            self.clients.move_to_end(client)
            while events and events[0] <= now - self.window:
                events.popleft()
            retry = max(1, math.ceil(events[0] + self.window - now)) if len(events) >= self.attempts else None
            if retry is None:
                events.append(now)
            while len(self.clients) > 1024:
                self.clients.popitem(last=False)
            return retry
