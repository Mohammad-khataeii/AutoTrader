from __future__ import annotations

import itertools
from dataclasses import dataclass
from decimal import Decimal
from math import sqrt

from autotrader.decision import DecisionEngine
from autotrader.domain import Candle, OrderBook, OrderBookLevel, OrderType, Side, TradingPair
from autotrader.indicators import calculate_features
from autotrader.paper_broker import PaperBroker
from autotrader.portfolio import Portfolio
from autotrader.strategies import BreakoutStrategyEngine


@dataclass(frozen=True)
class BacktestReport:
    net_profit: Decimal
    total_return: Decimal
    max_drawdown: Decimal
    profit_factor: Decimal
    win_rate: Decimal
    expectancy: Decimal
    sharpe_ratio: Decimal
    exposure: Decimal
    turnover: Decimal
    trades: int


class Backtester:
    def __init__(self, pair: TradingPair, portfolio: Portfolio, decision_engine: DecisionEngine) -> None:
        self.pair = pair
        self.portfolio = portfolio
        self.decision_engine = decision_engine
        self.strategy_engine = BreakoutStrategyEngine()
        self.broker = PaperBroker(portfolio)

    def run(self, candles: list[Candle]) -> BacktestReport:
        ordered = sorted(candles, key=lambda candle: candle.timestamp)
        equity_curve: list[Decimal] = [self.portfolio.cash]
        realized: list[Decimal] = []
        last_cash = self.portfolio.cash
        for index in range(50, len(ordered)):
            window = ordered[: index + 1]
            latest = window[-1]
            book = _book_from_candle(latest)
            features = calculate_features(window)
            features.metadata["last_price"] = latest.close
            signals = self.strategy_engine.generate(features)
            decision = self.decision_engine.decide(self.pair, features, signals, self.portfolio, ai_assessment=None)
            if decision.accepted and decision.entry_price is not None:
                self.broker.submit_order(
                    self.pair,
                    Side.BUY,
                    OrderType.MARKET,
                    decision.proposed_quantity,
                    decision.proposed_quote_amount,
                    book,
                    decision_id=decision.decision_id,
                )
            self._mark_exits(latest, book)
            equity = self.portfolio.cash + sum(position.quantity * latest.close for position in self.portfolio.positions.values() if position.closed_at is None)
            if self.portfolio.cash != last_cash:
                realized.append(self.portfolio.cash - last_cash)
                last_cash = self.portfolio.cash
            equity_curve.append(equity)
        return _report(equity_curve, realized, len(self.broker.fills))

    def _mark_exits(self, latest: Candle, book: OrderBook) -> None:
        position = self.portfolio.positions.get(self.pair.symbol)
        if position is None or position.closed_at is not None or position.quantity <= 0:
            return
        stop = position.protective_stop or position.average_entry_price * Decimal("0.97")
        target = position.average_entry_price * Decimal("1.03")
        if latest.low <= stop or latest.high >= target:
            self.broker.submit_order(self.pair, Side.SELL, OrderType.MARKET, position.quantity, Decimal("0"), book)


def _book_from_candle(candle: Candle) -> OrderBook:
    spread = candle.close * Decimal("0.001")
    qty = Decimal("999")
    return OrderBook(
        candle.symbol,
        candle.timestamp,
        bids=(OrderBookLevel(candle.close - spread, qty),),
        asks=(OrderBookLevel(candle.close + spread, qty),),
        source="backtest-synthetic-spread",
    )


def _report(equity_curve: list[Decimal], realized: list[Decimal], trades: int) -> BacktestReport:
    start = equity_curve[0]
    end = equity_curve[-1]
    peak = start
    max_drawdown = Decimal("0")
    returns: list[float] = []
    for prev, current in itertools.pairwise(equity_curve):
        peak = max(peak, current)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - current) / peak)
        if prev > 0:
            returns.append(float((current - prev) / prev))
    winners = [value for value in realized if value > 0]
    losers = [abs(value) for value in realized if value < 0]
    gross_win = sum(winners, Decimal("0"))
    gross_loss = sum(losers, Decimal("0"))
    avg_return = sum(returns) / len(returns) if returns else 0.0
    variance = sum((item - avg_return) ** 2 for item in returns) / len(returns) if returns else 0.0
    sharpe = Decimal(str((avg_return / sqrt(variance) * sqrt(365)) if variance > 0 else 0))
    expectancy = (sum(realized, Decimal("0")) / Decimal(len(realized))) if realized else Decimal("0")
    return BacktestReport(
        net_profit=end - start,
        total_return=(end - start) / start if start > 0 else Decimal("0"),
        max_drawdown=max_drawdown,
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else Decimal("0"),
        win_rate=(Decimal(len(winners)) / Decimal(len(realized))) if realized else Decimal("0"),
        expectancy=expectancy,
        sharpe_ratio=sharpe,
        exposure=Decimal("0"),
        turnover=Decimal(trades),
        trades=trades,
    )
