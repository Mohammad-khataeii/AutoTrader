from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from autotrader.config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    if settings.database_url.startswith("sqlite"):
        @event.listens_for(engine.sync_engine, "connect")
        def sqlite_integrity(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    """Compatibility entry point: apply versioned Alembic migrations, never create_all."""
    import asyncio
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    url = engine.url.render_as_string(hide_password=False)
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"),
         "-x", f"dburl={url}", "upgrade", "head"],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError("Schema migration failed; autonomous operation refused. " + result.stderr[-2000:])
    await check_schema(engine)


async def check_schema(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != "0006_v34_accounting":
            raise RuntimeError("Incompatible database schema; run alembic upgrade head.")
