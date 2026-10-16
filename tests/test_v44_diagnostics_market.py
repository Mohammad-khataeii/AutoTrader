import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import httpx
import pytest

from autotrader.clock import at
from autotrader.decision import DecisionEngine
from autotrader.domain import utc_now
from autotrader.market_data.revolut import RateLimitDeferred, RevolutXPublicClient
from autotrader.market_data.service import MarketDataService
from autotrader.portfolio import Portfolio
from autotrader.research.experimental import VERSION, ExperimentalStrategyEngine
from autotrader.research.strategies import StrategyParameters
from autotrader.risk import RiskEngine, RiskLimits
from autotrader.shadow.diagnostics import counterfactual, explain
from test_v4_execution import PAIR
from test_v4_regimes_strategies import features


def test_explanation_separates_independent_failures_concurrent_veto_and_unreached_stages():
    f = replace(features(), timeframe="5m")
    f.metadata["experimental_context"] = {
        "ready": True,
        "15m": {"bull": False, "bear": True, "ready": True},
        "60m": {"bull": False, "bear": True, "ready": True},
        "prebreak_width": ".5",
        "breakout_relative_volume": ".1",
        "last_open": "105",
        "previous_high": "106",
    }
    f.metadata.update(last_close="104", previous_close="105", last_low="103", retest_level="105")
    parameters = StrategyParameters(stop_atr=D(2), target_atr=D(2))
    signals = ExperimentalStrategyEngine(parameters, {"B2_CONFIRMED_COMPRESSION"}).generate(f, f, f)
    decision = DecisionEngine(RiskEngine(RiskLimits())).decide(
        PAIR, f, signals, Portfolio(D(500)), None
    )
    manifest = {
        "strategy_id": "B2_CONFIRMED_COMPRESSION",
        "strategy_version": VERSION,
        "parameters": parameters.payload(),
        "source_fingerprint": "synthetic-test",
    }
    explanation = explain(f, signals, decision, manifest, "native-v44")
    assert explanation["reason"] == decision.rejected_reason
    assert explanation["risk"]["reached"] is False and explanation["execution"]["reached"] is False
    assert {"higher_timeframe_bullish", "prebreak_compression", "breakout_volume"} <= set(
        explanation["independently_failed"]
    )
    assert explanation["final_state"] == "REJECTED"
    assert counterfactual([explanation])["single_observed_blocker_counts"] == {}
    f.metadata["experimental_context"] = {}
    unknown = explain(f, signals, decision, manifest, "native-v44")
    assert unknown["entry_conditions"]["context_ready"] is None
    assert "context_ready" not in unknown["independently_failed"]
    primary = next(s for s in signals if s.strategy_id == "B2_CONFIRMED_COMPRESSION")
    primary.evidence["regime"] = "RANGE"
    range_observation = explain(f, signals, decision, manifest, "native-v44")
    assert range_observation["regime_veto"] is True
    assert range_observation["regime_eligible"] is False
    assert "COMPRESSION" in range_observation["allowed_regimes"]
    assert "RANGE" not in range_observation["allowed_regimes"]


async def test_429_recovery_honors_millisecond_header_and_long_outage_defers(monkeypatch):
    client = RevolutXPublicClient()
    sleeps = []
    calls = []

    async def sleep(seconds):
        sleeps.append(seconds)

    async def request(path, params):
        calls.append(path)
        return httpx.Response(
            429 if len(calls) == 1 else 200,
            headers={"Retry-After": "750"},
            json={"data": {}},
            request=httpx.Request("GET", "https://example.test" + path),
        )

    monkeypatch.setattr(client, "_paced_get", request)
    monkeypatch.setattr("autotrader.market_data.revolut.asyncio.sleep", sleep)
    monkeypatch.setattr("autotrader.market_data.revolut.random.uniform", lambda *args: 0)
    try:
        assert await client._request("/1.0/public/candles/BTC-EUR") == {"data": {}}
        assert sleeps == [0.75] and len(calls) == 2

        async def outage(path, params):
            return httpx.Response(
                429,
                headers={"Retry-After": "120000"},
                request=httpx.Request("GET", "https://example.test" + path),
            )

        monkeypatch.setattr(client, "_paced_get", outage)
        with pytest.raises(RateLimitDeferred):
            await client._request("/1.0/public/candles/ETH-EUR")
        assert sleeps == [0.75]
    finally:
        await client.close()


