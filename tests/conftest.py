from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository


@pytest.fixture
async def pg_repo(request: pytest.FixtureRequest) -> AsyncIterator[PersistentTradingRepository]:
    admin = os.getenv("AUTOTRADER_TEST_PG_ADMIN_URL")
    if not admin:
        pytest.fail("Real PostgreSQL required: set AUTOTRADER_TEST_PG_ADMIN_URL. No SQLite fallback.")
    name = "autotrader_v34_" + uuid4().hex[:12]

    def create() -> str:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            info = conn.info.get_parameters()
            # libpq deliberately omits the password from connection info. Keep
            # explicitly supplied credentials for child migration/worker URLs.
            from psycopg.conninfo import conninfo_to_dict
            info.update(conninfo_to_dict(admin))
        info["dbname"] = name
        from sqlalchemy.engine import URL
        return URL.create("postgresql+asyncpg", username=info.get("user"), password=info.get("password"),
            host=info.get("host"), port=int(info.get("port", "5432")), database=name).render_as_string(hide_password=False)

    url = await asyncio.to_thread(create)
    engine = make_engine(SimpleNamespace(database_url=url))  # type: ignore[arg-type]
    try:
        if request.node.get_closest_marker("legacy_schema"):
            import subprocess
            import sys
            result = await asyncio.to_thread(subprocess.run,
                [sys.executable,"-m","alembic","-x",f"dburl={url}","upgrade","0004_v3_2_exit_plan_quantities"],
                capture_output=True,text=True)
            assert result.returncode == 0, result.stderr
        else:
            await create_schema(engine)
        repo = PersistentTradingRepository(make_session_factory(engine))
        repo.test_database_url = url  # type: ignore[attr-defined]
        yield repo
    finally:
        await engine.dispose()

        def drop() -> None:
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        await asyncio.to_thread(drop)


@pytest.fixture
async def lab(pg_repo):
    from decimal import Decimal as D

    from autotrader.config import Settings
    from autotrader.shadow.lab import ShadowLab
    await pg_repo.initialize_portfolio(D(500))
    settings = Settings(
        database_url=pg_repo.test_database_url,
        environment="test",
        shadow_enabled=True,
        _env_file=None,
    )
    service = ShadowLab(pg_repo, settings)
    yield service
    records = await service.records()
    await service.close()

    def cleanup():
        with psycopg.connect(os.environ["AUTOTRADER_TEST_PG_ADMIN_URL"], autocommit=True) as conn:
            for record in records:
                conn.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(record["manifest"]["database_name"])
                    )
                )

    await asyncio.to_thread(cleanup)
