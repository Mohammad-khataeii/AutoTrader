"""Deterministic virtual USD fills. Paper orders queued AFTER close, filled at NEXT published session open.

All actions are ledger-only. No brokerage orders, transfers, exchange credentials or live mode.
"""
from __future__ import annotations
import hashlib
import json
import math
from datetime import date
from .storage import connect,one,rows,utc
from .signals import evaluate,POLICY_VERSION

FRICTION_BPS=12.0
MAX_POSITIONS=5
MAX_SYMBOL_WEIGHT=.12
MAX_SECTOR_WEIGHT=.26
MAX_GROSS_EXPOSURE=.60
MAX_DRAWDOWN=.12
MAX_ONE_DAY_LOSS=.035
MAX_VOLATILITY=.70
SCORE_MIN=2.0

def order_key(symbol,day,side):return hashlib.sha256(f'sw1:{symbol}:{day}:{side}'.encode()).hexdigest()[:28]

def latest_bars(symbol,max_count=600):
    return list(reversed(rows('SELECT day,o,h,l,c,v,source,adjustment FROM bars WHERE symbol=? ORDER BY day DESC LIMIT ?', (symbol,max_count))))

def mark_to_market():
    account=one('SELECT * FROM portfolio WHERE id=1')
    held=rows('SELECT * FROM positions ORDER BY symbol')
    values=[];exposure=0.0
    for p in held:
        bar=one('SELECT day,c,source FROM bars WHERE symbol=? ORDER BY day DESC LIMIT 1',(p['symbol'],))
        mark=bar['c'] if bar else p['avg_cost']
        val=p['qty']*mark;exposure+=val
        values.append({**p,'mark':mark,'market_day':bar['day'] if bar else None,
                       'market_value':round(val,2),'unrealized':round(val-p['qty']*p['avg_cost'],2)})
    eq=account['cash']+exposure
    dd=max(0,(account['high_water']-eq)/max(1,account['high_water']))
    return account,values,round(eq,2),round(exposure,2),dd

def settle_pending():
    """Only fill with a new subsequently published bar, NEVER on signal day's bar."""
    open_orders=rows("SELECT * FROM pending_orders WHERE state='PENDING' ORDER BY created_at,id")
    count=0
    for pending in open_orders:
        future=one('SELECT * FROM bars WHERE symbol=? AND day>? ORDER BY day LIMIT 1',
                   (pending['symbol'],pending['signal_day']))
        if not future:continue
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            order=c.execute('SELECT * FROM pending_orders WHERE id=?',(pending['id'],)).fetchone()
            if not order or order['state']!='PENDING':c.rollback();continue
            p=c.execute('SELECT * FROM portfolio WHERE id=1').fetchone()
            held=c.execute('SELECT * FROM positions WHERE symbol=?',(order['symbol'],)).fetchone()
            entry=float(future['o']);side=order['side']
            # Guard splits, feed discontinuities and unrealistic gaps. No fabricated adjusted fills.
            prev=c.execute('SELECT c FROM bars WHERE symbol=? AND day=?',(order['symbol'],order['signal_day'])).fetchone()
            from datetime import date
            gap_days=(date.fromisoformat(future['day'])-date.fromisoformat(order['signal_day'])).days
            if not prev or gap_days>5 or abs(entry/prev['c']-1)>.27 or entry<=0:
                c.execute("UPDATE pending_orders SET state='CANCELLED' WHERE id=?",(order['id'],));c.commit();continue
            if side=='BUY':
                if held is not None or p['paused']:
                    c.execute("UPDATE pending_orders SET state='CANCELLED' WHERE id=?",(order['id'],));c.commit();continue
                balance=c.execute('SELECT cash FROM portfolio WHERE id=1').fetchone()['cash']
                # cap per-symbol, retain reserve; staged allocation limited to 12% INITIAL/mark equity.
                last_exposure=c.execute('''SELECT COALESCE(SUM(qty * COALESCE((SELECT b.c FROM bars b WHERE b.symbol=positions.symbol ORDER BY b.day DESC LIMIT 1),avg_cost)),0) FROM positions''').fetchone()[0]
                equity_est=max(0,min(p['initial_cash'],balance+float(last_exposure))) # cap at equity AND original capital
                fillprice=entry*(1+FRICTION_BPS/10000)
                qty=min(int(equity_est*MAX_SYMBOL_WEIGHT/fillprice),int(max(0,balance-0.40*p['initial_cash'])/fillprice))
                if qty<1:
                    c.execute("UPDATE pending_orders SET state='CANCELLED' WHERE id=?",(order['id'],));c.commit();continue
                fee=0.0;spent=qty*fillprice+fee
                c.execute('UPDATE portfolio SET cash=cash-? WHERE id=1',(spent,))
                sector=c.execute('SELECT sector FROM assets WHERE symbol=?',(order['symbol'],)).fetchone()['sector']
                c.execute('INSERT INTO positions(symbol,qty,avg_cost,stop,entry_day,sector) VALUES(?,?,?,?,?,?)',
                          (order['symbol'],qty,fillprice,fillprice*.92,future['day'],sector))
                realized=0.0
            elif side=='SELL':
                if held is None:
                    c.execute("UPDATE pending_orders SET state='CANCELLED' WHERE id=?",(order['id'],));c.commit();continue
                qty=held['qty'];fillprice=entry*(1-FRICTION_BPS/10000);fee=0.0
                proceeds=qty*fillprice-fee;realized=proceeds-qty*held['avg_cost']
                c.execute('UPDATE portfolio SET cash=cash+?,realized=realized+? WHERE id=1',(proceeds,realized))
                c.execute('DELETE FROM positions WHERE symbol=?',(order['symbol'],))
            else:raise AssertionError('Invalid order')
            c.execute('UPDATE pending_orders SET state=?,fill_day=? WHERE id=?',('FILLED',future['day'],order['id']))
            c.execute('INSERT INTO fills(id,order_id,symbol,side,signal_day,fill_day,qty,price,slippage,fee,realized,source,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      ('fill:'+order['id'],order['id'],order['symbol'],side,order['signal_day'],future['day'],qty,fillprice,
                       abs(fillprice-entry),fee,realized,future['source'],utc()))
            c.commit();count+=1
    return count


