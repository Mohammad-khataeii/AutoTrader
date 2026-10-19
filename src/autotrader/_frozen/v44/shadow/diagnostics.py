"""Additive observations only. Never used to authorize or change an order."""

from __future__ import annotations

import json
import logging
from collections import Counter
from decimal import Decimal as D
from typing import Any

from autotrader.persistence.models import SystemStateModel
from autotrader.persistence.repository import _json

log = logging.getLogger(__name__)


def explain(
    features: Any, signals: list[Any], decision: Any, manifest: dict[str, Any], runner: str
) -> dict[str, Any]:
    context = features.metadata.get("experimental_context", {})
    by_id = {s.strategy_id: s for s in signals}
    primary = by_id.get(manifest["strategy_id"])
    evidence = primary.evidence if primary else {}
    p = manifest["parameters"]

    def decimal(value: Any) -> D | None:
        try:
            number = D(str(value))
            return number if number.is_finite() else None
        except Exception:
            return None

    close = decimal(features.metadata.get("last_close"))
    previous = decimal(features.metadata.get("previous_close"))
    low = decimal(features.metadata.get("last_low"))
    retest = decimal(features.metadata.get("retest_level"))

    def check(*values: Any, predicate: Any) -> bool | None:
        return bool(predicate(*values)) if all(v is not None for v in values) else None

    ready = context.get("ready")
    conditions: dict[str, bool | None] = {
        "context_ready": bool(ready) if "ready" in context else None,
        "higher_timeframe_bullish": all(
            context.get(k, {}).get("bull") is True for k in ("15m", "60m")
        )
        if ready
        else None,
    }
    strategy = manifest["strategy_id"]
    if strategy == "A2_CONFIRMED_PULLBACK":
        conditions.update(
            ema9_recovery=check(low, features.ema_9, close, predicate=lambda a, b, c: a <= b <= c),
            close_recovery=check(
                close,
                previous,
                decimal(context.get("last_open")),
                predicate=lambda a, b, c: a > b and a > c,
            ),
            previous_high_reclaimed=check(
                close, decimal(context.get("previous_high")), predicate=lambda a, b: a > b
            ),
        )
    elif strategy == "B2_CONFIRMED_COMPRESSION":
        conditions.update(
            retest_available=check(retest, predicate=lambda a: a > 0),
            prebreak_compression=check(
                decimal(context.get("prebreak_width")),
                predicate=lambda a: a < D(p["compression_width"]),
            ),
            previous_breakout=check(
                previous, retest, predicate=lambda a, b: a > b * (1 + D(p["breakout_buffer"]))
            ),
            range_held=check(
                low, retest, predicate=lambda a, b: a >= b * (1 - D(p["breakout_buffer"]))
            ),
            no_close_reversal=check(close, previous, predicate=lambda a, b: a >= b),
            breakout_volume=check(
                decimal(context.get("breakout_relative_volume")),
                predicate=lambda a: a >= D(p["relative_volume"]),
            ),
        )
    veto = by_id.get("D2_MOMENTUM_QUALITY")
    regime = evidence.get("regime", features.metadata.get("regime_assessment", {}).get("regime"))
    if runner == "verified-v42":
        from autotrader.shadow.versions import legacy_module

        registry = (
            *legacy_module("research.experimental").EXPERIMENTAL_REGISTRY,
            *legacy_module("research.strategies").REGISTRY,
        )
    else:
        from autotrader.research.experimental import EXPERIMENTAL_REGISTRY
        from autotrader.research.strategies import REGISTRY

        registry = (*EXPERIMENTAL_REGISTRY, *REGISTRY)
    spec = next((s for s in registry if s.strategy_id == strategy), None)
    allowed_regimes = [r.value for r in spec.regimes] if spec else None
    regime_eligible = regime in allowed_regimes if regime and allowed_regimes is not None else None
    # The actual frozen signal is authoritative; contextual vetoes are separate
    # from independently failed entry conditions, never substituted as the cause.
    risk_reached = "risk_" in decision.explanation
    return {
        "schema": "shadow-decision-explanation/1",
        "decision_id": decision.decision_id,
        "symbol": features.symbol,
        "completed_candle_at": features.timestamp.isoformat(),
        "evaluated_at": decision.timestamp.isoformat(),
        "strategy_id": strategy,
        "strategy_version": manifest["strategy_version"],
        "source_fingerprint": manifest["source_fingerprint"],
        "execution_fingerprint": manifest.get("execution_fingerprint"),
        "runner": runner,
        "data_quality": features.data_quality.value,
        "regime": regime,
        "context": {k: context.get(k) for k in ("ready", "15m", "60m")},
        "entry_conditions": conditions,
        "independently_failed": [k for k, v in conditions.items() if v is False],
        "unknown_conditions": [k for k, v in conditions.items() if v is None],
        "volume_confirmation": conditions.get("breakout_volume"),
        "signal_entry_eligible": evidence.get("entry_eligible"),
        "momentum_veto": veto.evidence.get("veto") if veto else None,
        "allowed_regimes": allowed_regimes,
        "regime_eligible": regime_eligible,
        "regime_veto": not regime_eligible if regime_eligible is not None else None,
        "risk": {
            "reached": risk_reached,
            "rejection": decision.rejected_reason
            if risk_reached and not decision.accepted
            else None,
        },
        "execution": {
            "reached": False,
            "reason": None,
            "quality": {"reached": False, "rejection": None},
        },
        "decision_accepted": decision.accepted,
        "final_state": "DECISION_ACCEPTED_PENDING_EXECUTION" if decision.accepted else "REJECTED",
        "reason_code": "DECISION_ACCEPTED" if decision.accepted else "RECORDED_DECISION_REJECTION",
        "reason": decision.rejected_reason or decision.explanation,
        "notes": "A concurrent veto does not prove it alone caused rejection. Null means unobserved; risk/execution stages are reported only if reached.",
    }


