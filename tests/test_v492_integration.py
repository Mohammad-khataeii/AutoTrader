"""Genuine loss replay and actual read-only PostgreSQL collection."""
import asyncio
import json
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.engine import make_url

from autotrader.clock import at
from autotrader.domain import OrderBook, OrderBookLevel, Side
from autotrader.execution.pricing import quote_execution
from autotrader.learning.store import Store
from autotrader.learning.worker import _locked_tick, connect
from test_v47_paper import paper as paper_fixture
from test_v492_learning import evidence

paper = paper_fixture
ROOT = Path(__file__).parents[1]


def test_genuine_pepe_loss_replays_both_saved_books_and_fees():
    dataset=json.loads((ROOT/'docs/evidence/v4_9_2/forensics.json').read_text())
    trade=dataset['trades'][-1]
    assert trade['execution_profile']=='4.9.1-paper.1' and trade['stop_condition_consistent']
    quantity=D(trade['quantity']);quotes=[]
    for side,key in [(Side.BUY,'original_entry_book'),(Side.SELL,'original_exit_book')]:
        b=trade[key];observed=datetime.fromisoformat(b['timestamp'])
        book=OrderBook('PEPE-EUR',observed,tuple(OrderBookLevel(D(p),D(q)) for p,q in b['bids']),
            tuple(OrderBookLevel(D(p),D(q)) for p,q in b['asks']),b['source'])
        with at(observed):
            quotes.append(quote_execution(book,side,quantity,quantity_step=D(10),fee_bps=D(10),slippage_bps=D(8)))
    buy,sell=quotes
    assert buy.vwap==D(trade['entry_price']) and sell.vwap==D(trade['exit_price'])
    assert sell.net_cash_change+buy.net_cash_change==D('-18.338337569309')
    assert buy.fee+sell.fee==D(trade['fees_eur'])
    assert dataset['primary']['net_pnl_eur']=='-56.724117969028'
    assert sum(D(t['net_pnl_eur']) for t in dataset['trades'])==D(dataset['primary']['net_pnl_eur'])
    assert len(dataset['shadows'])==15


async def test_collector_read_only_restart_and_ledger_preservation(paper,pg_repo,tmp_path):
    _service,repo=paper
    e=evidence()
    async with repo.session_factory() as db,db.begin():
        await db.execute(text("INSERT INTO strategy_signals(signal_id,strategy_id,symbol,timestamp,score,data_quality,payload_json,created_at) VALUES ('causal_signal','RAOE_TREND_PULLBACK','TEST-EUR',:stamp,1,'GOOD',:payload,:stamp)"),
            {'stamp':datetime.fromisoformat('2026-01-01T00:00:00+00:00'),'payload':json.dumps({'evidence':e})})
    before=await repo.snapshot()
    settings=SimpleNamespace(database_url=pg_repo.test_database_url,personal_paper_enabled=True,live_trading_enabled=False)
    await asyncio.to_thread(_locked_tick,settings,tmp_path)
    await asyncio.to_thread(_locked_tick,settings,tmp_path)
    after=await repo.snapshot()
    for key in ('cash','reserved_cash','positions','orders','realized_pnl'):assert before[key]==after[key]
    assert await repo.verify_invariants(D(7000))==[]
    store=Store(tmp_path)
    assert store.db.execute('SELECT count(*) FROM observations').fetchone()[0]==0
    assert store.db.execute('SELECT disposition FROM funnel').fetchone()[0]=='SOURCE_EXCLUDED'  # retained synthetic coverage exclusion
    assert store.get('v493_backfill_cursor')[1]=='causal_signal'
    store.close()
    def check():
        with connect(make_url(pg_repo.test_database_url)) as conn:
            assert conn.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']=='on'
            try:conn.execute("UPDATE accounts SET control='STOPPED'")
            except Exception as error:assert type(error).__name__=='ReadOnlySqlTransaction'
            else:raise AssertionError('Research source connection allowed a financial mutation')
    await asyncio.to_thread(check)


def test_entry_candles_were_first_seen_before_pepe_entry_and_reproduce_admission():
    import gzip
    from collections import defaultdict

    from autotrader.domain import Candle
    from autotrader.personal_paper.admission import checks, completed_context
    rows=defaultdict(list)
    p=json.loads((ROOT/'docs/evidence/v4_9_2/forensics.json').read_text())['trades'][-1]
    opened=datetime.fromisoformat(p['entry_at'])
    with gzip.open(ROOT/'docs/evidence/v4_9_2/entry-candles.jsonl.gz','rt') as exported:
        for line in exported:
            r=json.loads(line);c=r['candle']
            assert datetime.fromisoformat(r['first_observed_at'])<=opened
            rows[c['symbol']].append(Candle(c['symbol'],datetime.fromisoformat(c['timestamp']),
                *[D(c[k]) for k in ('open','high','low','close','volume')],timeframe='5m',source=c['source']))
    proof=p['original_entry_evidence']['primary_admission']
    inputs=completed_context(rows['PEPE-EUR'],rows,datetime.fromisoformat(proof['evaluation_cutoff']))
    assert inputs==proof['inputs']
    assert checks(p['strategy'],inputs,proof['candle_at'],proof['evaluation_cutoff'],opened)==proof['gates']
    assert p['completed_candle_hash_reconstruction']['matches_original_entry_data_hash']
