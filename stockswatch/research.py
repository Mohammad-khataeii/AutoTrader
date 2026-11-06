"""Historical research and deliberately SHADOW-only chronological ML challenger.

No ML model is authorized to execute, size, or veto virtual orders.
"""
from __future__ import annotations
import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from .storage import rows,connect,utc
from .signals import historical_backtest,features,POLICY_VERSION

FEATURE_KEYS=('mom20','mom63','rel_mom63','z20','volume_ratio','volatility_annual')
HORIZON=5

def bseries(symbol):
    return rows('SELECT day,o,h,l,c,v,source,adjustment FROM bars WHERE symbol=? ORDER BY day',(symbol,))

def digest(stock_series):
    h=hashlib.sha256()
    for symbol in sorted(stock_series):
        bs=stock_series[symbol]
        h.update(f'{symbol}:{len(bs)}:{bs[0]["day"] if bs else ""}:{bs[-1]["day"] if bs else ""}:{bs[-1]["c"] if bs else ""};'.encode())
    return h.hexdigest()

def research_report():
    symbols=[r['symbol'] for r in rows('SELECT symbol FROM assets WHERE enabled=1 ORDER BY symbol')]
    data={s:bseries(s) for s in symbols};spy=data.get('SPY',[])
    source_hash=digest(data)
    result=[]
    for symbol in symbols:
        if symbol in {'SPY','QQQ'}:continue
        bars=data[symbol]
        for mode in ('ensemble','trend','momentum','breakout','mean_reversion'):
            metrics=historical_backtest(bars,spy,mode)
            if metrics['status']=='COMPUTED':metrics.update({'symbol':symbol})
            else:metrics={'symbol':symbol,'strategy':mode,**metrics}
            result.append(metrics)
    usable=[r for r in result if r['status']=='COMPUTED']
    by_strategy={}
    for mode in ('ensemble','trend','momentum','breakout','mean_reversion'):
        relevant=[r for r in usable if r['strategy']==mode]
        by_strategy[mode]={
            'count':len(relevant),'mean_return_pct':round(sum(r['return_pct'] for r in relevant)/len(relevant),3) if relevant else None,
            'mean_max_drawdown_pct':round(sum(r['max_drawdown_pct'] for r in relevant)/len(relevant),3) if relevant else None,
            'mean_buy_hold_pct':round(sum(r['buy_hold_pct'] for r in relevant if r['buy_hold_pct'] is not None)/len([r for r in relevant if r['buy_hold_pct'] is not None]),3) if any(r['buy_hold_pct'] is not None for r in relevant) else None,
        }
    report={'status':'COMPUTED_WITH_LIMITATIONS' if usable else 'INSUFFICIENT_DATA',
            'generated_at':utc(),'policy':POLICY_VERSION,'source_hash':source_hash,'total_backtests':len(usable),
            'source_coverage':{s:{'bars':len(bs),'first':bs[0]['day'] if bs else None,'latest':bs[-1]['day'] if bs else None,'source':bs[-1]['source'] if bs else None} for s,bs in data.items()},
            'by_strategy':by_strategy,'per_symbol':result,
            'warnings':['Fixed baseline rules were NOT optimized for historical returns',
                        'This study uses a CURRENT survivorship-biased watchlist; delisted companies are missing',
                        'Daily OHLCV data is not point-in-time corporate-action complete',
                        'No historical news or analyst-consensus data. Earnings surprises / PEAD NOT backtested',
                        'Backtest uses next bar open execution with a 15bps per-side friction estimate; no liquidity model',
                        'No unbiased out-of-sample edge is established from these backtests; no model auto-promotion']}
    key='research:'+source_hash[:16]
    with connect() as c:c.execute('INSERT OR IGNORE INTO research_runs(id,created_at,status,report_json,source_hash) VALUES(?,?,?,?,?)',
                                  (key,utc(),report['status'],json.dumps(report,separators=(',',':')),source_hash))
    return report


def logistic(x,w):
    z=max(-30,min(30,w[0]+sum(a*b for a,b in zip(x,w[1:]))))
    return 1/(1+math.exp(-z))

