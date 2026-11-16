"""Read-only causal replay for exploratory paper entry; no broker calls."""
from __future__ import annotations
import argparse
import bisect
import json
from datetime import datetime, timedelta
from . import alpaca_crypto as ac
from .crypto_active_paper import benchmark_ok
from .crypto_strategy_replay import _trade, _fmt, FEE_PER_SIDE, SLIPPAGE_PER_SIDE
from .storage import DB_PATH, connect_readonly


def run(db_path=DB_PATH, holdout_days=7):
    trades=[]
    candidate_hours=0
    ready=0
    with connect_readonly(db_path) as conn:
        btc=[dict(x) for x in conn.execute("SELECT ts,o,h,l,c,v FROM ac_bars WHERE symbol='BTC/USD' AND timeframe='1Hour' ORDER BY ts")]
        btc_index={b['ts']:i for i,b in enumerate(btc)}
        latest=None
        for symbol in ac.EXECUTION_PAIRS:
            h=[dict(x) for x in conn.execute("SELECT ts,o,h,l,c,v FROM ac_bars WHERE symbol=? AND timeframe='1Hour' ORDER BY ts",(symbol,))]
            d=[dict(x) for x in conn.execute("SELECT ts,o,h,l,c,v FROM ac_bars WHERE symbol=? AND timeframe='1Day' ORDER BY ts",(symbol,))]
            if len(h)<230 or len(d)<220:
                continue
            ready+=1
            daily_ts=[x['ts'] for x in d]
            block_until=0
            for i in range(219,len(h)-1):
                at=datetime.fromisoformat(h[i]['ts'])+timedelta(hours=1)
                n=bisect.bisect_left(daily_ts,ac._floor(at,'1Day').isoformat())
                if n<220:
                    continue
                signal=ac.evaluate_completed_bars(symbol,h[max(0,i-259):i+1],d[max(0,n-260):n],at,allow_active_paper=True)
                if signal['reason']!='paper_active_hourly_reclaim':
                    continue
                candidate_hours+=1
                if i<block_until:
                    continue
                if symbol!='BTC/USD':
                    j=btc_index.get(signal['bar_at'])
                    if j is None or not benchmark_ok(btc[max(0,j-3):j+1],signal['bar_at']):
                        continue
                trade,held=_trade(symbol,signal,h[i+1:],fee=FEE_PER_SIDE,slip=SLIPPAGE_PER_SIDE)
                if trade:
                    trades.append(trade)
                    block_until=i+1+held
            if h and (latest is None or h[-1]['ts']>latest):
                latest=h[-1]['ts']
    cutoff=(datetime.fromisoformat(latest)-timedelta(days=holdout_days)).isoformat() if latest else ''
    return {'state':'REPLAY_COMPLETE' if latest else 'INSUFFICIENT_HISTORY',
            'ready_symbols':ready,'candidate_hours':candidate_hours,
            'all':_fmt(trades),'holdout':_fmt([t for t in trades if t['at']>=cutoff]),
            'holdout_start':cutoff,'fees_per_side':FEE_PER_SIDE,
            'slippage_per_side':SLIPPAGE_PER_SIDE,
            'approved_for_live':False,'broker_orders_sent':0,
            'note':'Midpoint replay cannot prove fills, spreads, depth or profitability. No lookahead.'}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',default=DB_PATH)
    p.add_argument('--holdout-days',type=int,default=7)
    a=p.parse_args()
    print(json.dumps(run(a.db,a.holdout_days),indent=2,sort_keys=True))


if __name__=='__main__':
    main()
