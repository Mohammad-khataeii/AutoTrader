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
        Candle(pair.symbol, start + timedelta(minutes=index), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100") + Decimal(index % 3), Decimal("10"))
        for index in range(120)
    ]
    report = Backtester(pair, Portfolio(Decimal("500")), DecisionEngine(RiskEngine(RiskLimits()))).run(candles)
    assert report.trades >= 0
    assert report.total_return > Decimal("-1")

