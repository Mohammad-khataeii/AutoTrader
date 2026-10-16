from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from autotrader.persistence.repository import PersistentTradingRepository
from test_v34_migrations import migrate


@pytest.mark.legacy_schema
async def test_v4_to_v41_preserves_existing_ai_holds_and_financial_history(pg_repo: PersistentTradingRepository) -> None:
    result=await migrate(pg_repo,'0009_legacy_quarantine')
    assert result.returncode==0,result.stderr
    await pg_repo.initialize_portfolio(Decimal(500))
    before=await pg_repo.verify_invariants(Decimal(500))
    assert before==[]
    async with pg_repo.session_factory() as session,session.begin():
        await session.execute(text("INSERT INTO ai_budgets(month,spent,reserved) VALUES ('2026-10',0,0.03)"))
        await session.execute(text("INSERT INTO ai_usage(request_id,month,model,status,reserved_cost,input_tokens,output_tokens,provider,candidate_symbol,cached_input_tokens,cache_write_tokens,pricing_json) VALUES ('legacy-unit-hold','2026-10','fixture-model','UNKNOWN',0.03,0,0,'openai','BTC-EUR',0,0,'{}')"))
    result=await migrate(pg_repo,'head')
    assert result.returncode==0,result.stderr
    async with pg_repo.session_factory() as session:
        row=(await session.execute(text("SELECT status,reserved_cost,quota_timestamp=created_at FROM ai_usage WHERE request_id='legacy-unit-hold'"))).one()
        assert row==('OUTCOME_UNKNOWN',Decimal('.03'),True)
        assert (await session.execute(text("SELECT reserved FROM ai_budgets WHERE month='2026-10'"))).scalar()==Decimal('.03')
        assert (await session.execute(text('SELECT count(*) FROM financial_journal'))).scalar()==1
        assert (await session.execute(text('SELECT version_num FROM alembic_version'))).scalar()=='0010_v41_ai_quotas'
    assert await pg_repo.verify_invariants(Decimal(500))==[]
