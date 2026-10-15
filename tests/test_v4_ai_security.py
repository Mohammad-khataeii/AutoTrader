from __future__ import annotations

import asyncio
from dataclasses import replace
from decimal import Decimal as D

from autotrader.ai import EventDrivenAIProvider, MockAIProvider
from autotrader.api.security import AuthenticationThrottle
from autotrader.persistence.repository import PersistentTradingRepository
from test_v4_regimes_strategies import features


async def test_persistent_event_cache_singleflight_and_material_change(pg_repo: PersistentTradingRepository) -> None:
    await pg_repo.initialize_portfolio(D(500))
    f = features()
    f.metadata["last_close"] = D(103)
    from autotrader.research.strategies import V4StrategyEngine
    signals = V4StrategyEngine().generate(f)
    class Boundary(MockAIProvider):
        calls = 0
        async def assess(self, *args, **kwargs):
            self.calls += 1
            await asyncio.sleep(.05)
            return await super().assess(*args, **kwargs)
    boundary = Boundary()
    provider = EventDrivenAIProvider(boundary, pg_repo, "mock-v1")
    results = await asyncio.gather(*(provider.assess(f, signals) for _ in range(5)))
    assert boundary.calls == 1 and any(not r.failed for r in results)
    restarted = EventDrivenAIProvider(boundary, PersistentTradingRepository(pg_repo.session_factory), "mock-v1")
    cached = await restarted.assess(f, signals)
    assert boundary.calls == 1 and "cache hit" in cached.explanation and cached.tokens_used == 0
    changed = replace(f, momentum=D(".04"))
    await restarted.assess(changed, signals)
    assert boundary.calls == 2
    skipped = await restarted.assess(f, [])
    assert boundary.calls == 2 and skipped.provider == "event-gate"
    assert (await pg_repo.ai_budget_status())["requests"] == 0


def test_failed_auth_throttle_and_bounded_memory() -> None:
    throttle = AuthenticationThrottle()
    assert [throttle.failure("client") for _ in range(5)] == [None] * 5
    assert 1 <= throttle.failure("client") <= 60
    for i in range(1500):
        throttle.failure(str(i))
    assert len(throttle.clients) == 1024
