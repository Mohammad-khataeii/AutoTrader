"""One isolated database, one shared cash pool, the existing journal and broker."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from autotrader.domain import Candle, TradingPair
from autotrader.persistence.accounting import aware
from autotrader.persistence.models import (
    AccountModel,
    ExitPlanModel,
    MarketCandle,
    MarketFeature,
    OrderModel,
    PositionModel,
    ShadowIdentityModel,
    SystemStateModel,
)
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.personal_paper.exits import assess_exit
from autotrader.personal_paper.policy import (
    ACCOUNT,
    AGGREGATE_STOP_RISK,
    CORRELATED_CAPITAL,
    INITIAL,
    LIMITS,
    MAX_DRAWDOWN,
    STRATEGIES,
    STRATEGY_CAPITAL,
    fingerprint,
    risk_payload,
)
from autotrader.personal_paper.selection import POLICY, QUALITY_GATES
from autotrader.research.data import canonical, digest

D = Decimal


class PersonalPaperRepository(PersistentTradingRepository):
    expected_initial_cash = INITIAL
    ledger_risk_limits = LIMITS
    max_drawdown_fraction = MAX_DRAWDOWN

    def __init__(self, factory: Any, manifest: dict[str, Any]):
        self.manifest = manifest
        actual = factory.kw['bind'].url.database
        if (actual != manifest['database_name'] or not actual.startswith('autotrader_paper_')
                or actual == manifest['official_database'] or manifest['account_id'] != ACCOUNT):
            raise ValueError('personal_paper_database_scope_mismatch')
        super().__init__(factory)

    @property
    def account_id(self) -> str:  # type: ignore[override]
        return ACCOUNT

    async def assert_scope(self, session: Any) -> None:
        marker = await session.get(ShadowIdentityModel, 1)
        origin = self.manifest.get('account_origin', self.manifest)
        if (not marker or marker.manifest_hash != digest(canonical(origin))
                or json.loads(marker.manifest_json) != origin):
            raise ValueError('personal_paper_identity_mismatch')
        if self.manifest.get('account_origin'):
            from autotrader.persistence.models import SystemStateModel
            profile = await session.get(SystemStateModel, 'paper_profile:'+self.manifest['version'])
            if not profile or json.loads(profile.payload_json) != self.manifest:
                raise ValueError('personal_paper_revision_identity_mismatch')
        if await session.scalar(select(func.count()).select_from(AccountModel).where(AccountModel.account_id != ACCOUNT)):
            raise ValueError('foreign_account_in_personal_paper_database')

    async def _lock_account(self, session: Any) -> AccountModel:
        await self.assert_scope(session)
        return await super()._lock_account(session)

    async def initialize_portfolio(self, initial_cash: Decimal) -> None:
        async with self.session_factory() as session:
            await self.assert_scope(session)
        await super().initialize_portfolio(initial_cash)

    async def _entry_policy_error(self, session: Any, strategy: str, evidence: dict[str, Any], fee: Any, slip: Any) -> str | None:
        await self.assert_scope(session)
        m = self.manifest
        if m['runtime_fingerprint'] != fingerprint() or m['risk_limits'] != risk_payload() or m.get('execution_policy') != POLICY:
            return 'paper_frozen_runtime_changed_new_experiment_required'
        selected = m['strategies'].get(strategy)
        if (selected != STRATEGIES.get(strategy) or not selected
                or any(evidence.get(k) != selected[k] for k in ('strategy_version', 'parameters'))
                or evidence.get('paper_manifest') != digest(canonical(m))):
            return 'paper_strategy_not_authorized_for_manifest'
        if str(fee) != m['fee_bps'] or str(slip) != m['slippage_bps']:
            return 'paper_frozen_cost_mismatch'
        if (evidence.get('quality_policy', {}).get('version') != POLICY['version']
                or set(evidence.get('quality_policy', {}).get('gates', {})) != QUALITY_GATES
                or not all(v is True for v in evidence['quality_policy']['gates'].values())):
            return 'paper_quality_policy_required'
        if not evidence.get('entry_eligible') or evidence.get('veto'):
            return 'paper_entry_ineligible'
        return None

    async def _entry_risk(self, session: Any, pair: TradingPair, quote: Decimal, price: Decimal,
                          stop: Decimal | None, execution_cost_bps: Decimal = D(25), *,
                          own_order: OrderModel | None = None) -> str | None:
        error = await super()._entry_risk(session, pair, quote, price, stop, execution_cost_bps, own_order=own_order)
        if error:
            return error
        # Executed under the SAME account lock as cash reservation, including
        # the second admission at fill time. All crypto belongs to one coarse
        # correlation cluster when synchronized correlation evidence is absent.
        positions = (await session.scalars(select(PositionModel).where(PositionModel.state == 'OPEN'))).all()
        pending = (await session.scalars(select(OrderModel).where(OrderModel.side == 'BUY', OrderModel.status.in_(['PENDING', 'ACCEPTED'])))).all()
        pending = [o for o in pending if not own_order or o.order_id != own_order.order_id]
        stop_risk = sum((max(D(0), p.cost_basis-p.quantity*(p.protective_stop or D(0))*(1-D('.004'))) for p in positions), D(0))
        stop_risk += sum((o.quote_amount*max(D(0), 1-D(json.loads(o.execution_json)['stop_loss'])/(o.quote_amount/o.quantity))+o.quote_amount*D('.004') for o in pending), D(0))
        proposed_risk = quote*((price-(stop or D(0)))/price+execution_cost_bps/10000)
        if stop_risk+proposed_risk > AGGREGATE_STOP_RISK:
            return 'aggregate_stop_risk_budget'
        committed = sum((p.cost_basis for p in positions), D(0))+sum((o.quote_amount for o in pending), D(0))
        if committed+quote > CORRELATED_CAPITAL:
            return 'crypto_cluster_exposure_limit'
        if own_order:
            strategy = json.loads(own_order.execution_json)['strategy_id']
            plans = (await session.scalars(select(ExitPlanModel).where(ExitPlanModel.strategy_id == strategy))).all()
            ids = {p.position_id for p in plans}
            attributed = sum((p.cost_basis for p in positions if p.position_id in ids), D(0))
            attributed += sum((o.quote_amount for o in pending if json.loads(o.execution_json).get('strategy_id') == strategy), D(0))
            if attributed+quote > STRATEGY_CAPITAL:
                return 'strategy_concentration_limit'
        return None

    async def position_exit_reason(self, position_id: str, symbol: str, as_of: datetime) -> str | None:
        async with self.session_factory() as session:
            position = await session.get(PositionModel, position_id)
            if not position or position.symbol != symbol or position.account_id != ACCOUNT:
                return None
            plan = await session.scalar(select(ExitPlanModel).where(ExitPlanModel.position_id == position_id))
            entry = await session.scalar(select(OrderModel).where(OrderModel.position_id == position_id,
                OrderModel.side == 'BUY', OrderModel.filled_quantity > 0).order_by(OrderModel.created_at).limit(1))
            rows = (await session.scalars(select(MarketCandle).where(MarketCandle.symbol == symbol,
                MarketCandle.timeframe == '5m', MarketCandle.timestamp <= as_of-timedelta(minutes=5),
                MarketCandle.timestamp >= as_of-timedelta(hours=62)).order_by(MarketCandle.timestamp.desc(), MarketCandle.id.desc()).limit(3000))).all()
            unique: dict[datetime, Candle] = {}
            for c in rows:
                stamp = aware(c.timestamp)
                candle = Candle(c.symbol, stamp, c.open, c.high, c.low, c.close, c.volume, c.timeframe, c.source)
                if stamp in unique and unique[stamp] != candle:
                    return None  # Conflicting closed observations cannot authorize a discretionary exit.
                unique[stamp] = candle
            result = assess_exit(plan.strategy_id if plan else 'UNATTRIBUTED', aware(position.opened_at),
                json.loads(entry.execution_json).get('strategy_evidence', {}) if entry else {},
                list(unique.values()), as_of, genuine=self.manifest['data_kind']!='SYNTHETIC_ACCEPTANCE')
        # Append-only causal assessments, separate from shared strategy features.
        key = 'position_exit:'+digest(canonical([position_id, result.get('candle_at'), result['status'], POLICY['version']]))[:48]
        from autotrader.persistence.repository import _json
        async with self.session_factory() as session, session.begin():
            await self._lock_account(session)
            if not await session.get(SystemStateModel, key):
                session.add(SystemStateModel(key=key, state='EXIT_ASSESSMENT', reason=result['status'],
                    payload_json=_json({**result, 'position_id': position_id})))
        return result['reason'] if isinstance(result['reason'], str) else None

    async def latest_features(self, symbol: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            row = await session.scalar(select(MarketFeature).where(MarketFeature.symbol == symbol).order_by(MarketFeature.timestamp.desc()).limit(1))
            return json.loads(row.payload_json) if row else None
