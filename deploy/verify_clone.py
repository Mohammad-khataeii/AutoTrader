"""Executed inside a candidate image against newly restored AutoTrader clones only."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import make_url

from autotrader.config import get_settings
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository

FINANCIAL_TABLES = (
    'accounts','balances','financial_journal','orders','fills','positions',
    'capital_reservations','exit_intents','exit_targets','exit_plans',
    'risk_periods','cooldowns','equity_snapshots','ai_budgets','ai_usage',
)


async def verify_clone(database: str, account: str = 'paper-eur', migrate: bool = False):
    if not database.startswith('autotrader_restore_'):
        raise ValueError('Verification refuses original/runtime databases')
    settings=get_settings()
    settings.database_url=make_url(settings.database_url).set(database=database).render_as_string(hide_password=False)
    engine=make_engine(settings)
    try:
        repo=PersistentTradingRepository(make_session_factory(engine))
        # This verifier is deliberately read-only financial replay on a newly
        # restored clone. It cannot initialize money or admit an order.
        repo.account_id=account
        async with engine.connect() as connection:
            accounts=list((await connection.execute(text('SELECT account_id FROM accounts'))).scalars())
            assert accounts==[account], 'Restored financial domain identity mismatch'
            before_revision=await connection.scalar(text('SELECT version_num FROM alembic_version'))
            if account.startswith('shadow:'):
                marker=json.loads(await connection.scalar(text('SELECT manifest_json FROM shadow_identity WHERE singleton=1')))
                assert account=='shadow:'+marker['experiment_id']
        async def seal():
            result={}
            async with engine.connect() as connection:
                for table in FINANCIAL_TABLES:
                    row=(await connection.execute(text(f"SELECT count(*),md5(COALESCE(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text),'')) FROM {table} t"))).one()
                    result[table]={'rows':row[0],'digest':row[1]}
            return result
        before=await seal()
        assert not await repo.verify_invariants(Decimal(500)), 'Restored financial reconciliation failed'
        rollback='not_requested'
        after_revision=before_revision
        if migrate:
            await create_schema(engine)
            assert not await repo.verify_invariants(Decimal(500))
            async with engine.connect() as connection:
                after_revision=await connection.scalar(text('SELECT version_num FROM alembic_version'))
            rollback='not_needed_same_revision'
            if before_revision!=after_revision:
                args=[sys.executable,'-m','alembic','-x','dburl='+settings.database_url,'downgrade',before_revision]
                process=await asyncio.to_thread(subprocess.run,args,capture_output=True,text=True)
                if process.returncode:
                    raise RuntimeError('Isolated rollback failed: '+process.stderr[-1000:])
                assert not await repo.verify_invariants(Decimal(500))
                assert await seal()==before, 'Rollback changed financial history'
                await create_schema(engine)
                assert not await repo.verify_invariants(Decimal(500))
                rollback='isolated_downgrade_and_reupgrade_passed'
        assert await seal()==before, 'Migration/verification changed financial history'
        return {'database':database,'account_id':account,'before':before_revision,'after':after_revision,
                'rollback':rollback,'reconciliation':[],'financial_seal':before,'financial_history_unchanged':True,
                'original_database_modified':False,'runtime_activated':False}
    finally:
        await engine.dispose()
