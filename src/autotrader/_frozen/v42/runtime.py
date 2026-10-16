from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from autotrader.ai import AIProviderClient
from autotrader.decision import DecisionEngine
from autotrader.domain import (
    AIAssessment,
    Candle,
    DecisionAction,
    Order,
    OrderBook,
    RiskEvaluation,
    StrategySignal,
    TradingDecision,
    TradingPair,
)
from autotrader.execution_gateway import PaperExecutionGateway
from autotrader.indicators import calculate_features, higher_timeframe_context
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.portfolio import Portfolio
from autotrader.risk import RiskEngine
from autotrader.strategies import BreakoutStrategyEngine


@dataclass(frozen=True)
class RuntimeCycleResult:
    signals: list[StrategySignal]
    ai_assessment: AIAssessment
    decision: TradingDecision
    risk_evaluation: RiskEvaluation | None
    order: Order | None


class PaperTradingRuntime:
    def __init__(
        self,
        repository: PersistentTradingRepository,
        strategy_engine: BreakoutStrategyEngine,
        decision_engine: DecisionEngine,
        risk_engine: RiskEngine,
        ai_provider: AIProviderClient,
        initial_cash: Decimal,
        execution_gateway: PaperExecutionGateway,
    ) -> None:
        self.repository = repository
        self.strategy_engine = strategy_engine
        self.decision_engine = decision_engine
        self.risk_engine = risk_engine
        self.ai_provider = ai_provider
        self.initial_cash = initial_cash
        self.execution_gateway = execution_gateway

    async def run_market_cycle(
        self,
        pair: TradingPair,
        candles: list[Candle],
        order_book: OrderBook,
        idempotency_key: str,
        entries_today: int = 0,
    ) -> RuntimeCycleResult:
        await self.repository.initialize_portfolio(self.initial_cash)
        persisted_snapshot = await self.repository.snapshot()
        portfolio = Portfolio(Decimal(persisted_snapshot["available_cash"]), quote_asset=self.repository.quote_asset)
        portfolio.balances[portfolio.quote_asset].reserved = Decimal(persisted_snapshot["reserved_cash"])
        for position in await self.repository.list_positions():
            if position.closed_at is None and position.quantity > 0:
                portfolio.positions[position.symbol] = position

        features = calculate_features(candles)
        features.metadata['higher_timeframe_confirmation']=higher_timeframe_context(candles)
        features.metadata["last_price"] = candles[-1].close
        if order_book.mid and order_book.spread:
            features.metadata["last_price"] = order_book.mid

        signals = self.strategy_engine.generate(features)
        await self.repository.store_market_analysis(candles, features, order_book)
        ai_assessment = await self.ai_provider.assess(features, signals)
        decision = self.decision_engine.decide(pair, features, signals, portfolio, ai_assessment, entries_today)

        risk_evaluation = None
        order = None
        if decision.entry_price is not None and decision.stop_loss is not None:
            risk_evaluation = self.risk_engine.evaluate_entry(
                portfolio,
                pair,
                decision.proposed_quote_amount,
                decision.entry_price,
                decision.stop_loss,
                entries_today,
            )
        await self.repository.store_analysis(signals, ai_assessment, decision, risk_evaluation)

        if decision.accepted and decision.action is DecisionAction.BUY:
            execution = await self.execution_gateway.execute_entry_decision(pair, decision, order_book, idempotency_key)
            order = execution.order
        return RuntimeCycleResult(signals, ai_assessment, decision, risk_evaluation, order)

    async def exit_position(
        self,
        pair: TradingPair,
        quantity: Decimal,
        order_book: OrderBook,
        idempotency_key: str,
    ) -> Order:
        await self.repository.initialize_portfolio(self.initial_cash)
        result = await self.execution_gateway.execute_exit(pair, quantity, order_book, idempotency_key, "runtime_exit")
        if result.order is None:
            raise RuntimeError(result.reason)
        return result.order
