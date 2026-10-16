from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from autotrader.persistence.models import AIUsageModel
from autotrader.persistence.repository import PersistentTradingRepository


@pytest.fixture
async def clock(pg_repo: PersistentTradingRepository, monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    await pg_repo.initialize_portfolio(D(500))
    current=[datetime(2026,10,16,0,0,tzinfo=UTC)]
    async def now(session: object) -> datetime:
        return current[0]
    monkeypatch.setattr('autotrader.persistence.ai_budget.quota_now',now)
    return current


async def reserve(repo: PersistentTradingRepository, **kwargs: object) -> str | None:
    return await repo.reserve_ai_budget(D('.01'),'unit-boundary-model','BTC-EUR',{},**kwargs)


async def test_daily_thirty_then_reject_thirty_first(pg_repo: PersistentTradingRepository, clock: list[datetime]) -> None:
    for hour in range(5):
        clock[0]=clock[0].replace(hour=hour)
        accepted=await asyncio.gather(*(reserve(pg_repo) for _ in range(6)))
        assert all(accepted)
    clock[0]+=timedelta(hours=1)
    assert await reserve(pg_repo) is None
    status=await pg_repo.ai_budget_status()
    assert status['daily_used']==30 and status['daily_remaining']==0 and status['rolling_hour_used']==0
    reopened=PersistentTradingRepository(pg_repo.session_factory)
    assert await reserve(reopened) is None
    clock[0]+=timedelta(days=1)
    assert await reserve(reopened)


async def test_rolling_hour_concurrency_restart_and_exact_expiry(pg_repo: PersistentTradingRepository, clock: list[datetime]) -> None:
    requests=await asyncio.gather(*(reserve(pg_repo) for _ in range(20)))
    assert sum(r is not None for r in requests)==6
    reopened=PersistentTradingRepository(pg_repo.session_factory)
    clock[0]+=timedelta(minutes=59,seconds=59)
    assert await reserve(reopened) is None
    clock[0]+=timedelta(seconds=1)
    assert await reserve(reopened)
    assert (await reopened.ai_budget_status())['daily_used']==7
    assert await pg_repo.verify_invariants(D(500))==[]


@pytest.mark.parametrize('last,next_day', [('2024-02-29','2024-03-01'),('2025-02-28','2025-03-01'),('2026-04-30','2026-05-01'),('2026-01-31','2026-02-01')])
async def test_utc_day_and_calendar_month_boundaries_keep_rolling_hour(pg_repo: PersistentTradingRepository,clock: list[datetime],last: str,next_day: str) -> None:
    clock[0]=datetime.fromisoformat(last).replace(hour=23,minute=59,tzinfo=UTC)
    for _ in range(6):
        assert await reserve(pg_repo)
    previous=await pg_repo.ai_budget_status()
    assert previous['monthly_reset_at'].startswith(next_day)
    clock[0]=datetime.fromisoformat(next_day).replace(tzinfo=UTC)
    status=await pg_repo.ai_budget_status()
    assert status['daily_used']==0 and status['rolling_hour_used']==6
    assert D(status['remaining_usd'])==10 and status['requests']==0
    assert await reserve(pg_repo) is None
    clock[0]+=timedelta(hours=1)
    assert await reserve(pg_repo)


async def test_duplicate_unknown_billing_holds_and_audited_reconciliation(pg_repo: PersistentTradingRepository,clock: list[datetime]) -> None:
    request=await reserve(pg_repo,event_fingerprint='same-material-event')
    assert request
    await pg_repo.ai_request_sent(request)
    await pg_repo.finish_ai_request(request,error='TimeoutError')
    clock[0]+=timedelta(hours=2)
    assert await reserve(pg_repo,event_fingerprint='same-material-event') is None
    status=await pg_repo.ai_budget_status()
    assert status['errors'][0]['status']=='OUTCOME_UNKNOWN' and D(status['reserved_usd'])==D('.01')
    await pg_repo.reconcile_ai_request(request,reported_cost=D(0),actor='unit-operator',evidence='Provider billing reference confirms no charge.')
    assert D((await pg_repo.ai_budget_status())['reserved_usd'])==0
    assert await reserve(pg_repo,event_fingerprint='same-material-event')


async def test_monthly_budget_and_provider_cost_bound_violation_fail_closed(pg_repo: PersistentTradingRepository,clock: list[datetime]) -> None:
    request=await pg_repo.reserve_ai_budget(D(10),'unit-model','BTC-EUR',{})
    assert request and await reserve(pg_repo) is None
    await pg_repo.ai_request_sent(request)
    await pg_repo.finish_ai_request(request,input_tokens=10,output_tokens=1,cost=D('10.01'),provider_response_id='unit-response')
    status=await pg_repo.ai_budget_status()
    assert D(status['spent_usd'])==D('10.01') and status['billing_review_required']
    assert D(status['confirmed_spend_usd'])==0  # A token estimate is not an invoice.
    clock[0]=datetime(2026,11,1,tzinfo=UTC)
    assert await reserve(pg_repo) is None  # Pricing review persists across month/restart.
    async with pg_repo.session_factory() as session:
        row=await session.get(AIUsageModel,request)
        assert row.provider_response_id=='unit-response'


async def test_cross_month_reservation_cannot_submit_in_wrong_budget_window(pg_repo: PersistentTradingRepository,clock: list[datetime]) -> None:
    clock[0]=datetime(2026,10,31,23,59,tzinfo=UTC)
    request=await reserve(pg_repo)
    assert request
    clock[0]+=timedelta(minutes=2)
    with pytest.raises(ValueError,match='before submission'):
        await pg_repo.ai_request_sent(request)
    async with pg_repo.session_factory() as session:
        row=await session.get(AIUsageModel,request)
        assert row.status=='RESERVED'


async def test_call_counters_preserve_sent_and_failed_usage_details(pg_repo: PersistentTradingRepository,clock: list[datetime]) -> None:
    request=await pg_repo.reserve_ai_budget(D('.1'),'fixture-model','BTC-EUR',{},estimated_input_tokens=123,reserved_output_tokens=456,category='portfolio_risk')
    assert request
    await pg_repo.ai_request_sent(request)
    await pg_repo.finish_ai_request(request,input_tokens=100,output_tokens=20,cached_tokens=10,cost=D('.02'),error='invalid_structured_response')
    await pg_repo.finish_ai_request(request,cost=D('.02'))
    async with pg_repo.session_factory() as session:
        rows=(await session.scalars(select(AIUsageModel))).all()
        assert len(rows)==1 and rows[0].request_category=='portfolio_risk'
        assert rows[0].estimated_input_tokens==123 and rows[0].reserved_output_tokens==456
    status=await pg_repo.ai_budget_status()
    assert status['daily_used']==1 and status['rolling_hour_used']==1 and D(status['spent_usd'])==D('.02')


async def test_portfolio_review_capacity_is_protected(pg_repo: PersistentTradingRepository,clock: list[datetime]) -> None:
    for _ in range(5):
        assert await reserve(pg_repo,portfolio_reserve_daily=3,portfolio_reserve_hourly=1)
    assert await reserve(pg_repo,portfolio_reserve_daily=3,portfolio_reserve_hourly=1) is None
    assert await reserve(pg_repo,category='portfolio_risk')
    assert await reserve(pg_repo,category='portfolio_risk') is None
