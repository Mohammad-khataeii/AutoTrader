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
    features: Any, signals: list[Any], decision: Any, manifest: dict[str, Any], runner: str,
    benchmarks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = features.metadata.get("experimental_context", {})
    by_id = {s.strategy_id: s for s in signals}
    primary = by_id.get(manifest["strategy_id"])
    evidence = primary.evidence if primary else {}
    if evidence.get('strategy_version') == '4.6.0-experimental.1':
        assert primary is not None
        successor_conditions = evidence['conditions']
        return {'schema': 'shadow-decision-explanation/3', 'decision_id': decision.decision_id,
            'experiment_id': manifest['experiment_id'], 'strategy_id': manifest['strategy_id'],
            'symbol': decision.symbol, 'runner': runner, 'data_quality': features.data_quality.value,
            'regime': evidence['regime'], 'entry_conditions': successor_conditions,
            'independently_failed': evidence['reasons'], 'unknown_conditions': [], 'diagnostic_parity': True,
            'signal_entry_eligible': evidence['entry_eligible'], 'technical_eligible': evidence['technical_eligible'],
            'economic_eligible': evidence['economic_eligible'], 'opportunity': evidence,
            'risk': {'reached': evidence['entry_eligible'], 'rejection': decision.rejected_reason if not decision.accepted else None},
            'decision_accepted': decision.accepted, 'execution': {'reached': False, 'quality': {'reached': False, 'rejection': None}},
            'final_state': 'BUY_PENDING_EXECUTION' if decision.accepted else 'REJECTED',
            'reason_code': 'DECISION_ACCEPTED' if decision.accepted else 'COST_REFUSAL' if evidence['technical_eligible'] and not evidence['economic_eligible'] else 'RISK_REFUSAL' if evidence['entry_eligible'] else 'TECHNICAL_INELIGIBLE',
            'reason': decision.rejected_reason if evidence['entry_eligible'] and not decision.accepted else primary.explanation}
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
        "context_15m_ready": context.get("15m", {}).get("ready"),
        "context_1h_ready": context.get("60m", {}).get("ready"),
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
    elif strategy == "C2_LIQUID_RETEST":
        conditions.update(
            retest_available=check(retest, predicate=lambda a: a > 0),
            previous_breakout=check(previous, retest, predicate=lambda a, b: a > b * (1 + D(p["breakout_buffer"]))),
            retest_touched=check(low, retest, predicate=lambda a, b: a <= b * D("1.002")),
            range_held=check(close, retest, predicate=lambda a, b: a >= b),
            close_recovery=check(close, previous, decimal(context.get("last_open")), predicate=lambda a, b, c: a > b and a > c),
            previous_high_reclaimed=check(close, decimal(context.get("previous_high")), predicate=lambda a, b: a > b),
            relative_volume=check(decimal(features.relative_volume), predicate=lambda a: a >= D(p["relative_volume"])),
        )
    elif strategy == "E2_ABSOLUTE_RELATIVE_STRENGTH":
        peers = [b for b in (benchmarks or {}).values() if b.timestamp == features.timestamp]
        absolute_safe = len(peers) == 2 and all(
            b.ema_21 and b.ema_50 and b.ema_21 > b.ema_50
            and D(str(b.metadata.get("last_close", 0))) >= b.ema_21 for b in peers)
        conditions.update(
            absolute_benchmarks_bullish=bool(absolute_safe) if benchmarks is not None else None,
            relative_outperformance=(decimal(evidence.get("relative_return")) or D(0)) > D(p["relative_return"]),
            close_recovery=check(close, previous, decimal(context.get("last_open")), predicate=lambda a, b, c: a > b and a > c),
            relative_volume=check(decimal(features.relative_volume), predicate=lambda a: a >= D(p["relative_volume"])),
        )
    else:
        conditions["strategy_specific_conditions_unobserved"] = None
    veto = by_id.get("D2_MOMENTUM_QUALITY")
    regime = evidence.get("regime", features.metadata.get("regime_assessment", {}).get("regime"))
    if runner in {"verified-v42", "verified-v44"}:
        from functools import partial

        from autotrader.shadow.versions import frozen_module
        legacy_module = partial(frozen_module, selected=runner.removeprefix("verified-"))

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
    computed_entry = all(value is True for value in conditions.values()) and regime_eligible is True
    diagnostic_parity = (
        computed_entry == evidence.get("entry_eligible")
        if all(value is not None for value in conditions.values()) and regime_eligible is not None
        else None
    )
    peers = [b for b in (benchmarks or {}).values() if b.timestamp == features.timestamp]
    atr, ema21 = decimal(features.atr), decimal(features.ema_21)
    momentum_components = {
        "extended_above_ema21": check(close, ema21, atr, predicate=lambda c, e, a: a > 0 and (c-e)/a > 2),
        "falling_close_weakening_volume": check(
            close, previous, decimal(context.get("current_volume")),
            decimal(context.get("previous_volume")), predicate=lambda c, p, v, pv: c < p and v < pv),
        "bearish_benchmark": any(b.ema_21 and b.ema_50 and b.ema_21 < b.ema_50 for b in peers)
            if benchmarks is not None else None,
        "spread_above_25bps": check(decimal(features.spread_bps), predicate=lambda v: v > 25),
        "adverse_regime": regime in {"BEAR", "LIQUIDITY_STRESS", "UNCERTAIN"} if regime else None,
    }
    component_parity = (
        any(momentum_components.values()) == (veto.evidence.get("veto") if veto else None)
        if all(v is not None for v in momentum_components.values()) else None
    )
    inputs = {k: str(features.metadata[k]) if k in features.metadata else None for k in
              ("last_close", "previous_close", "last_low", "last_high", "retest_level")}
    inputs.update({k: context.get(k) for k in
                   ("last_open", "previous_high", "prebreak_width", "breakout_relative_volume",
                    "current_volume", "previous_volume")})
    inputs.update({k: str(getattr(features, k)) if getattr(features, k) is not None else None
                   for k in ("ema_9", "ema_21", "ema_50", "atr", "relative_volume", "spread_bps")})
    return {
        "schema": "shadow-decision-explanation/2",
        "action": decision.action.value,
        "diagnostic_parity": diagnostic_parity,
        "momentum_components": momentum_components,
        "momentum_component_parity": component_parity,
        "inputs": inputs,
        "allocation": {"reached": False, "accepted": None, "reason": None},
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
        "final_state": "BUY_PENDING_EXECUTION" if decision.accepted else "REJECTED",
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
    repo._diagnostic_runner = runner
    original_market, original_analysis = repo.store_market_analysis, repo.store_analysis
    captured: dict[str, Any] = {}
    claim_candle, claim_coordinator = repo.claim_candle, repo.claim_coordinator

    async def candle(*args: Any, **kwargs: Any) -> Any:
        result = await claim_candle(*args, **kwargs)
        if not result and hasattr(repo, "_diagnostic_scan"):
            repo._diagnostic_scan.setdefault("skips", []).append({"symbol": args[0], "stage": "candle_deduplication"})
        return result

    async def coordinator(*args: Any, **kwargs: Any) -> Any:
        result = await claim_coordinator(*args, **kwargs)
        if not result and hasattr(repo, "_diagnostic_scan"):
            repo._diagnostic_scan["coordinator_refused"] = True
        return result

    repo.claim_candle, repo.claim_coordinator = candle, coordinator

    async def market(candles: Any, features: Any, book: Any) -> Any:
        captured["features"] = features
        return await original_market(candles, features, book)

    async def analysis(signals: Any, ai: Any, decision: Any, *args: Any, **kwargs: Any) -> Any:
        result = await original_analysis(signals, ai, decision, *args, **kwargs)
        if hasattr(repo, "_diagnostic_scan"):
            repo._diagnostic_scan["evaluated"] += 1
        if "features" in captured:
            from autotrader.shadow.trace import event
            primary = next((s for s in signals if s.strategy_id == repo.scope.manifest["strategy_id"]), None)
            stamp = captured["features"].timestamp.isoformat()
            await event(repo, decision.decision_id, "SIGNAL_ELIGIBLE",
                "SUCCEEDED" if primary and primary.evidence.get("entry_eligible") else "REJECTED",
                symbol=decision.symbol, candle_at=stamp, reason="recorded_signal_eligibility")
            await event(repo, decision.decision_id, "DECISION_ACCEPTED",
                "SUCCEEDED" if decision.accepted and decision.action.value == "BUY" else "REJECTED",
                symbol=decision.symbol, candle_at=stamp, reason=decision.rejected_reason)
            try:
                await persist(
                    repo,
                    explain(captured["features"], signals, decision, repo.scope.manifest, runner,
                            getattr(repo, "_diagnostic_benchmarks", None)),
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
                    if stage == "allocation":
                        body["allocation"] = {"reached": True, "accepted": accepted, "reason": reason}
                    body["execution"] = {
                        "reached": True,
                        "stage": stage,
                        "reason": reason,
                        "quality": dict(quality),
                        "refusal_gate": None if accepted else (
                            "execution_quality" if reason.startswith("execution_quality:")
                            else "risk" if "risk" in reason or "reconciliation" in reason
                            else "data_freshness" if "stale" in reason or "future" in reason
                            else "instrument_limits" if "min_order" in reason or "max_order" in reason
                            else "recorded_refusal"
                        ),
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
        from autotrader.domain import new_id
        from autotrader.shadow.trace import event
        attempt = new_id('attempt') if getattr(getattr(repo, 'scope', None), 'manifest', {}).get('strategy_version') == '4.6.0-experimental.1' else ''
        quality.update(reached=False, rejection=None)
        buying = candidate.decision.accepted and candidate.decision.action.value == "BUY"
        if buying:
            await event(repo, candidate.decision.decision_id, "ALLOCATION_ACCEPTED", "ATTEMPTED", symbol=candidate.decision.symbol, discriminator=attempt)
        try:
            result = await allocate(candidate)
        except Exception as exc:
            if buying:
                await event(repo, candidate.decision.decision_id, "ALLOCATION_ACCEPTED", "EXCEPTION", reason=type(exc).__name__, discriminator=attempt)
            raise
        if buying:
            await event(repo, candidate.decision.decision_id, "ALLOCATION_ACCEPTED",
                "SUCCEEDED" if result[0] is not None else "REJECTED", reason=result[1], discriminator=attempt)
        if candidate.decision.accepted and candidate.decision.action.value == "BUY":
            await outcome(
                candidate.decision.decision_id, result[0] is not None, result[1], "allocation"
            )
        return result

    async def entry(pair: Any, decision: Any, *args: Any, **kwargs: Any) -> Any:
        quality.update(reached=False, rejection=None)
        from autotrader.domain import new_id
        from autotrader.shadow.trace import event, observe_order
        attempt = new_id('attempt') if getattr(getattr(repo, 'scope', None), 'manifest', {}).get('strategy_version') == '4.6.0-experimental.1' else ''
        buying = decision.accepted and decision.action.value == "BUY"
        if buying:
            await event(repo, decision.decision_id, "ENTRY_PREFLIGHT", "ATTEMPTED", symbol=pair.symbol, discriminator=attempt)
        try:
            result = await execute(pair, decision, *args, **kwargs)
        except Exception as exc:
            if buying:
                await event(repo, decision.decision_id, "ENTRY_PREFLIGHT", "EXCEPTION", reason=type(exc).__name__, discriminator=attempt)
            raise
        if buying:
            await event(repo, decision.decision_id, "ENTRY_PREFLIGHT",
                "SUCCEEDED" if result.accepted else "REJECTED", reason=result.reason,
                related={"order_id": result.order.order_id if result.order else None}, discriminator=attempt)
            if result.order:
                await observe_order(repo, result.order.order_id)
        # The original runtime invokes the gateway for WAIT decisions too; that
        # returns before risk/market quality evaluation. Preserve that distinction.
        if decision.accepted and decision.action.value == "BUY":
            await outcome(decision.decision_id, result.accepted, result.reason, "entry")
        return result

    original_exit: Any = getattr(gateway, "execute_exit", None)

    async def exit_observation(*args: Any, **kwargs: Any) -> Any:
        from autotrader.shadow.trace import observe_order
        result = await original_exit(*args, **kwargs)
        if result.order:
            await observe_order(repo, result.order.order_id)
        return result

    if original_exit is not None:
        gateway.execute_exit = exit_observation
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


async def record_scan(repo: Any, observation: dict[str, Any]) -> None:
    """Best-effort telemetry cannot admit or veto a financial action."""
    try:
        from autotrader.domain import utc_now
        async with repo.session_factory() as session, session.begin():
            row = await session.get(SystemStateModel, "shadow_scan_observation")
            if row is None:
                row = SystemStateModel(key="shadow_scan_observation")
                session.add(row)
            row.state = "ERROR" if observation.get("exception") else "COMPLETED"
            row.reason = "observed_scan_control_flow"
            row.payload_json = _json(observation)
            row.updated_at = utc_now()
    except Exception:
        log.exception("shadow_scan_observation_failed")
