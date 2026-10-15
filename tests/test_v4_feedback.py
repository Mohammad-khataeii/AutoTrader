from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

from autotrader.domain import DecisionAction, TradingDecision, new_id, utc_now
from autotrader.persistence.models import MarketCandle
from autotrader.persistence.repository import PersistentTradingRepository


async def test_feedback_horizon_excludes_later_move_and_cannot_change_ledger(pg_repo: PersistentTradingRepository) -> None:
    await pg_repo.initialize_portfolio(D(500))
    start = utc_now() - timedelta(hours=7)
    decision = TradingDecision(new_id("dec"), "BTC-EUR", start, DecisionAction.WAIT, [], None,
        D(0), D(0), D(100), D(98), (), False, "No qualifying signal", "Unit feedback observation; no order")
    await pg_repo.store_analysis([], None, decision)
    async with pg_repo.session_factory() as session, session.begin():
        for i in range(73):
            # The final large move is outside the specified six-hour horizon.
            session.add(MarketCandle(observation_key=f"unit-feedback-{i}", symbol="BTC-EUR", timeframe="5m",
                timestamp=start+timedelta(minutes=i*5), open=D(100), high=D(103 if i<72 else 1000),
                low=D(99), close=D(100), volume=D(1), source="unit-feedback-fixture"))
    await pg_repo.refresh_opportunity_feedback()
    reopened = PersistentTradingRepository(pg_repo.session_factory)
    await reopened.refresh_opportunity_feedback()
    result = await reopened.opportunity_analytics()
    assert len(result["feedback"]) == 1
    feedback = result["feedback"][0]
    assert feedback["subsequent_completed_bars"] == 72
    assert D(feedback["observed_mfe"]) == D(".03")
    assert feedback["category"] == "NO_QUALIFYING_SIGNAL"
    assert result["mature_feedback_backlog"] == 0
    assert D((await reopened.snapshot())["cash"]) == 500
    assert await reopened.verify_invariants(D(500)) == []