def train_and_evaluate():
    """Last ~25% dates are forward holdout; five-session purge; price features ONLY.
    Out-of-sample evaluation is never used for training or changing a deployed strategy.
    """
    symbols=[r['symbol'] for r in rows("SELECT symbol FROM assets WHERE enabled=1 AND symbol NOT IN ('SPY','QQQ')")]
    data={s:bseries(s) for s in symbols+['SPY']};spy=data.get('SPY',[])
    spy_map={b['day']:i for i,b in enumerate(spy)}
    samples=[]
    for sym in symbols:
        b=data[sym]
        if len(b)<365:continue
        for i in range(201,len(b)-HORIZON):
            ref_i=spy_map.get(b[i]['day'])
            if ref_i is None or ref_i<201:continue
            f=features(b[max(0,i-210):i+1],spy[max(0,ref_i-210):ref_i+1])
            if not f or not f['benchmark_available']:continue
            xs=[float(f[k]) for k in FEATURE_KEYS]
            if max(abs(x) for x in xs)>1000:continue
            y=int(b[i+HORIZON]['c']/b[i]['c']>1.01)
            samples.append({'day':b[i]['day'],'end_day':b[i+HORIZON]['day'],'symbol':sym,'x':xs,'y':y})
    dates=sorted({s['day'] for s in samples})
    if len(dates)<500 or len(samples)<1500:
        return {'status':'INSUFFICIENT_HISTORY','samples':len(samples),'trading_days':len(dates),'promoted':False}
    split=dates[int(len(dates)*0.75)]
    train=[s for s in samples if s['end_day']<split] # Label known before test cutoff. Embargo HORIZON.
    test=[s for s in samples if s['day']>=split]
    if min(len(train),len(test))<250:
        return {'status':'INSUFFICIENT_SPLIT','train':len(train),'test':len(test),'promoted':False}
    dims=len(FEATURE_KEYS)
    means=[sum(s['x'][j] for s in train)/len(train) for j in range(dims)]
    scales=[max(1e-5, math.sqrt(sum((s['x'][j]-means[j])**2 for s in train)/len(train))) for j in range(dims)]
    def norm(s):return [max(-5,min(5,(s['x'][j]-means[j])/scales[j])) for j in range(dims)]
    # Unshuffled, deterministic batch gradient; L2 penalty; no test-derived thresholds.
    weights=[0.0]*(dims+1)
    for epoch in range(60):
        grad=[0.0]*(dims+1)
        for s in train:
            x=norm(s);p=logistic(x,weights);d=p-s['y']
            grad[0]+=d
            for j,v in enumerate(x):grad[j+1]+=d*v
        step=0.09/(1+epoch/18)
        weights[0]-=step*grad[0]/len(train)
        for j in range(1,dims+1):weights[j]-=step*(grad[j]/len(train)+0.02*weights[j])
    scores=[(logistic(norm(s),weights),s['y']) for s in test]
    brier=sum((p-y)**2 for p,y in scores)/len(scores)
    nullprob=sum(s['y'] for s in train)/len(train)
    null_brier=sum((nullprob-y)**2 for _,y in scores)/len(scores)
    positive=sum(y for _,y in scores)
    # AUC using rank sum with tie averages.
    sorted_scores=sorted(scores,key=lambda x:x[0]);ranks=0.;i=0;n=len(scores)
    while i<n:
        j=i+1
        while j<n and sorted_scores[j][0]==sorted_scores[i][0]:j+=1
        ranks+=sum(sorted_scores[k][1] for k in range(i,j))*(i+j+1)/2
        i=j
    auc=(ranks-positive*(positive+1)/2)/(positive*(n-positive)) if 0<positive<n else None
    status='SHADOW_ONLY'
    metrics={'status':status,'promoted':False,'sample_count':len(samples),'train_count':len(train),
             'holdout_count':len(test),'holdout_start':split,'holdout_end':max(s['day'] for s in test),
             'target':'next-five-session-return > 1%', 'brier':round(brier,6),'no_skill_brier':round(null_brier,6),
             'holdout_auc':round(auc,5) if auc is not None else None,
             'better_than_null':brier<null_brier, 'positive_rate_holdout':round(positive/n,5),
             'limits':['Current-ticker universe only: survivorship bias','No corporate-action completeness',
                       'Single fixed forward holdout not multi-regime validation','No P&L promotion evidence','Non-trading research only']}
    source_hash=digest(data);rid='ml:'+source_hash[:16]
    weights_out={'intercept':weights[0],'weights':dict(zip(FEATURE_KEYS,weights[1:])),
                 'means':dict(zip(FEATURE_KEYS,means)),'stds':dict(zip(FEATURE_KEYS,scales)),
                 'horizon_sessions':HORIZON,'trained_until':split}
    with connect() as c:c.execute('INSERT OR IGNORE INTO model_runs(id,trained_at,cutoff_day,status,metrics_json,weights_json,source_hash) VALUES(?,?,?,?,?,?,?)',
        (rid,utc(),split,status,json.dumps(metrics,separators=(',',':')),json.dumps(weights_out,separators=(',',':')),source_hash))
    return metrics
