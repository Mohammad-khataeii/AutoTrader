import asyncio
import importlib.util
import os
import subprocess
import sys
from decimal import Decimal as D
from pathlib import Path

from sqlalchemy import text


def helper():
    spec = importlib.util.spec_from_file_location("vps_helper", Path("deploy/vps.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deploy_probe_distinguishes_running_fresh_unversioned_and_populated():
    probe = helper().database_state

    def dc_for(values):
        sequence = iter(values)

        def call(*args):
            return next(sequence)

        return call

    assert probe(dc_for([b'{"tables":0,"version_table":false}'])) == "FRESH"
    import pytest

    with pytest.raises(RuntimeError, match="Unversioned nonempty"):
        probe(dc_for([b'{"tables":1,"version_table":false}']))
    assert (
        probe(
            dc_for(
                [
                    b'{"tables":40,"version_table":true}',
                    b"0010_v41_ai_quotas",
                    b'{"accounts":0,"journal":0,"balances":0}',
                ]
            )
        )
        == "SCHEMA_ONLY"
    )
    assert (
        probe(
            dc_for(
                [
                    b'{"tables":40,"version_table":true}',
                    b"0010_v41_ai_quotas",
                    b'{"accounts":1,"journal":1,"balances":1}',
                ]
            )
        )
        == "POPULATED"
    )


async def revision(repo, direction, target, fail=False):
    env = {**os.environ}
    if fail:
        env["AUTOTRADER_V42_MIGRATION_FAILPOINT"] = "after_ddl"
    return await asyncio.to_thread(
        subprocess.run,
        [
            sys.executable,
            "-m",
            "alembic",
            "-x",
            "dburl=" + repo.test_database_url,
            direction,
            target,
        ],
        env=env,
        capture_output=True,
        text=True,
    )


async def test_populated_v41_upgrade_rollback_and_failed_migration_preserve_financial_history(
    pg_repo,
):
    await pg_repo.initialize_portfolio(D(500))
    assert (await revision(pg_repo, "downgrade", "0010_v41_ai_quotas")).returncode == 0
    async with pg_repo.session_factory() as session:
        before = (
            await session.execute(
                text("SELECT event_key,cash_delta FROM financial_journal ORDER BY event_key")
            )
        ).all()
    failed = await revision(pg_repo, "upgrade", "head", True)
    assert failed.returncode != 0 and "Injected V4.2 migration failure" in failed.stderr
    async with pg_repo.session_factory() as session:
        assert (
            await session.scalar(text("SELECT version_num FROM alembic_version"))
            == "0010_v41_ai_quotas"
        )
        assert await session.scalar(text("SELECT to_regclass('shadow_experiments')")) is None
        assert (
            await session.execute(
                text("SELECT event_key,cash_delta FROM financial_journal ORDER BY event_key")
            )
        ).all() == before
    assert (await revision(pg_repo, "upgrade", "head")).returncode == 0
    assert await pg_repo.verify_invariants(D(500)) == []
    await pg_repo.initialize_portfolio(D(500))
    async with pg_repo.session_factory() as session:
        assert (
            await session.execute(
                text("SELECT event_key,cash_delta FROM financial_journal ORDER BY event_key")
            )
        ).all() == before
        assert await session.scalar(text("SELECT available FROM balances WHERE asset='EUR'")) == 500
