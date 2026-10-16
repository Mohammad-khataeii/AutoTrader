from __future__ import annotations

import pytest
from pydantic import ValidationError

from autotrader.config import Settings


def test_live_trading_cannot_be_enabled() -> None:
    with pytest.raises(ValidationError):
        Settings(live_trading_enabled=True)



def test_acceptance_cannot_use_production_paper_database() -> None:
    with pytest.raises(ValidationError,match='isolated test database'):
        Settings(environment='test',database_url='postgresql+asyncpg://paper:placeholder@localhost/autotrader')


@pytest.mark.parametrize('overrides',[{'ai_max_analyses_per_day':31},{'ai_max_analyses_per_hour':7},{'ai_monthly_budget_usd':11},{'initial_cash_eur':'NaN'}])
def test_invalid_quota_and_nonfinite_finance_configuration_fails_closed(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(**overrides)
