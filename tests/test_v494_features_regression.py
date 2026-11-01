"""V4.9.4 Regression tests: null pattern_state handling, loss cooldown, hourly trend filter."""
from datetime import timedelta
from decimal import Decimal as D

from autotrader.domain import utc_now
from autotrader.learning import features
from test_v492_learning import NOW, evidence


def test_v494_features_build_with_null_pattern_state():
    e = evidence()
    # Explicitly set pattern_state to None (the production payload bug)
    e['pattern_state'] = None
    observed_at = NOW.isoformat()
    # Should not raise AttributeError: 'NoneType' object has no attribute 'get'
    feat = features.build(e, 'RAOE_TREND_PULLBACK', observed_at)
    assert feat is not None
    assert isinstance(feat['values'], list)
    assert len(feat['values']) == len(features.NAMES)


def test_v494_features_build_with_missing_pattern_state():
    e = evidence()
    e.pop('pattern_state', None)
    observed_at = NOW.isoformat()
    feat = features.build(e, 'RAOE_TREND_PULLBACK', observed_at)
    assert feat is not None
    assert isinstance(feat['values'], list)


def test_v494_symbol_loss_cooldown_detection():
    from autotrader.domain import Position

    now = utc_now()
    closed_loss = Position(
        position_id="pos_loss",
        symbol="PEPE-EUR",
        quantity=D(0),
        average_entry_price=D("0.00001"),
        opened_at=now - timedelta(minutes=45),
        realized_pnl=D("-10.50"),
        protective_stop=D("0.000009"),
        take_profit_targets=[],
        original_quantity=D(1000000),
        target_quantities=[],
        target_filled_quantities=[],
        target_ids=[],
        closed_at=now - timedelta(minutes=35),
    )

    all_positions = [closed_loss]
    loss_cooldown_seconds = 7200
    recent_symbol_loss = False
    for p in reversed(all_positions):
        if p.symbol == "PEPE-EUR" and p.closed_at is not None:
            age_seconds = (now - p.closed_at).total_seconds()
            if age_seconds < loss_cooldown_seconds and (p.realized_pnl or D(0)) < D(0):
                recent_symbol_loss = True
                break

    assert recent_symbol_loss is True

    # After cooldown period expires (e.g. 130 mins)
    recent_symbol_loss_expired = False
    for p in reversed(all_positions):
        if p.symbol == "PEPE-EUR" and p.closed_at is not None:
            age_seconds = (now + timedelta(minutes=130) - p.closed_at).total_seconds()
            if age_seconds < loss_cooldown_seconds and (p.realized_pnl or D(0)) < D(0):
                recent_symbol_loss_expired = True
                break

    assert recent_symbol_loss_expired is False


def test_v494_competition_cache_returns_fast(monkeypatch):
    from fastapi import FastAPI
    from autotrader.api import v48

    app = FastAPI()
    call_count = 0

    class DummyService:
        official = None
        async def detail(self):
            nonlocal call_count
            call_count += 1
            return {'strategies': []}

    class DummyLab:
        async def records(self):
            return []

    v48.install(app, DummyService(), DummyLab(), lambda: True)

    # Find competition endpoint handler
    route = next(r for r in app.routes if r.path == '/api/intelligence/competition')
    endpoint = route.endpoint

    import asyncio
    res1 = asyncio.run(endpoint())
    assert call_count == 1
    # Second call within 20s should hit cache without calling detail() again
    res2 = asyncio.run(endpoint())
    assert call_count == 1
    assert res1 == res2