def eligible_signals():
    spy=latest_bars('SPY');spy_map={b['day']:i for i,b in enumerate(spy)}
    latest_spy=spy[-1]['day'] if spy else None
    output=[]
    for a in rows("SELECT symbol,name,sector FROM assets WHERE enabled=1 AND sector<>'Benchmark' ORDER BY symbol"):
        bars=latest_bars(a['symbol'])
        if not bars:continue
        # Cross-date matching to prevent using a benchmark bar after the market observation.
        index=spy_map.get(bars[-1]['day'])
        benchmark=spy[:index+1] if index is not None else []
        ev=evaluate(bars,benchmark)
        if ev:
            output.append({'symbol':a['symbol'],'name':a['name'],'sector':a['sector'],'day':bars[-1]['day'],**ev,
                           'source':bars[-1]['source'],'adjustment':bars[-1]['adjustment']})
    return sorted(output,key=lambda r:(-r['score'],r['symbol'])),latest_spy


def decide_and_queue(observer=None):
    """Runs only against latest closed EOD bars; by source date, no current quote assumption."""
    settle_pending()
    signals,benchmark_day=eligible_signals()
    if not signals:return {'status':'WAITING_FOR_HISTORY','processed':0}
    account,held,equity,exposure,dd=mark_to_market()
    held_by={x['symbol']:x for x in held}
    spy=latest_bars('SPY')
    if len(spy)<201 or not benchmark_day:return {'status':'WAITING_FOR_BENCHMARK','processed':0}
    # If provider is blocked or data older than latest recorded completed session, fail closed.
    from datetime import datetime,timezone,timedelta
    age=(datetime.now(timezone.utc).date()-date.fromisoformat(benchmark_day)).days
    if age>5:return {'status':'STALE_MARKET','processed':0,'age_days':age}
    if account['paused'] or dd>=MAX_DRAWDOWN:
        if dd>=MAX_DRAWDOWN:
            with connect() as c:c.execute('UPDATE portfolio SET paused=1 WHERE id=1')
        return {'status':'PAUSED_OR_DRAWDOWN','processed':0}
    # Market regime based ONLY on SPY history at last known date.
    risk_on=spy[-1]['c']>sum(x['c'] for x in spy[-200:])/200
    total_positions=len(held)
    weight=exposure/max(1,equity)
    sector_exp={}
    for p in held:sector_exp[p['sector']]=sector_exp.get(p['sector'],0)+p['market_value']
    pending=rows("SELECT * FROM pending_orders WHERE state='PENDING'")
    pending_syms={p['symbol'] for p in pending}
    # Reserve sector headroom for BUY orders already queued on earlier scans.
    for q in pending:
        if q['side']=='BUY':
            rec=one('SELECT sector FROM assets WHERE symbol=?',(q['symbol'],))
            if rec:sector_exp[rec['sector']]=sector_exp.get(rec['sector'],0)+equity*MAX_SYMBOL_WEIGHT
    today=benchmark_day
    purchases=0;actions=0
    last_eq=one('SELECT equity FROM equity_curve ORDER BY day DESC LIMIT 1')
    day_loss=bool(last_eq and equity<last_eq['equity']*(1-MAX_ONE_DAY_LOSS))
    for s in signals:
        # Signals are recorded for transparency, independent of trade admission.
        if s['day']!=today:continue
        sym=s['symbol'];p=held_by.get(sym)
        sell=bool(p and (s['score']<.8 or s['features']['close']<p['stop'] or s['features']['close']<s['features']['sma50']*.96))
        buy=bool(not p and sym not in pending_syms and risk_on and not day_loss and s['score']>=SCORE_MIN
                 and s['features']['volatility_annual']<MAX_VOLATILITY and total_positions+len(pending)+purchases<MAX_POSITIONS
                 and weight+MAX_SYMBOL_WEIGHT<=MAX_GROSS_EXPOSURE+.0001
                 and sector_exp.get(s['sector'],0)+equity*MAX_SYMBOL_WEIGHT<=equity*MAX_SECTOR_WEIGHT
                 and purchases<2 and s['adjustment'] in ('RAW','VENDOR_UNSPECIFIED'))
        action='SELL' if sell else 'BUY' if buy else 'WATCH'
        reasons=list(s['reasons']);
        if s['adjustment']=='VENDOR_UNSPECIFIED':reasons.append('provider corporate-action adjustment unverified')
        if day_loss:reasons.append('daily equity loss risk gate')
        if not risk_on:reasons.append('market regime risk off')
        key=order_key(sym,today,action)
        # Preserve the EXACT point-in-time features and source/adjustment that informed
        # this action, including rejected/watch candidates, for future learning.
        features_payload=json.dumps(s['features'],sort_keys=True,separators=(',',':'),default=str)
        snapshot_payload=json.dumps({'symbol':sym,'day':today,'policy':POLICY_VERSION,
                                     'score':s['score'],'features':s['features'],
                                     'signals':s['signals'],'reasons':reasons,'action':action,
                                     'source':s['source'],'adjustment':s['adjustment']},
                                    sort_keys=True,separators=(',',':'),default=str)
        fingerprint=hashlib.sha256(snapshot_payload.encode()).hexdigest()
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute("""INSERT OR IGNORE INTO sw_signal_snapshots
                (id,run_id,symbol,signal_day,policy_version,score,regime,action,source,
                 adjustment,features_json,signals_json,reasons_json,recorded_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (fingerprint,observer.id if observer else 'legacy',sym,today,POLICY_VERSION,
                  s['score'],s['regime'],action,s['source'],s['adjustment'],features_payload,
                  json.dumps(s['signals'],sort_keys=True,default=str),
                  json.dumps(reasons,default=str),utc()))
            c.execute('INSERT OR IGNORE INTO decisions(id,symbol,signal_day,score,regime,signals_json,reasons_json,action,policy_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      ('dec:'+key,sym,today,s['score'],s['regime'],json.dumps(s['signals']),json.dumps(reasons),action,POLICY_VERSION,utc()))
            if action in ('BUY','SELL'):
                c.execute('INSERT OR IGNORE INTO pending_orders(id,symbol,side,signal_day,decision,created_at,state) VALUES(?,?,?,?,?,?,?)',
                          (order_key(sym,today,action),sym,action,today,'dec:'+key,utc(),'PENDING'))
            c.commit()
        if observer is not None:
            observer.event('SIGNAL_EVALUATED','OK' if action != 'WATCH' else 'INFO',
                           'Decision evaluated from recorded features',symbol=sym,
                           action=action,score=float(s['score']),market_day=today,
                           policy=POLICY_VERSION,source=s['source'])
        if buy:
            purchases+=1;total_positions+=1;weight+=MAX_SYMBOL_WEIGHT
            sector_exp[s['sector']]=sector_exp.get(s['sector'],0)+equity*MAX_SYMBOL_WEIGHT
        actions+=int(buy or sell)
    with connect() as c:
        c.execute('UPDATE portfolio SET high_water=MAX(high_water,?) WHERE id=1',(equity,))
        hi=max(account['high_water'],equity);drawdown=max(0,(hi-equity)/max(1,hi))
        spy_close=spy[-1]['c']
        c.execute('INSERT OR IGNORE INTO equity_curve(day,equity,cash,exposure,drawdown,spy_close,created_at) VALUES(?,?,?,?,?,?,?)',
                  (today,equity,account['cash'],exposure,drawdown,spy_close,utc()))
    return {'status':'PAPER_ORDERS_QUEUED' if actions else 'WATCHING','processed':len(signals),'orders_queued':actions,
            'benchmark_day':today,'market_regime':'RISK_ON' if risk_on else 'RISK_OFF'}
