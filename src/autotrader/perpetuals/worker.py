"""Independent worker; only the explicit paper research profile starts it."""
from __future__ import annotations

import asyncio
import os
import signal
import httpx
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from autotrader.logging_config import configure_logging
from autotrader.perpetuals.service import Perpetuals, flag
from autotrader.persistence.database import make_session_factory


def migrate(url: str) -> None:
    cfg = Config()
    root = Path(os.getenv("AUTOTRADER_MIGRATIONS_ROOT", str(Path.cwd())))
    path = root / "alembic" / "perpetuals"
    if not path.is_dir():
        path = Path(__file__).resolve().parents[3] / "alembic" / "perpetuals"
    cfg.set_main_option("script_location", str(path))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")


async def main() -> None:
    if (
        not flag("PAPER_PERPETUALS_ENABLED") or not flag("PAPER_TRADING_ENABLED")
        or os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "false"
        or os.getenv("MARKET_DATA_REPLAY_FILE")
        or os.getenv("ENVIRONMENT") not in {"local", "staging"}
    ):
        raise RuntimeError("Perpetuals worker requires explicit local/staging paper mode")
    url = os.environ["DATABASE_URL"]
    if os.getenv("ENVIRONMENT") == "staging" and make_url(url).database != "autotrader_aruba_staging":
        raise RuntimeError("Perpetuals staging database identity mismatch")
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stopping.set)
    await asyncio.to_thread(migrate, url)
    engine = create_async_engine(url, pool_pre_ping=True, hide_parameters=True)
    try:
        factory = make_session_factory(engine)
        legacy_task = asyncio.create_task(Perpetuals(factory).run(stopping))
        multi_task = None
        try:
            if flag("PAPER_MULTI_PERPETUALS_ENABLED"):
                from autotrader.perpetuals.multi.ledger import MultiLedger
                from autotrader.perpetuals.multi.market import MultiMarket
                from autotrader.perpetuals.multi.runtime import MultiRuntime
                # Separate HTTP pools and tasks keep scanning independent of protection.
                async with httpx.AsyncClient(timeout=4, follow_redirects=False) as scan_client, \
                        httpx.AsyncClient(timeout=3, follow_redirects=False) as protect_client:
                    multi_task = asyncio.create_task(MultiRuntime(MultiLedger(factory),
                        MultiMarket(scan_client, protect_client)).run(stopping))
                    await legacy_task
            else:
                await legacy_task
        finally:
            if multi_task:
                multi_task.cancel()
                await asyncio.gather(multi_task, return_exceptions=True)
            legacy_task.cancel()
            await asyncio.gather(legacy_task, return_exceptions=True)
    finally:
        await engine.dispose()


def run() -> None:
    configure_logging()
    asyncio.run(main())


if __name__ == "__main__":
    run()
