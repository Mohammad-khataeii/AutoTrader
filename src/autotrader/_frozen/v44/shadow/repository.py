from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, select

from autotrader.persistence.models import AccountModel, ShadowIdentityModel, SystemStateModel
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.research.artifacts import source_fingerprint
from autotrader.research.data import canonical, digest
from autotrader.shadow.versions import execution_fingerprint


@dataclass(frozen=True)
class ShadowScope:
    database_name: str
    manifest_json: str

    @property
    def manifest(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.manifest_json))

    @property
    def identity_hash(self) -> str:
        return digest(canonical(self.manifest))


class ShadowTradingRepository(PersistentTradingRepository):
    def __init__(self, session_factory: Any, scope: ShadowScope):
        actual = session_factory.kw["bind"].url.database
        if (
            not actual
            or actual != scope.database_name
            or not actual.startswith("autotrader_shadow_")
        ):
            raise ValueError("shadow_database_scope_mismatch")
        if (
            scope.manifest["database_name"] != actual
            or scope.manifest["official_database"] == actual
        ):
            raise ValueError("shadow_manifest_scope_mismatch")
        self.scope = scope
        super().__init__(session_factory)

    @property
    def account_id(self) -> str:  # type: ignore[override]  # Deliberately remove inherited write access.
        return "shadow:" + str(self.scope.manifest["experiment_id"])

    async def _assert_scope(self, session: Any) -> None:
        identity = await session.get(ShadowIdentityModel, 1)
        if (
            not identity
            or identity.manifest_hash != self.scope.identity_hash
            or json.loads(identity.manifest_json) != self.scope.manifest
        ):
            raise ValueError("shadow_identity_marker_mismatch")
        other = await session.scalar(
            select(func.count())
            .select_from(AccountModel)
            .where(AccountModel.account_id != self.account_id)
        )
        if other:
            raise ValueError("foreign_account_in_shadow_database")

    async def initialize_portfolio(self, initial_cash: Decimal) -> None:
        async with self.session_factory() as session:
            await self._assert_scope(session)
        await super().initialize_portfolio(initial_cash)

    async def _lock_account(self, session: Any) -> AccountModel:
        await self._assert_scope(session)
        return await super()._lock_account(session)

    async def _entry_policy_error(
        self, session: Any, strategy: str, evidence: dict[str, Any], fee: Any, slip: Any
    ) -> str | None:
        await self._assert_scope(session)
        m = self.scope.manifest
        if (execution_fingerprint() != m["execution_fingerprint"] if m.get("execution_fingerprint") else source_fingerprint()[0] != m["source_fingerprint"]):
            return "shadow_frozen_source_changed"
        if (
            strategy != m["strategy_id"]
            or evidence.get("strategy_version") != m["strategy_version"]
            or evidence.get("parameters") != m["parameters"]
        ):
            return "shadow_frozen_strategy_mismatch"
        if str(fee) != m["fee_bps"] or str(slip) != m["slippage_bps"]:
            return "shadow_frozen_cost_mismatch"
        if not evidence.get("entry_eligible") or evidence.get("veto"):
            return "shadow_entry_ineligible"
        return None

    async def claim_candle(self, symbol: str, stamp: str) -> bool:
        key = "shadow_candle:" + symbol
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            row = await session.get(SystemStateModel, key)
            if row and json.loads(row.payload_json)["stamp"] >= stamp:
                return False
            payload = json.dumps({"stamp": stamp})
            if row:
                row.payload_json = payload
            else:
                session.add(
                    SystemStateModel(
                        key=key,
                        state="OBSERVED",
                        reason="at_most_once_candle_evaluation",
                        payload_json=payload,
                    )
                )
            return True
