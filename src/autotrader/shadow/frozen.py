"""Reviewed V4.4 adapter: observations enter, original execution code owns finances.

No entry policy replacement or fingerprint rebinding occurs here. The original
repository runs its own original execution_fingerprint() at order admission.
"""
from __future__ import annotations

import inspect
from dataclasses import asdict, replace
from typing import Any

from autotrader.shadow.versions import (
    V44_EXECUTION,
    convert,
    frozen_module,
    verify_generation,
)


def module(name: str) -> Any:
    return frozen_module(name, "v44")


class V44ObservationBoundary:
    def __init__(self, current: Any):
        self.current = current

    def __getattr__(self, name: str) -> Any:
        if name == "validate_order_book":
            return module("market_data.service").MarketDataService(
                None, max_staleness_seconds=getattr(self.current, "max_staleness_seconds", 90)
            ).validate_order_book
        method = getattr(self.current, name)
        if not callable(method):
            return method
        if inspect.iscoroutinefunction(method):
            async def call(*args: Any, **kwargs: Any) -> Any:
                try:
                    value = await method(*(convert(a, False, "v44") for a in args),
                                         **convert(kwargs, False, "v44"))
                    return convert(value, selected="v44")
                except Exception as exc:
                    if type(exc).__module__ == "autotrader.market_data.revolut":
                        raise module("market_data.revolut").MarketDataError(str(exc)) from exc
                    raise
            return call
        def sync(*args: Any, **kwargs: Any) -> Any:
            return convert(method(*(convert(a, False, "v44") for a in args),
                                  **convert(kwargs, False, "v44")), selected="v44")
        return sync


class FrozenV44Runner:
    def __init__(self, lab: Any, market_data: Any, risk: Any, owner: str):
        verify_generation("v44")
        official = module("persistence.repository").PersistentTradingRepository(lab.official.session_factory)
        self.lab = module("shadow.lab").ShadowLab(official, lab.settings)

        async def records() -> list[dict[str, Any]]:
            return [r for r in await lab.records()
                    if r["manifest"].get("execution_fingerprint") == V44_EXECUTION
                    and not r.get("archived_at")]
        self.lab.records = records
        frozen_risk = module("risk")
        self.runtime = module("shadow.runtime").ShadowRuntime(
            self.lab, V44ObservationBoundary(market_data),
            frozen_risk.RiskEngine(frozen_risk.RiskLimits(**asdict(risk.limits))), owner)
        original_gateway = self.runtime.gateway
        from autotrader.shadow.diagnostics import observe_gateway, observe_repository

        # The frozen gateway (including preflight and repository authorization)
        # is unchanged. The outer observer only records its returned outcomes.
        self.runtime.gateway = lambda repo: observe_gateway(original_gateway(repo), repo)
        original_repository = self.lab.repository

        async def repository(identity: str) -> Any:
            repo = await original_repository(identity)
            # Installing this observer first makes the old observer's existing
            # idempotency guard skip its obsolete 35-character explanation.
            observe_repository(repo, "verified-v44")
            return repo
        self.lab.repository = repository

    async def renew(self) -> None:
        verify_generation("v44")
        await self.runtime.renew()

    async def monitor(self) -> None:
        verify_generation("v44")
        await self.runtime.monitor()
        from autotrader.shadow.trace import recover_traces
        for record in await self.lab.records():
            if record["state"] != "CREATING":
                await recover_traces(await self.lab.repository(record["experiment_id"]))

    async def scan(self, record: dict[str, Any], candidates: list[Any]) -> None:
        verify_generation("v44")
        if record["manifest"].get("execution_fingerprint") != V44_EXECUTION:
            raise ValueError("v44_runner_manifest_mismatch")
        repo = await self.lab.repository(record["experiment_id"])
        prepared = []
        validator = module("market_data.service").MarketDataService(
            None, max_staleness_seconds=getattr(self.runtime.market_data.current, "max_staleness_seconds", 90))
        indicators = module("indicators")
        for candidate in convert(candidates, selected="v44"):
            market = candidate.market
            reasons, metrics = validator.validate_order_book(market.order_book, market.metrics.provider_latency_ms)
            failures = reasons or validator.validate_pair(market.pair) or validator.validate_candles(market.candles, 5)
            if not failures and len(market.candles) < 50:
                failures = ["insufficient_candle_history"]
            if failures:
                if hasattr(repo, "_diagnostic_scan"):
                    repo._diagnostic_scan["skips"].append({"symbol": market.pair.symbol,
                        "stage": "frozen_market_validation", "reasons": failures})
                continue
            features = indicators.calculate_features(market.candles[-240:], metrics.imbalance, metrics.spread_bps)
            features.metadata["higher_timeframe_confirmation"] = indicators.higher_timeframe_context(market.candles[-240:])
            features.metadata.update({"last_price": metrics.mid, "best_bid": metrics.best_bid,
                "best_ask": metrics.best_ask, "spread_bps": metrics.spread_bps,
                "bid_depth": metrics.bid_depth, "ask_depth": metrics.ask_depth,
                "liquidity_quote": metrics.liquidity_quote, "provider_latency_ms": metrics.provider_latency_ms,
                "order_book_age_seconds": metrics.age_seconds, "provider": market.order_book.source})
            prepared.append(replace(candidate, market=replace(market, metrics=metrics), features=features))
        context = {c.features.symbol: c.features for c in prepared}
        repo._diagnostic_benchmarks = {k: v for k, v in context.items() if k in {"BTC-EUR", "ETH-EUR"}}
        await self.runtime._scan_experiment(record, prepared, context)

    async def close(self) -> None:
        await self.lab.close()