async def persist(repo: Any, explanation: dict[str, Any]) -> None:
    key = "shadow_explanation:" + explanation["decision_id"]
    async with repo.session_factory() as session, session.begin():
        if not await session.get(SystemStateModel, key):
            session.add(
                SystemStateModel(
                    key=key,
                    state=explanation["final_state"],
                    reason="observed_shadow_evaluation",
                    payload_json=_json(explanation),
                )
            )


def observe_repository(repo: Any, runner: str) -> None:
    if getattr(repo, "_diagnostic_observed", False):
        return
    repo._diagnostic_observed = True
    original_market, original_analysis = repo.store_market_analysis, repo.store_analysis
    captured: dict[str, Any] = {}

    async def market(candles: Any, features: Any, book: Any) -> Any:
        captured["features"] = features
        return await original_market(candles, features, book)

    async def analysis(signals: Any, ai: Any, decision: Any, *args: Any, **kwargs: Any) -> Any:
        result = await original_analysis(signals, ai, decision, *args, **kwargs)
        if "features" in captured:
            try:
                await persist(
                    repo,
                    explain(captured["features"], signals, decision, repo.scope.manifest, runner),
                )
            except Exception:
                log.exception("shadow_diagnostic_observation_failed")
        return result

    repo.store_market_analysis, repo.store_analysis = market, analysis


def observe_gateway(gateway: Any, repo: Any) -> Any:
    allocate, execute = gateway.allocate_candidate, gateway.execute_entry_decision
    original_market_data = gateway.market_data
    quality: dict[str, Any] = {"reached": False, "rejection": None}

    class QualityObservation:
        def __getattr__(self, name: str) -> Any:
            return getattr(original_market_data, name)

        def validate_order_book(self, *args: Any, **kwargs: Any) -> Any:
            result = original_market_data.validate_order_book(*args, **kwargs)
            quality.update(reached=True, rejection=",".join(result[0]) if result[0] else None)
            return result

    gateway.market_data = QualityObservation()

    async def outcome(identity: str, accepted: bool, reason: str, stage: str) -> None:
        try:
            async with repo.session_factory() as session, session.begin():
                row = await session.get(SystemStateModel, "shadow_explanation:" + identity)
                if row:
                    body = json.loads(row.payload_json)
                    body["execution"] = {
                        "reached": True,
                        "stage": stage,
                        "reason": reason,
                        "quality": dict(quality),
                    }
                    body["final_state"] = (
                        "ACCEPTED"
                        if accepted and stage == "entry"
                        else "ALLOCATED"
                        if accepted
                        else "REJECTED"
                    )
                    body["reason_code"] = (
                        "EXECUTION_ACCEPTED" if accepted else "EXECUTION_REJECTION"
                    )
                    body["reason"] = reason
                    row.state, row.payload_json = body["final_state"], _json(body)
        except Exception:
            log.exception("shadow_execution_observation_failed")

    async def allocation(candidate: Any) -> Any:
        quality.update(reached=False, rejection=None)
        result = await allocate(candidate)
        if candidate.decision.accepted and candidate.decision.action.value == "BUY":
            await outcome(
                candidate.decision.decision_id, result[0] is not None, result[1], "allocation"
            )
        return result

    async def entry(pair: Any, decision: Any, *args: Any, **kwargs: Any) -> Any:
        quality.update(reached=False, rejection=None)
        result = await execute(pair, decision, *args, **kwargs)
        # The original runtime invokes the gateway for WAIT decisions too; that
        # returns before risk/market quality evaluation. Preserve that distinction.
        if decision.accepted and decision.action.value == "BUY":
            await outcome(decision.decision_id, result.accepted, result.reason, "entry")
        return result

    gateway.allocate_candidate, gateway.execute_entry_decision = allocation, entry
    return gateway


def counterfactual(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures: Counter[str] = Counter()
    single_blockers: Counter[str] = Counter()
    for row in rows:
        failures.update(row.get("independently_failed", []))
        failed = row.get("independently_failed", [])
        if (
            len(failed) == 1
            and not row.get("unknown_conditions")
            and not row.get("momentum_veto")
            and not row.get("regime_veto")
        ):
            single_blockers.update(failed)
    return {
        "observations": len(rows),
        "independent_failure_counts": dict(failures),
        "single_observed_blocker_counts": dict(single_blockers),
        "limitation": "Offline eligibility diagnostic only; not an executed counterfactual, profitability estimate, parameter change or promotion. Omitted/unknown conditions prevent causal attribution.",
    }
