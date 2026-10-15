from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from autotrader.clock import at
from autotrader.domain import Candle
from autotrader.indicators import higher_timeframe_context


def test_confirmation_uses_completed_aligned_bars_without_future_leakage()->None:
    start=datetime(2026,10,14,0,0,tzinfo=UTC)
    bars=[Candle('BTC-EUR',start+timedelta(minutes=i*5),Decimal(10),Decimal(11),Decimal(9),
        Decimal(10)+Decimal(i)/1000,Decimal(1),timeframe='5m') for i in range(240)]
    with at(start+timedelta(hours=20)):
        context=higher_timeframe_context(bars)
        assert context['available'] is True and context['timeframe']=='20m'
        assert context['observations']==60
        future=Candle('BTC-EUR',start+timedelta(hours=21),Decimal(10000),Decimal(10000),Decimal(10000),Decimal(10000),Decimal(1),timeframe='5m')
        assert higher_timeframe_context([*bars,future])==context


def test_incomplete_confirmation_history_vetoes_entries()->None:
    start=datetime(2026,10,14,0,0,tzinfo=UTC)
    bars=[Candle('BTC-EUR',start+timedelta(minutes=i*5),Decimal(10),Decimal(11),Decimal(9),Decimal(10),Decimal(1),timeframe='5m') for i in range(50)]
    with at(start+timedelta(hours=20)):
        context=higher_timeframe_context(bars)
        assert context['available'] is False and context['veto'] is True
