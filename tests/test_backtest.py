from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from autotrader.backtest import Backtester
from autotrader.decision import DecisionEngine
from autotrader.domain import Candle, TradingPair, utc_now
from autotrader.portfolio import Portfolio
from autotrader.risk import RiskEngine, RiskLimits


def test_backtest_produces_reproducible_report_without_fabricating_profit() -> None:
    pair = TradingPair("BTC-EUR", "BTC", "EUR")
    start = utc_now()
    candles = [
        Candle(pair.symbol, start + timedelta(minutes=index), Decimal("100"), Decimal("103"), Decimal("99"), Decimal("100") + Decimal(index % 3), Decimal("10"))
        for index in range(120)
    ]
    report = Backtester(pair, Portfolio(Decimal("500")), DecisionEngine(RiskEngine(RiskLimits()))).run(candles)
    assert report.trades >= 0
    assert report.total_return > Decimal("-1")
    repeated = Backtester(pair, Portfolio(Decimal("500")), DecisionEngine(RiskEngine(RiskLimits()))).run(candles)
    assert report == repeated


def test_historical_limit_ioc_can_expire_without_manufacturing_fills()->None:
    from datetime import datetime

    from autotrader.domain import OrderType
    from process_support import replay_frame
    frame=replay_frame('qualifying',Decimal('9.92'),qualifying=True)
    candles=[Candle('BTC-EUR',datetime.fromisoformat(c['timestamp']),*[Decimal(c[k]) for k in ('open','high','low','close','volume')],timeframe='5m')
             for c in frame['markets']['BTC-EUR']['candles']]
    candles.append(Candle('BTC-EUR',candles[-1].timestamp+timedelta(minutes=5),Decimal('9.92'),Decimal('9.94'),Decimal('9.90'),Decimal('9.92'),Decimal(100),timeframe='5m'))
    pair=TradingPair('BTC-EUR','BTC','EUR',min_order_quote=Decimal(1))
    engine=DecisionEngine(RiskEngine(RiskLimits()))
    market=Backtester(pair,Portfolio(Decimal(500)),engine).run(candles)
    limit=Backtester(pair,Portfolio(Decimal(500)),engine,entry_order_type=OrderType.LIMIT).run(candles)
    assert market.assumptions['confirmed_fills']>0
    assert limit.assumptions['order_status_counts']['CANCELLED']>0
    assert limit.assumptions['confirmed_fills']==0
    assert limit.net_profit==0 and limit.exposure==0

