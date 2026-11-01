"""V4.9.4 integration verification: null pattern_state unblocking, symbol loss cooldown, entry frequency."""
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

paper = paper_fixture


async def test_v494_worker_handles_null_pattern_state_without_crashing(paper, pg_repo, tmp_path):
    _service, repo = paper
    before = await repo.snapshot()
    async with pg_repo.session_factory() as db, db.begin():
        original = (await db.execute(text("SELECT payload_json FROM system_state WHERE key='personal_paper_v47'"))).scalar_one()
        manifest = json.loads(original)
        manifest['data_kind'] = 'REVOLUT_X_PROSPECTIVE_PAPER'
        await db.execute(text("UPDATE system_state SET payload_json=:p WHERE key='personal_paper_v47'"), {'p': json.dumps(manifest)})

    e = event()['evidence']
    # Explicitly test null pattern_state in production signal payload
    e['pattern_state'] = None
    async with repo.session_factory() as db, db.begin():
        await db.execute(text("INSERT INTO strategy_signals(signal_id,strategy_id,symbol,timestamp,score,data_quality,payload_json,created_at) VALUES ('sig-null-pattern','RAOE_TREND_PULLBACK','TEST-EUR',:stamp,1,'GOOD',:payload,:stamp)"),
                         {'stamp': NOW, 'payload': json.dumps({'evidence': e})})

    settings = SimpleNamespace(database_url=pg_repo.test_database_url, personal_paper_enabled=True, live_trading_enabled=False)
    with at(NOW + timedelta(seconds=30)):
        await asyncio.to_thread(_locked_tick, settings, tmp_path)

    s = Store(tmp_path)
    # The signal should be processed into funnel without crashing or creating collector-error.json
    assert not (tmp_path / 'collector-error.json').exists()
    assert s.db.execute("SELECT id FROM funnel WHERE id='sig-null-pattern'").fetchone() is not None
    s.close()
    after = await repo.snapshot()
    assert before['cash'] == after['cash']
    assert await repo.verify_invariants(D(7000)) == []