async def test_cancelled_http_request_is_not_retried_or_counted_as_provider_failure(monkeypatch):
    client = RevolutXPublicClient()
    started = asyncio.Event()
    calls = []

    async def pending(path, params):
        calls.append(path)
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(client, "_paced_get", pending)
    task = asyncio.create_task(client._request("/1.0/public/candles/BTC-EUR"))
    await started.wait()
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(calls) == 1 and client._breaker.failures == 0
    finally:
        await client.close()


async def test_discovery_rotates_same_universe_without_changing_request_rate():
    pairs = [replace(PAIR, symbol=s + "-EUR", base_asset=s) for s in ("BTC", "ETH", "SOL")]

    class Feed:
        async def get_pairs(self):
            return pairs

    service = MarketDataService(Feed())
    results = [await service.discover_pairs(limit=3) for _ in range(3)]
    assert [r[0].base_asset for r in results] == ["BTC", "ETH", "SOL"]
    assert all({p.symbol for p in r} == {p.symbol for p in pairs} for r in results)


async def test_rate_metrics_have_identifiable_windows_without_relabeling_legacy_counts(pg_repo):
    await pg_repo.initialize_portfolio(D(500))
    start = utc_now()
    with at(start):
        await pg_repo.market_metric("request_success", 10)
        await pg_repo.market_metric("request_429", 2)
    with at(start + timedelta(minutes=16)):
        await pg_repo.market_metric("request_success", 1)
        health = await pg_repo.market_data_health()
    assert health["requests"] == 13 and health["request_429"] == 2
    assert len(health["measurement_windows"]) == 2
    assert sorted(w.get("request_success", 0) for w in health["measurement_windows"]) == [1, 10]
    assert all(w["started_at"] and w["observed_until"] for w in health["measurement_windows"])


async def test_gateway_observation_does_not_call_wait_preflight_a_quality_rejection(pg_repo):
    import json
    from types import SimpleNamespace

    from autotrader.persistence.models import SystemStateModel
    from autotrader.shadow.diagnostics import observe_gateway

    await pg_repo.initialize_portfolio(D(500))
    async with pg_repo.session_factory() as session, session.begin():
        session.add(
            SystemStateModel(
                key="shadow_explanation:wait-test",
                state="REJECTED",
                reason="observed",
                payload_json=json.dumps(
                    {
                        "final_state": "REJECTED",
                        "reason_code": "RECORDED_DECISION_REJECTION",
                        "reason": "Entry conditions not met.",
                        "execution": {"reached": False},
                    }
                ),
            )
        )

    class Gateway:
        market_data = SimpleNamespace(validate_order_book=lambda *a: (["stale_depth"], {}))

        async def allocate_candidate(self, candidate):
            return candidate.decision, "allocation_accepted"

        async def execute_entry_decision(self, pair, decision, *args):
            if not decision.accepted:
                return SimpleNamespace(accepted=False, reason="Entry conditions not met.")
            self.market_data.validate_order_book(None)
            return SimpleNamespace(accepted=False, reason="stale_depth")

    gateway = observe_gateway(Gateway(), pg_repo)
    decision = SimpleNamespace(
        decision_id="wait-test", accepted=False, action=SimpleNamespace(value="WAIT")
    )
    await gateway.allocate_candidate(SimpleNamespace(decision=decision))
    await gateway.execute_entry_decision(None, decision)
    async with pg_repo.session_factory() as session:
        row = await session.get(SystemStateModel, "shadow_explanation:wait-test")
        body = json.loads(row.payload_json)
        assert body["execution"]["reached"] is False
        assert body["final_state"] == "REJECTED" and body["reason"] == "Entry conditions not met."
        assert body["reason_code"] == "RECORDED_DECISION_REJECTION"
    decision.accepted = True
    decision.action.value = "BUY"
    await gateway.execute_entry_decision(None, decision)
    async with pg_repo.session_factory() as session:
        row = await session.get(SystemStateModel, "shadow_explanation:wait-test")
        assert json.loads(row.payload_json)["execution"]["quality"] == {
            "reached": True,
            "rejection": "stale_depth",
        }
