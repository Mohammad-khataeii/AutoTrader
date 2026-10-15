from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest

from autotrader.api.main import create_app
from autotrader.clock import at
from autotrader.domain import utc_now
from autotrader.persistence.repository import PersistentTradingRepository


async def test_durable_research_job_singleflight_lease_and_queue_capacity(pg_repo: PersistentTradingRepository) -> None:
    await pg_repo.initialize_portfolio(D(500))
    request = {"strategies":["A_TREND_PULLBACK"], "timeframes":["1d"], "assets":["BTC"]}
    for _ in range(3):
        await pg_repo.queue_research(request)
    with pytest.raises(ValueError, match="capacity"):
        await pg_repo.queue_research(request)
    claims = await asyncio.gather(*(pg_repo.claim_research(str(i)) for i in range(3)))
    assert sum(c is not None for c in claims) == 1
    claimed = next(c for c in claims if c)
    reopened = PersistentTradingRepository(pg_repo.session_factory)
    assert await reopened.claim_research("new-owner") is None
    with at(utc_now() + timedelta(seconds=91)):
        reclaimed = await reopened.claim_research("new-owner")
        assert reclaimed and reclaimed["job_id"] == claimed["job_id"]
        await reopened.update_research_job(claimed["job_id"], claimed["owner"], {"run_id":"stale-owner"})
        assert not any(j["status"] == "COMPLETED" for j in await reopened.research_jobs())
        await reopened.update_research_job(claimed["job_id"], "new-owner", {"run_id":"verified-test-result"})
        assert sum(j["status"] == "COMPLETED" for j in await reopened.research_jobs()) == 1
    assert await reopened.verify_invariants(D(500)) == []


async def test_authenticated_api_throttles_guesses_and_validates_research_requests(pg_repo: PersistentTradingRepository, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", pg_repo.test_database_url)  # type: ignore[attr-defined]
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-secret-only")
    monkeypatch.setenv("RESEARCH_ROOT", str(tmp_path))
    await pg_repo.initialize_portfolio(D(500))
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        wrong = [await client.get("/api/settings", auth=("admin", "wrong")) for _ in range(6)]
        assert [r.status_code for r in wrong] == [401]*5+[429]
        assert 1 <= int(wrong[-1].headers["Retry-After"]) <= 60
        auth = ("admin", "test-secret-only")
        # A locked client cannot continue guessing and use200 as a success oracle.
        assert (await client.get("/api/settings", auth=auth)).status_code == 429
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("another-client",123)), base_url="http://test") as client:
        assert (await client.get("/api/settings", auth=auth)).status_code == 200
        invalid = await client.post("/api/research/jobs", auth=auth, json={"assets":["BTC-USD"]})
        assert invalid.status_code == 400
        invalid_grid = await client.post("/api/research/jobs", auth=auth, json={"grid":[{"stop_atr":0}]})
        assert invalid_grid.status_code == 422
        queued = await client.post("/api/research/jobs", auth=auth, json={"strategies":["A_TREND_PULLBACK"], "assets":["BTC"], "timeframes":["1d"]})
        assert queued.status_code == 202 and queued.json()["status"] == "QUEUED"
        assert (await client.get("/api/execution", auth=auth)).json()["executable_bid_equity_after_exit_costs"] == "500.000000000000"
        assert (await client.get("/api/intelligence", auth=auth)).status_code == 200
        assert (await client.get("/api/research/runs/research-20261015T000000/secrets.json", auth=auth)).status_code == 400
