from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from decimal import Decimal

import pytest
from sqlalchemy import text

from autotrader.domain import RuntimeHealth
from autotrader.persistence.repository import PersistentTradingRepository

pytestmark = [pytest.mark.asyncio, pytest.mark.legacy_schema]


async def migrate(repo: PersistentTradingRepository, revision: str, *, fail: bool = False) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "ENVIRONMENT":"test"}
    if fail:
        env["AUTOTRADER_MIGRATION_FAILPOINT"] = "after_ddl"
    return await asyncio.to_thread(subprocess.run,[sys.executable,"-m","alembic","-x",
        f"dburl={repo.test_database_url}","upgrade",revision],  # type: ignore[attr-defined]
        env=env,capture_output=True,text=True)


async def test_populated_v33_history_is_preserved_and_quarantined(pg_repo: PersistentTradingRepository) -> None:
    async with pg_repo.session_factory() as s, s.begin():
        await s.execute(text("INSERT INTO balances(asset,available,reserved) VALUES ('EUR',400,0)"))
        await s.execute(text("INSERT INTO positions(position_id,symbol,quantity,average_entry_price,realized_pnl,state,opened_at) VALUES ('old','BTC-EUR',1,100,0,'OPEN',CURRENT_TIMESTAMP)"))
        await s.execute(text("INSERT INTO orders(order_id,client_order_id,symbol,side,order_type,status,quantity,quote_amount,simulated) VALUES ('o','k','BTC-EUR','BUY','MARKET','FILLED',1,100,true)"))
        await s.execute(text("INSERT INTO fills(fill_id,order_id,symbol,side,quantity,price,fee,simulated) VALUES ('f','o','BTC-EUR','BUY',1,100,0,true)"))
    result = await migrate(pg_repo,"0005_v3_3_ledger")
    assert result.returncode == 0,result.stderr
    async with pg_repo.session_factory() as s, s.begin():
        assert (await s.execute(text("SELECT position_id FROM fills WHERE fill_id='f'"))).scalar() is None
        await s.execute(text("INSERT INTO positions(position_id,symbol,quantity,average_entry_price,realized_pnl,state,opened_at) VALUES ('second','BTC-EUR',0,90,0,'CLOSED',CURRENT_TIMESTAMP)"))
        # Emulate an already-deployed old 0005 guess. The new migration must distrust it.
        await s.execute(text("UPDATE fills SET position_id='old' WHERE fill_id='f'"))
    result = await migrate(pg_repo,"head")
    assert result.returncode == 0,result.stderr
    async with pg_repo.session_factory() as s:
        row = (await s.execute(text("SELECT position_id,attribution_status,quantity,price FROM fills WHERE fill_id='f'"))).one()
        assert row == (None,"UNRESOLVED",Decimal(1),Decimal(100))
        assert (await s.execute(text("SELECT previous_position_id FROM legacy_attribution_report WHERE fill_id='f'"))).scalar() == "old"
        assert (await s.execute(text("SELECT COUNT(*) FROM positions"))).scalar() == 2
    await pg_repo.initialize_portfolio(Decimal(500))
    assert await pg_repo.get_runtime_health() is RuntimeHealth.RECONCILIATION_REQUIRED
    problems = await pg_repo.verify_invariants(Decimal(500))
    assert "unresolved_legacy_fill_attribution" in problems
    assert "missing_or_incorrect_initial_funding" in problems
    from autotrader.persistence.corrections import review_projection_repair
    await pg_repo.set_control('pause')
    with pytest.raises(ValueError,match='Immutable history requires reviewed remediation'):
        await review_projection_repair(pg_repo)
    async with pg_repo.session_factory() as s:
        assert (await s.execute(text("SELECT COUNT(*) FROM financial_journal"))).scalar() == 0


async def test_failed_postgres_migration_rolls_back_and_retries(pg_repo: PersistentTradingRepository) -> None:
    assert (await migrate(pg_repo,"0005_v3_3_ledger")).returncode == 0
    failed = await migrate(pg_repo,"head",fail=True)
    assert failed.returncode != 0 and "Injected migration failure" in failed.stderr
    async with pg_repo.session_factory() as s:
        assert (await s.execute(text("SELECT version_num FROM alembic_version"))).scalar() == "0005_v3_3_ledger"
        assert (await s.execute(text("SELECT to_regclass('financial_journal')"))).scalar() is None
    retried = await migrate(pg_repo,"head")
    assert retried.returncode == 0,retried.stderr
    await pg_repo.initialize_portfolio(Decimal(500))
    assert await pg_repo.verify_invariants(Decimal(500)) == []
