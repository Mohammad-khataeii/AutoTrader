"""Run the verified V4.2 execution closure with shared current observations."""

from __future__ import annotations

import inspect
from dataclasses import asdict
from typing import Any

from autotrader.shadow.versions import (
    LEGACY_SOURCE,
    convert,
    legacy_module,
    verify_boundary,
    verify_legacy,
)


class ObservationBoundary:
    def __init__(self, current: Any):
        self.current = current

    def __getattr__(self, name: str) -> Any:
        if name == "validate_order_book":
            frozen_service = legacy_module("market_data.service").MarketDataService(
                None, max_staleness_seconds=getattr(self.current, "max_staleness_seconds", 90)
            )
            return frozen_service.validate_order_book
        method = getattr(self.current, name)
        if not callable(method):
            return method
        if inspect.iscoroutinefunction(method):

            async def call(*args: Any, **kwargs: Any) -> Any:
                try:
                    return convert(await method(*(convert(a, False) for a in args), **kwargs))
                except Exception as exc:
                    if type(exc).__module__ == "autotrader.market_data.revolut":
                        raise legacy_module("market_data.revolut").MarketDataError(
                            str(exc)
                        ) from exc
                    raise

            return call

        def call_sync(*args: Any, **kwargs: Any) -> Any:
            return convert(method(*(convert(a, False) for a in args), **kwargs))

        return call_sync


class LegacyRunner:
    def __init__(self, lab: Any, market_data: Any, risk: Any, owner: str):
        verify_legacy()
        verify_boundary()
        repository = legacy_module("persistence.repository").PersistentTradingRepository(
            lab.official.session_factory
        )
        self.lab = legacy_module("shadow.lab").ShadowLab(repository, lab.settings)

        async def records() -> list[dict[str, Any]]:
            return [
                r
                for r in await lab.records()
                if r["manifest"]["source_fingerprint"] == LEGACY_SOURCE and not r.get("archived_at")
            ]

        self.lab.records = records
        frozen_risk = legacy_module("risk")
        self.runtime = legacy_module("shadow.runtime").ShadowRuntime(
            self.lab,
            ObservationBoundary(market_data),
            frozen_risk.RiskEngine(frozen_risk.RiskLimits(**asdict(risk.limits))),
            owner,
        )
        original_gateway = self.runtime.gateway
        from autotrader.shadow.diagnostics import observe_gateway

        self.runtime.gateway = lambda repo: observe_gateway(original_gateway(repo), repo)
        original = self.lab.repository
        self.observed: set[str] = set()

        async def repository_with_observer(identity: str) -> Any:
            repo = await original(identity)
            if identity not in self.observed:
                from autotrader.shadow.diagnostics import observe_repository

                observe_repository(repo, "verified-v42")
                self.observed.add(identity)
            return repo

        self.lab.repository = repository_with_observer

    async def renew(self) -> None:
        verify_legacy()
        verify_boundary()
        await self.runtime.renew()

    async def monitor(self) -> None:
        verify_legacy()
        verify_boundary()
        await self.runtime.monitor()

    async def scan(self, record: dict[str, Any], candidates: list[Any]) -> None:
        verify_legacy()
        verify_boundary()
        copied = convert(candidates)
        # Recompute features from shared raw observations with the frozen
        # indicator implementation. No current strategy/indicator code executes.
        from dataclasses import replace

        indicators = legacy_module("indicators")
        prepared = []
        repo = await self.lab.repository(record["experiment_id"])
        for candidate in copied:
            market = candidate.market
            validator = legacy_module("market_data.service").MarketDataService(
                None,
                max_staleness_seconds=getattr(
                    self.runtime.market_data.current, "max_staleness_seconds", 90
                ),
            )
            reasons, _ = validator.validate_order_book(
                market.order_book, market.metrics.provider_latency_ms
            )
            # Preserve the original short-circuit order, including invalid data.
            failures = reasons
            if not failures:
                failures = validator.validate_pair(market.pair)
            if not failures:
                failures = validator.validate_candles(market.candles, 5)
            if not failures and len(market.candles) < 50:
                failures = ["insufficient_candle_history"]
            if failures:
                if hasattr(repo, "_diagnostic_scan"):
                    repo._diagnostic_scan["skips"].append({"symbol": market.pair.symbol, "stage": "frozen_market_validation", "reasons": failures})
                continue
            f = indicators.calculate_features(
                market.candles[-240:], market.metrics.imbalance, market.metrics.spread_bps
            )
            f.metadata["higher_timeframe_confirmation"] = indicators.higher_timeframe_context(
                market.candles[-240:]
            )
            f.metadata.update(
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
            prepared.append(replace(candidate, features=f))
        copied = prepared
        repo = await self.lab.repository(record["experiment_id"])
        repo._diagnostic_benchmarks = {
            c.features.symbol: c.features for c in copied if c.features.symbol in {"BTC-EUR", "ETH-EUR"}
        }
        await self.runtime._scan_experiment(
            record, copied, {c.features.symbol: c.features for c in copied}
        )

    async def close(self) -> None:
        await self.lab.close()
