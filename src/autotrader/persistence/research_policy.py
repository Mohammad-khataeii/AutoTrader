from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from autotrader.domain import new_id, utc_now
from autotrader.persistence.models import (
    MarketFeature,
    PositionModel,
    SystemIncidentModel,
    SystemStateModel,
)
from autotrader.research.artifacts import load_latest, source_fingerprint
from autotrader.research.strategies import StrategyParameters


class ResearchPolicyMixin:
    session_factory: Any
    _lock_account: Any

    async def configure_research_policy(self, root: Path, *, test_environment: bool,
                                         approved: set[str]) -> None:
        summary = None
        failure = None
        try:
            summary = load_latest(root)
        except (ValueError, OSError) as exc:
            failure = str(exc)
        passed = set(summary.get("passed_strategies", [])) if summary else set()
        current_source, _ = source_fingerprint()
        source_matches = bool(summary and summary.get("source_fingerprint") == current_source)
        live = summary.get("timeframes", {}).get("5m", {}).get("strategies", {}) if summary else {}
        live_parameters = StrategyParameters().payload()
        allowed = sorted(strategy for strategy in approved & passed if source_matches and
            live.get(strategy, {}).get("gates", {}).get("passed") and
            live.get(strategy, {}).get("out_of_sample", {}).get("parameters") == live_parameters)
        payload = {"require_validation": not test_environment, "allowed_strategy_ids": allowed,
            "mode": "TEST_FINANCIAL_ACCEPTANCE" if test_environment else "VALIDATED_ONLY",
            "research_verdict": summary.get("verdict") if summary else "NO_VERIFIED_RESEARCH_REPORT",
            "research_run_id": summary.get("run_id") if summary else None, "source_matches": source_matches,
            "live_timeframe":"5m", "required_parameters":live_parameters,
            "promotion_requirement":"Matching live timeframe, exact frozen parameters, source fingerprint, validation gates and explicit approval",
            "failure": failure, "policy_version": "4.0.0"}
        encoded = json.dumps(payload, sort_keys=True)
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            row = await session.get(SystemStateModel, "research_entry_policy")
            if row and row.payload_json == encoded:
                return
            if row is None:
                session.add(SystemStateModel(key="research_entry_policy", state=payload["mode"], reason="research_promotion_gate", payload_json=encoded))
            else:
                row.state, row.reason, row.payload_json = payload["mode"], "research_promotion_gate", encoded
            session.add(SystemIncidentModel(incident_id=new_id("inc"), severity="INFO", status="ENTRY_POLICY",
                message="research_strategy_promotion_policy", payload_json=encoded))

    async def allocation_context(self) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            positions = (await session.scalars(select(PositionModel).where(PositionModel.state == "OPEN"))).all()
            result = []
            for position in positions:
                row = await session.scalar(select(MarketFeature).where(MarketFeature.symbol == position.symbol,
                    MarketFeature.timestamp <= utc_now()).order_by(MarketFeature.timestamp.desc()).limit(1))
                if row:
                    metadata = json.loads(row.payload_json).get("metadata", {})
                    metadata["_feature_timestamp"] = row.timestamp.isoformat()
                    result.append(metadata)
                else:
                    result.append({})
            return result

    async def store_allocation_advice(self, decision_id: str, payload: dict[str, Any]) -> None:
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            key = "alloc:" + decision_id
            row = await session.get(SystemStateModel, key)
            if row is None:
                session.add(SystemStateModel(key=key, state="ACCEPTED" if payload["accepted"] else "REJECTED",
                    reason="portfolio_allocation", payload_json=json.dumps(payload, default=str)))
