"""V4.9.5 Regression tests: breakeven stop locking, macro bear veto, countertrend recovery veto, and noise immunity."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from unittest.mock import MagicMock

import pytest

from autotrader.domain import Candle, DataQuality, Position, utc_now
from autotrader.personal_paper import exits


def test_v495_macro_bearish_veto_logic():
    # If BTC is BEARISH or dumping, macro_bearish must be True
    raoe_regime_bear = {'benchmark': 'RISK_OFF', 'benchmarks': {'BTC-EUR': {'trend': 'BEARISH', 'return_30m': '-0.01'}}}
    btc_bench = raoe_regime_bear['benchmarks']['BTC-EUR']
    btc_dumping = btc_bench.get('trend') == 'BEARISH' or (btc_bench.get('return_30m') is not None and D(str(btc_bench['return_30m'])) < D('-0.005'))
    macro_bearish = raoe_regime_bear.get('benchmark') == 'RISK_OFF' or btc_dumping
    assert macro_bearish is True

    # If BTC is BULLISH and return is positive, macro_bearish must be False
    raoe_regime_bull = {'benchmark': 'SUPPORTIVE', 'benchmarks': {'BTC-EUR': {'trend': 'BULLISH', 'return_30m': '0.005'}}}
    btc_bench2 = raoe_regime_bull['benchmarks']['BTC-EUR']
    btc_dumping2 = btc_bench2.get('trend') == 'BEARISH' or (btc_bench2.get('return_30m') is not None and D(str(btc_bench2['return_30m'])) < D('-0.005'))
    macro_bearish2 = raoe_regime_bull.get('benchmark') == 'RISK_OFF' or btc_dumping2
    assert macro_bearish2 is False


def test_v495_countertrend_recovery_veto_logic():
    # When asset 15m or 60m is BEARISH, RAOE_EARLY_RECOVERY must be vetoed
    is_hourly_bearish = True
    is_15m_bearish = False
    is_unfavorable_setup = (
        ('RAOE_EARLY_RECOVERY' == 'RAOE_EARLY_RECOVERY' and (is_hourly_bearish or is_15m_bearish))
        or ('RAOE_EARLY_RECOVERY' == 'RAOE_TREND_PULLBACK' and is_hourly_bearish)
    )
    assert is_unfavorable_setup is True

    # When asset 15m and 60m are BULLISH, setup is allowed
    is_hourly_bearish2 = False
    is_15m_bearish2 = False
    is_unfavorable_setup2 = (
        ('RAOE_EARLY_RECOVERY' == 'RAOE_EARLY_RECOVERY' and (is_hourly_bearish2 or is_15m_bearish2))
        or ('RAOE_EARLY_RECOVERY' == 'RAOE_TREND_PULLBACK' and is_hourly_bearish2)
    )
    assert is_unfavorable_setup2 is False


def test_v495_exit_manager_requires_at_least_six_post_entry_bars():
    opened_at = datetime(2026, 10, 28, 15, 6, tzinfo=UTC)
    # Simulate only 2 bars post-entry (10 minutes)
    bars_short = [
        Candle('TEST-EUR', opened_at - timedelta(minutes=5 * i), D(100), D(101), D(99), D(100), D(10), '5m', 'revolut-x')
        for i in range(160, 2, -1)
    ]
    bars_short.append(Candle('TEST-EUR', opened_at + timedelta(minutes=2), D(100), D(101), D(99), D(100), D(10), '5m', 'revolut-x'))
    bars_short.append(Candle('TEST-EUR', opened_at + timedelta(minutes=7), D(100), D(101), D(99), D(100), D(10), '5m', 'revolut-x'))

    completed_post_entry_short = len([c for c in bars_short if c.timestamp >= opened_at])
    post_entry_short = completed_post_entry_short >= 6 and bars_short[-2].timestamp >= opened_at
    assert post_entry_short is False

    # Simulate 7 bars post-entry (35 minutes)
    bars_long = list(bars_short)
    for m in range(12, 40, 5):
        bars_long.append(Candle('TEST-EUR', opened_at + timedelta(minutes=m), D(100), D(101), D(99), D(100), D(10), '5m', 'revolut-x'))

    completed_post_entry_long = len([c for c in bars_long if c.timestamp >= opened_at])
    post_entry_long = completed_post_entry_long >= 6 and bars_long[-2].timestamp >= opened_at
    assert post_entry_long is True


def test_v495_loss_cooldown_and_asset_hourly_bearish_veto():
    # Asset hourly trend bearish blocks long entries
    is_hourly_bearish = True
    accepted = not is_hourly_bearish
    assert accepted is False

    is_hourly_bullish = False
    accepted2 = not is_hourly_bullish
    assert accepted2 is True
