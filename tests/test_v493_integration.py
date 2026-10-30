"""Engineering fixture: stage-aware SQL collection, cutoff and restart recovery.

Prospective-source marker exercises the collector branch only; fixture prices
are synthetic acceptance and provide no performance or market evidence.
"""
import asyncio
import json
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace

from sqlalchemy import text

from autotrader.clock import at
from autotrader.learning.store import Store
from autotrader.learning.worker import _locked_tick
from test_v47_paper import paper as paper_fixture
from test_v493_learning import NOW, event

paper=paper_fixture


async def test_source_stages_priority_cutoff_restart_and_financial_read_only(paper,pg_repo,tmp_path):
    _service,repo=paper;before=await repo.snapshot()
    # Only the disposable official test registry's source marker is changed.
    async with pg_repo.session_factory() as db,db.begin():
        original=(await db.execute(text("SELECT payload_json FROM system_state WHERE key='personal_paper_v47'"))).scalar_one()
        manifest=json.loads(original);manifest['data_kind']='REVOLUT_X_PROSPECTIVE_PAPER'
        await db.execute(text("UPDATE system_state SET payload_json=:p WHERE key='personal_paper_v47'"),{'p':json.dumps(manifest)})
    e=event()['evidence']
    async with repo.session_factory() as db,db.begin():
        for identity,when in [('fixture-current',NOW),('fixture-future',NOW+timedelta(days=1))]:
            await db.execute(text("INSERT INTO strategy_signals(signal_id,strategy_id,symbol,timestamp,score,data_quality,payload_json,created_at) VALUES (:id,'RAOE_TREND_PULLBACK','TEST-EUR',:stamp,1,'GOOD',:payload,:stamp)"),{'id':identity,'stamp':when,'payload':json.dumps({'evidence':e})})
    settings=SimpleNamespace(database_url=pg_repo.test_database_url,personal_paper_enabled=True,live_trading_enabled=False)
    with at(NOW+timedelta(seconds=30)):
        await asyncio.to_thread(_locked_tick,settings,tmp_path)
        await asyncio.to_thread(_locked_tick,settings,tmp_path)
    s=Store(tmp_path)
    assert s.db.execute('SELECT id,stage,disposition FROM funnel').fetchall()==[('fixture-current','TECHNICAL_REJECTED','OBSERVED')]
    assert s.db.execute('SELECT id,status FROM market_observations').fetchall()==[('fixture-current','PENDING')]
    assert s.db.execute('SELECT count(*) FROM observations').fetchone()[0]==0
    assert s.get('v493_fresh_cursor')[1]==s.get('v493_backfill_cursor')[1]=='fixture-current'
    s.close();after=await repo.snapshot()
    for key in ('cash','reserved_cash','positions','orders','realized_pnl'):assert before[key]==after[key]
    assert await repo.verify_invariants(D(7000))==[]
