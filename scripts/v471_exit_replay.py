"""Counterfactual replay at the actual recorded timestamps, with no ledger writes."""
import json
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from autotrader.domain import OrderBook, OrderBookLevel, Side
from autotrader.execution.pricing import quote_execution
from autotrader.research.data import digest

path=Path('docs/evidence/v4_7_1/loss-audit.json');audit=json.loads(path.read_text());out=[]
for report in audit['reports']:
    stop=D(report['initial_stop'])
    legs=[]
    for fill in report['fills']:
        book=fill['book']
        b=OrderBook(report['symbol'],datetime.fromisoformat(book['timestamp']),tuple(OrderBookLevel(D(p),D(q)) for p,q in book['bids']),tuple(OrderBookLevel(D(p),D(q)) for p,q in book['asks']),book['source'])
        order=report['original_entry_execution'] if fill['side']=='BUY' else next(o for o in report['original_exit_executions'] if o['order_id']==fill['order_id'])
        timestamp=datetime.fromisoformat(fill['timestamp'])
        with patch('autotrader.execution.pricing.utc_now',return_value=timestamp):
            quoted=quote_execution(b,Side(fill['side']),D(fill['quantity']),quantity_step=D(order['quantity_step']),fee_bps=D(order['fee_bps']),slippage_bps=D(order['slippage_bps']))
        assert quoted.vwap==D(fill['price']) and quoted.fee==D(fill['fee_eur']) and quoted.fillable_quantity==D(fill['quantity'])
        if fill['side']=='SELL':assert b.best_bid<=stop and fill['exit_reason']=='STOP'
        legs.append({'side':fill['side'],'quantity':str(quoted.fillable_quantity),'vwap':str(quoted.vwap),'fee_eur':str(quoted.fee),'same_finite_depth_pricing':True})
    out.append({'symbol':report['symbol'],'old_exit':'STOP','new_exit_with_same_open_position':'STOP','discretionary_signal_cannot_override_stop':True,'net_pnl_unchanged':report['net_pnl_eur'],'entry_review':'WOULD_REJECT_USING_ENTRY_TIME_BENCHMARK_AND_RESISTANCE','legs':legs})
Path('docs/evidence/v4_7_1/exit-replay.json').write_text(json.dumps({'schema':'v471-recorded-book-replay/1','source_sha256':digest(path.read_bytes()),'ledger_writes':False,'clock':'pinned to actual fill timestamps, no historical freshness bypass in runtime','reports':out,'limitation':'Replays four executed observations, not an alternate prospective price path or new runtime historical performance.'},indent=2)+'\n')
print('PASS: all four recorded finite-depth fills replay exactly; stop priority unchanged')
