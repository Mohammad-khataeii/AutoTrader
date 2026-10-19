from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path

from autotrader.config import get_settings
from autotrader.domain import new_id
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.research.strategies import StrategyParameters
from autotrader.research.workflow import run_full


async def main() -> None:
    settings = get_settings()
    engine = make_engine(settings)
    await create_schema(engine)
    repo = PersistentTradingRepository(make_session_factory(engine))
    await repo.initialize_portfolio(settings.initial_cash_eur)
    owner = new_id("researchworker")
    root = Path(settings.research_root)
    try:
        while True:
            job = await repo.claim_research(owner)
            if job is None:
                await asyncio.sleep(5)
                continue
            try:
                catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
                request = job["request"]
                grid = tuple(StrategyParameters(**{k:Decimal(v) for k,v in row.items()}) for row in request["grid"])
                task = asyncio.create_task(asyncio.to_thread(run_full, root, catalog,
                    timeframes=tuple(request["timeframes"]), strategy_ids=tuple(request["strategies"]),
                    grid=grid, assets=tuple(request["assets"])))
                while not task.done():
                    await asyncio.wait({task}, timeout=15)
                    if not task.done():
                        await repo.update_research_job(job["job_id"], owner)
                report = await task
                result = {"run_id":report["run_id"], "verdict":report["verdict"]}
            except Exception as exc:
                result = {"error":type(exc).__name__ + ":" + str(exc)}
            await repo.update_research_job(job["job_id"], owner, result)
    finally:
        await engine.dispose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
