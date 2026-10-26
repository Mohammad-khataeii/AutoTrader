"""Local provisioning reuses shadow isolation, migrations and identity markers."""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import sql
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from autotrader.domain import utc_now
from autotrader.persistence.accounting import aware
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.models import (
    AccountModel,
    EquitySnapshotModel,
    ExitPlanModel,
    FillModel,
    OrderModel,
    PositionModel,
    ShadowIdentityModel,
    SystemStateModel,
)
from autotrader.persistence.repository import PersistentTradingRepository, _json
from autotrader.personal_paper.policy import (
    ACCOUNT,
    INITIAL,
    REGISTRY_KEY,
    STRATEGIES,
    VERSION,
    fingerprint,
    risk_payload,
)
from autotrader.personal_paper.repository import PersonalPaperRepository
from autotrader.research.data import canonical, digest

D = Decimal


class PersonalPaperService:
    def __init__(self, official: PersistentTradingRepository, settings: Any):
        self.official, self.settings = official, settings
        self.engine: Any = None
        self.repo: PersonalPaperRepository | None = None

    async def record(self) -> dict[str, Any] | None:
        async with self.official.session_factory() as session:
            row = await session.get(SystemStateModel, REGISTRY_KEY)
            if not row:
                return None
            origin: dict[str, Any] = json.loads(row.payload_json)
            active = await session.get(SystemStateModel, 'personal_paper_active_profile')
            if not active:
                return origin
            pointer = json.loads(active.payload_json)
            profile = await session.get(SystemStateModel, pointer['key'])
            manifest = json.loads(profile.payload_json) if profile else None
            if (not manifest or digest(canonical(manifest)) != pointer['hash']
                    or manifest.get('account_origin') != origin):
                raise ValueError('paper_active_profile_identity_mismatch')
            return dict(manifest)

    async def create_runtime_revision(self, reason: str) -> PersonalPaperRepository:
        """Explicit reviewed cutover while flat. Never called by the worker loop.

        The account origin, old decisions, rejected orders and funding stay
        immutable. A new frozen prospective identity shares the original cash.
        """
        if len(reason) < 20 or not self.settings.personal_paper_enabled:
            raise ValueError('explicit_paper_revision_reason_required')
        repo = await self.repository()
        if not repo:
            raise ValueError('paper_origin_required')
        current = repo.manifest
        if current['version'] == VERSION:
            if current['runtime_fingerprint'] != fingerprint():
                raise ValueError('new_runtime_version_required_no_manifest_overwrite')
            return repo
        origin = current.get('account_origin', current)
        manifest = {**origin, 'version': VERSION, 'account_origin': origin,
            'parent_profile_hash': digest(canonical(current)), 'frozen_at': utc_now().isoformat(),
            'runtime_fingerprint': fingerprint(), 'revision_reason': reason}
        key = 'paper_profile:'+VERSION
        async with repo.session_factory() as session, session.begin():
            account = await repo._lock_account(session)
            if account.control != 'PAUSED':
                raise ValueError('pause_entries_before_explicit_revision')
            if (await session.scalar(select(func.count()).select_from(PositionModel).where(PositionModel.state.in_(['OPEN','PENDING'])))
                    or await session.scalar(select(func.count()).select_from(OrderModel).where(OrderModel.status.in_(['PENDING','ACCEPTED'])))):
                raise ValueError('runtime_revision_requires_flat_reconciled_account')
            if await repo._verify(session, INITIAL):
                raise ValueError('runtime_revision_reconciliation_required')
            existing = await session.get(SystemStateModel, key)
            if existing:
                manifest = json.loads(existing.payload_json)
                if manifest['runtime_fingerprint'] != fingerprint() or manifest['account_origin'] != origin:
                    raise ValueError('immutable_runtime_revision_conflict')
            else:
                session.add(SystemStateModel(key=key, state='FROZEN_PROFILE', reason=reason, payload_json=_json(manifest)))
        # Cross-database cutover is resumable: the immutable profile is durable
        # in its account database before the official registry points to it.
        async with self.official.session_factory() as session, session.begin():
            await self.official._lock_account(session)
            registry_key = 'personal_paper_profile:'+VERSION
            existing = await session.get(SystemStateModel, registry_key)
            if existing and json.loads(existing.payload_json) != manifest:
                raise ValueError('immutable_profile_registry_conflict')
            if not existing:
                session.add(SystemStateModel(key=registry_key,state='FROZEN_PROFILE',reason=reason,payload_json=_json(manifest)))
            pointer = await session.get(SystemStateModel, 'personal_paper_active_profile')
            payload = _json({'key':registry_key,'hash':digest(canonical(manifest))})
            if pointer:
                pointer.payload_json, pointer.updated_at = payload, utc_now()
            else:
                session.add(SystemStateModel(key='personal_paper_active_profile',state='ACTIVE_PROFILE',reason='explicit_flat_account_cutover',payload_json=payload))
        await self.close()
        opened = await self.repository()
        assert opened is not None
        return opened

    async def ensure(self) -> PersonalPaperRepository:
        if not self.settings.personal_paper_enabled or self.settings.live_trading_enabled:
            raise ValueError('experimental_paper_authority_required')
        url = make_url(self.settings.database_url)
        if url.get_backend_name() != 'postgresql' or self.official.account_id != 'paper-eur':
            raise ValueError('paper_requires_isolated_postgresql_and_official_registry')
        async with self.official.session_factory() as session, session.begin():
            await self.official._lock_account(session)
            row = await session.get(SystemStateModel, REGISTRY_KEY)
            if not row:
                manifest = {'account_id': ACCOUNT, 'version': VERSION, 'official_database': url.database,
                    'database_name': 'autotrader_paper_'+digest(str(url.database).encode())[:32],
                    'initial_cash_eur': str(INITIAL), 'currency': 'EUR', 'strategies': STRATEGIES,
                    'risk_limits': risk_payload(), 'runtime_fingerprint': fingerprint(),
                    'fee_bps': str(self.settings.default_fee_bps), 'slippage_bps': str(self.settings.default_slippage_bps),
                    'fee_tier': 'CONSERVATIVE_UNVERIFIED_TAKER_ASSUMPTION',
                    'data_kind': 'SYNTHETIC_ACCEPTANCE' if self.settings.environment == 'test' else 'REVOLUT_X_PROSPECTIVE_PAPER',
                    'frozen_at': utc_now().isoformat(), 'approval': 'EXPERIMENTAL_PAPER_ONLY',
                    'live_authorized': False}
                row = SystemStateModel(key=REGISTRY_KEY, state='CREATING', reason='one_shared_virtual_pool', payload_json=_json(manifest))
                session.add(row)
            manifest = json.loads(row.payload_json)

        def provision() -> None:
            with psycopg.connect(dbname=url.database, user=url.username, password=url.password,
                                 host=url.host, port=url.port or 5432, autocommit=True) as conn:
                conn.execute('SELECT pg_advisory_lock(4700001)')
                name = manifest['database_name']
                if not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone():
                    conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))

        await asyncio.to_thread(provision)
        settings = self.settings.model_copy(update={'database_url': url.set(database=manifest['database_name']).render_as_string(hide_password=False)})
        engine = make_engine(settings)
        try:
            await create_schema(engine)
            factory = make_session_factory(engine)
            async with factory() as session, session.begin():
                await session.execute(text('SELECT pg_advisory_xact_lock(4700002)'))
                marker = await session.get(ShadowIdentityModel, 1)
                identity_hash = digest(canonical(manifest))
                if marker and marker.manifest_hash != identity_hash:
                    raise ValueError('paper_database_manifest_collision')
                if not marker:
                    if await session.scalar(select(func.count()).select_from(AccountModel)):
                        raise ValueError('unmarked_paper_database_contains_accounts')
                    session.add(ShadowIdentityModel(singleton=1, manifest_hash=identity_hash, manifest_json=_json(manifest)))
            repo = PersonalPaperRepository(factory, manifest)
            await repo.initialize_portfolio(INITIAL)
            if await repo.verify_invariants(INITIAL):
                raise ValueError('paper_initial_reconciliation_failed')
        finally:
            await engine.dispose()
        async with self.official.session_factory() as session, session.begin():
            row = await session.get(SystemStateModel, REGISTRY_KEY)
            assert row is not None
            row.state = 'PAPER_EXPERIMENTAL_ACTIVE'
        opened = await self.repository()
        assert opened is not None
        return opened

    async def repository(self) -> PersonalPaperRepository | None:
        if self.repo is None:
            manifest = await self.record()
            if manifest is None:
                return None
            url = make_url(self.settings.database_url).set(database=manifest['database_name'])
            settings = self.settings.model_copy(update={'database_url': url.render_as_string(hide_password=False)})
            self.engine = make_engine(settings)
            self.repo = PersonalPaperRepository(make_session_factory(self.engine), manifest)
        return self.repo

    async def detail(self) -> dict[str, Any]:
        repo = await self.repository()
        if repo is None:
            return {'state': 'NOT_INITIALIZED', 'enabled': self.settings.personal_paper_enabled, 'live_authorized': False}
        async with repo.session_factory() as session, session.begin():
            await repo._lock_account(session)
            portfolio = await repo._valuation(session)
            account = await session.get(AccountModel, ACCOUNT)
            assert account is not None
            portfolio['control'] = account.control
            health = await session.get(SystemStateModel, repo.RUNTIME_STATE_KEY)
            portfolio['risk_state'] = health.state if health else 'HEALTHY'
            positions = (await session.scalars(select(PositionModel))).all()
            plans = (await session.scalars(select(ExitPlanModel))).all()
            fills = (await session.scalars(select(FillModel))).all()
            orders = (await session.scalars(select(OrderModel))).all()
            snapshots = (await session.scalars(select(EquitySnapshotModel).order_by(EquitySnapshotModel.timestamp.desc()).limit(120))).all()
            scan = await session.get(SystemStateModel, 'paper_scan')
            monitor = await session.get(SystemStateModel, 'position_monitor')
            review = await session.get(SystemStateModel, 'paper_research_review')
            review_body = json.loads(review.payload_json) if review else {}
            attribution = {p.position_id: p.strategy_id for p in plans}
            closed = [p for p in positions if p.state == 'CLOSED']
            strategies = []
            for identity, spec in repo.manifest['strategies'].items():
                sample = [p for p in closed if attribution.get(p.position_id) == identity]
                pnl = sum((p.realized_pnl for p in sample), D(0))
                strategies.append({'strategy_id': identity, **spec, 'state': 'EXPERIMENTAL_PAPER_SELECTED',
                    'closed_positions': len(sample), 'net_realized_pnl': str(pnl),
                    'expectancy': str(pnl/len(sample)) if sample else None,
                    'confidence': 'INSUFFICIENT_INDEPENDENT_EVIDENCE' if len(sample)<30 else 'REQUIRES_CHRONOLOGICAL_REVIEW',
                    'allocation_weight': '1', 'automatic_parameter_changes': False})
            wins = [p.realized_pnl for p in closed if p.realized_pnl>0]
            losses = [p.realized_pnl for p in closed if p.realized_pnl<0]
            peak, max_dd = INITIAL, D(0)
            for equity in (await session.scalars(select(EquitySnapshotModel.equity).where(EquitySnapshotModel.degraded.is_(False)).order_by(EquitySnapshotModel.timestamp))).all():
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak-equity)/peak)
            problems = await repo._verify(session, INITIAL)
            modeled_impact = D(0)
            order_payloads = {o.order_id:json.loads(o.execution_json) for o in orders}
            for fill in fills:
                observed = order_payloads[fill.order_id].get('book',{})
                levels = observed.get('asks' if fill.side=='BUY' else 'bids',[])
                if levels:
                    reference = D(levels[0][0])
                    modeled_impact += fill.quantity*(fill.price-reference if fill.side=='BUY' else reference-fill.price)
            outcomes = {'modeled_slippage_and_impact_eur':str(modeled_impact), 'buy_orders': sum(o.side=='BUY' for o in orders), 'sell_orders': sum(o.side=='SELL' for o in orders),
                'buy_fills': sum(f.side=='BUY' for f in fills), 'sell_fills': sum(f.side=='SELL' for f in fills),
                'fills': len(fills), 'open_positions': sum(p.state=='OPEN' for p in positions), 'closed_positions': len(closed),
                'fees_eur': str(sum((f.fee for f in fills), D(0))),
                'win_rate': len(wins)/len(closed) if closed else None,
                'average_win': str(sum(wins)/len(wins)) if wins else None,
                'average_loss': str(sum(losses)/len(losses)) if losses else None,
                'profit_factor': str(sum(wins)/-sum(losses)) if losses else None,
                'expectancy': str(sum((p.realized_pnl for p in closed), D(0))/len(closed)) if closed else None,
                'max_drawdown': str(max_dd), 'risk_adjusted_return': None,
                'statistics_limit': 'Trade counts are not independent samples; risk-adjusted returns require a longer daily series.'}
            paper_scan = json.loads(scan.payload_json) if scan else {}
            monitor_body = json.loads(monitor.payload_json) if monitor else {}
        runtime_matches = repo.manifest['runtime_fingerprint'] == fingerprint()
        monitor_age = (utc_now()-aware(datetime.fromisoformat(monitor_body['heartbeat']))).total_seconds() if monitor_body.get('heartbeat') else None
        scan_age = (utc_now()-aware(datetime.fromisoformat(paper_scan['observed_at']))).total_seconds() if paper_scan.get('observed_at') else None
        active = runtime_matches and portfolio['control']=='RUNNING' and portfolio['risk_state']=='HEALTHY'
        fresh = monitor_age is not None and -5 <= monitor_age <= 60 and scan_age is not None and -5 <= scan_age <= 180
        return {'account_id': ACCOUNT, 'state': 'PAPER_EXPERIMENTAL_ACTIVE' if active and fresh else 'DATA_SYNCING' if active else 'ENTRY_SUSPENDED',
            'version': VERSION, 'manifest': repo.manifest, 'portfolio': portfolio, 'performance': outcomes,
            'strategies': strategies, 'worker_health': {'monitor_age_seconds': monitor_age, 'scan_age_seconds': scan_age, 'fresh': fresh}, 'runtime_matches': runtime_matches, 'live_authorized': False,
            'evidence_category': repo.manifest['data_kind'], 'reconciliation': problems,
            'scan': paper_scan, 'position_monitor': monitor_body, 'research_review': review_body,
            'positions': [{**asdict(p), 'strategy_id': attribution.get(p.position_id)} for p in await repo.list_positions()],
            'orders': [{'order_id':o.order_id,'symbol':o.symbol,'side':o.side,'status':o.status,
                'order_type':o.order_type,'quantity':str(o.quantity),'filled_quantity':str(o.filled_quantity),
                'average_fill_price':str(o.average_fill_price) if o.average_fill_price is not None else None,
                'created_at':o.created_at.isoformat(),'strategy_id':json.loads(o.execution_json).get('strategy_id'),
                'rejection_reason':json.loads(o.execution_json).get('rejection_reason'),
                'fee_eur':str(sum((f.fee for f in fills if f.order_id==o.order_id),D(0)))} for o in reversed(orders[-80:])],
            'fills': list(reversed((await repo.list_fills())[-80:])),
            'equity_history': [{'timestamp': r.timestamp.isoformat(), 'equity': str(r.equity), 'degraded': r.degraded} for r in reversed(snapshots)],
            'history_limit': 120, 'observed_at': utc_now().isoformat(),
            'warning': 'Unvalidated virtual experiment. Official EUR500 and research shadow balances are excluded.'}

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
            self.engine, self.repo = None, None
