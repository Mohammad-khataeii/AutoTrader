from __future__ import annotations

import time
from dataclasses import dataclass, replace
from decimal import Decimal

from autotrader.ai import AIProviderClient
from autotrader.decision import DecisionEngine
from autotrader.domain import (
    AIAssessment,
    DecisionAction,
    MarketFeatures,
    StrategySignal,
    TradingDecision,
)
from autotrader.indicators import calculate_features, higher_timeframe_context
from autotrader.market_data.revolut import MarketDataError
from autotrader.market_data.service import MarketDataService, ValidatedMarket
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.portfolio import Portfolio
from autotrader.strategies import BreakoutStrategyEngine


@dataclass(frozen=True)
class ScanCandidate:
    market: ValidatedMarket
    features: MarketFeatures
    signals: list[StrategySignal]
    ai_assessment: AIAssessment
    decision: TradingDecision
    score: Decimal


@dataclass(frozen=True)
class ScanResult:
    status: str
    scanned: int
    rejected: list[dict[str, object]]
    provider_errors: list[str]
    candidates: list[ScanCandidate]
    duration_ms: Decimal

    @property
    def best(self) -> ScanCandidate | None:
        return self.candidates[0] if self.candidates else None


class MarketScanner:
    def __init__(
        self,
        *,
        market_data: MarketDataService,
        repository: PersistentTradingRepository,
        strategy_engine: BreakoutStrategyEngine,
        decision_engine: DecisionEngine,
        ai_provider: AIProviderClient,
        initial_cash: Decimal,
    ) -> None:
        self.market_data = market_data
        self.repository = repository
        self.strategy_engine = strategy_engine
        self.decision_engine = decision_engine
        self.ai_provider = ai_provider
        self.initial_cash = initial_cash

    async def scan_once(self, max_pairs: int = 8) -> ScanResult:
        started = time.perf_counter()
        rejected: list[dict[str, object]] = []
        provider_errors: list[str] = []
        candidates: list[ScanCandidate] = []
        try:
            pairs = await self.market_data.discover_pairs(limit=max_pairs)
        except MarketDataError as exc:
            return ScanResult("DATA_UNAVAILABLE", 0, rejected, [str(exc)], [], Decimal("0"))

        portfolio = await self._portfolio()
        benchmarks:dict[str,MarketFeatures]={}
        prepared: list[tuple[ValidatedMarket, MarketFeatures]] = []
        for pair in pairs:
            try:
                market = await self.market_data.get_validated_market(pair)
            except MarketDataError as exc:
                provider_errors.append(f"{pair.symbol}:{exc}")
                rejected.append({"symbol": pair.symbol, "reasons": ["provider_error"]})
                continue
            if not market.usable_for_entry:
                rejected.append({"symbol": pair.symbol, "reasons": market.rejected_reasons})
                continue
            features = calculate_features(market.candles[-240:], market.metrics.imbalance, market.metrics.spread_bps)
            features.metadata['higher_timeframe_confirmation']=higher_timeframe_context(market.candles[-240:])
            features.metadata.update(
                {
                    "last_price": market.metrics.mid,
                    "best_bid": market.metrics.best_bid,
                    "best_ask": market.metrics.best_ask,
                    "spread_bps": market.metrics.spread_bps,
                    "bid_depth": market.metrics.bid_depth,
                    "ask_depth": market.metrics.ask_depth,
                    "liquidity_quote": market.metrics.liquidity_quote,
                    "provider_latency_ms": market.metrics.provider_latency_ms,
                    "order_book_age_seconds": market.metrics.age_seconds,
                    "provider": market.order_book.source,
                }
            )
            benchmarks[pair.base_asset]=features
            prepared.append((market, features))
        # Evaluate the whole completed-bar cross-section so BTC and ETH receive
        # the same available benchmark context as assets discovered after them.
        for market, features in prepared:
            signals = self.strategy_engine.generate(features,benchmarks.get('BTC'),benchmarks.get('ETH'))
            await self.repository.store_market_analysis(market.candles, features, market.order_book)
            ai = await self.ai_provider.assess(features, signals)
            decision = self.decision_engine.decide(market.pair, features, signals, portfolio, ai)
            policy_reason=await self.repository.candidate_policy_reason(signals)
            if policy_reason and decision.accepted:
                decision=replace(decision,accepted=False,action=DecisionAction.WAIT,rejected_reason=policy_reason,
                    explanation=decision.explanation+'; research admission: '+policy_reason)
            await self.repository.store_analysis(signals, ai, decision)
            score = sum((signal.score for signal in signals), Decimal("0"))
            candidates.append(ScanCandidate(market, features, signals, ai, decision, score))

        candidates.sort(key=lambda candidate: (candidate.decision.accepted, candidate.score), reverse=True)
        status = "OK" if candidates else ("DATA_UNAVAILABLE" if provider_errors and not rejected else "NO_CANDIDATES")
        duration = Decimal(str(round((time.perf_counter() - started) * 1000, 3)))
        return ScanResult(status, len(pairs), rejected, provider_errors, candidates, duration)

    async def _portfolio(self) -> Portfolio:
        await self.repository.initialize_portfolio(self.initial_cash)
        snapshot = await self.repository.snapshot()
        portfolio = Portfolio(Decimal(snapshot["available_cash"]), quote_asset=self.repository.quote_asset)
        portfolio.balances[portfolio.quote_asset].reserved = Decimal(snapshot["reserved_cash"])
        for position in await self.repository.list_positions():
            if position.closed_at is None and position.quantity > 0:
                portfolio.positions[position.symbol] = position
        return portfolio
