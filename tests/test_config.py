from __future__ import annotations

import pytest
from pydantic import ValidationError

from autotrader.config import Settings


def test_live_trading_cannot_be_enabled() -> None:
    with pytest.raises(ValidationError):
        Settings(live_trading_enabled=True)

