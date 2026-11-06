"""Fixed, causal price-only strategy baselines. All features use <=signal day's observations."""
from __future__ import annotations
from math import log, sqrt, isfinite
POLICY_VERSION='stockswatch-price-v1.0-frozen'

def avg(xs):return sum(xs)/len(xs) if xs else 0.0

def sigma(xs):
    if not xs:return 0.0
    m=avg(xs);return sqrt(avg([(v-m)**2 for v in xs]))

def returns(bars,window):
    return (bars[-1]['c']/bars[-window-1]['c']-1) if len(bars)>window and bars[-window-1]['c']>0 else None

def features(bars,benchmark=None):
    if len(bars)<201:return None
    c=[float(b['c']) for b in bars];v=[float(b['v']) for b in bars]
    daily=[c[i]/c[i-1]-1 for i in range(1,len(c)) if c[i-1]>0]
    if len(daily)<100:return None
    vol20=sigma(daily[-20:])*sqrt(252)
    sma20=avg(c[-20:]);sma50=avg(c[-50:]);sma200=avg(c[-200:])
    mom20=c[-1]/c[-21]-1;mom63=c[-1]/c[-64]-1
    oldmax=max(float(b['h']) for b in bars[-21:-1]);oldmin=min(float(b['l']) for b in bars[-21:-1])
    vratio=v[-1]/max(1,avg(v[-21:-1]))
    b63=returns(benchmark,63) if benchmark else None
    return dict(day=bars[-1]['day'],close=c[-1],sma20=sma20,sma50=sma50,sma200=sma200,
                mom20=mom20,mom63=mom63,volume_ratio=vratio,volatility_annual=vol20,
                breakout=c[-1]>oldmax*1.001,prev_high=oldmax,prev_low=oldmin,
                z20=(c[-1]-sma20)/(sigma(c[-20:]) or 1),rel_mom63=mom63-(b63 if b63 is not None else mom63),
                benchmark_available=b63 is not None)

def evaluate(bars,spy=None,kind='ensemble'):
    f=features(bars,spy)
    if f is None:return None
    trend=f['close']>f['sma50'] and f['sma20']>f['sma50'] and f['sma50']>f['sma200']
    momentum=f['mom63']>0.08 and f['rel_mom63']>0.0 and f['benchmark_available']
    breakout=f['breakout'] and f['volume_ratio']>=1.25
    reversion=f['z20']<-1.8 and f['close']>f['sma200'] and f['volatility_annual']<0.65
    signals={'trend':bool(trend),'momentum':bool(momentum),'breakout':bool(breakout),
             'mean_reversion':bool(reversion),'high_volatility':f['volatility_annual']>0.75}
    weights={'trend':1.1,'momentum':1.0,'breakout':1.1,'mean_reversion':0.9}
    score=sum(weights[k] for k in weights if signals[k])
    if signals['high_volatility']:score-=2.0
    if f['close']<f['sma200']:score-=0.8
    if kind in weights:score=weights[kind] if signals[kind] else 0.0
    reasons=[k.replace('_',' ') for k,v in signals.items() if v]
    if not f['benchmark_available']:reasons.append('benchmark history unavailable')
    return {'score':round(score,4),'signals':signals,'reasons':reasons,'features':f,
            'regime':'RISK_ON' if spy and len(spy)>200 and spy[-1]['c']>avg([b['c'] for b in spy[-200:]]) else 'RISK_OFF',
            'version':POLICY_VERSION}

def historical_backtest(bars,spy,kind='ensemble',fee_bps=15):
    """Long/cash single-symbol historical replay; signal at t close -> fill at t+1 open.
    No retrospective portfolio action at the signal close; never access tomorrow's bar for signal.
    """
    if len(bars)<260:return {'status':'INSUFFICIENT_DATA','bars':len(bars)}
    balance=10000.0;qty=0;entry=0.0;peak=balance;maxdd=0.0;trades=0;wins=0
    equity=[];entry_day=None
    from bisect import bisect_right
    spy_days=[b["day"] for b in spy] if spy else []
    for i in range(201,len(bars)-1):
        hist=bars[max(0,i-210):i+1]
        j=bisect_right(spy_days,bars[i]["day"])
        benchmark=spy[max(0,j-211):j] if spy and j else None
        ev=evaluate(hist,benchmark,kind)
        if ev is None:continue
        tomorrow=bars[i+1]
        # Only pretend to trade an next session open once the bar has completed.
        threshold=2.0 if kind=='ensemble' else 0.5
        if qty and (ev['score'] < (0.8 if kind=='ensemble' else 0.4) or ev['features']['close']<ev['features']['sma50']*0.96 or (i-int(entry_day or i)>40)):
            fill=float(tomorrow['o'])*(1-fee_bps/10000)
            balance+=qty*fill
            trades+=1;wins+=int(fill>entry);qty=0;entry_day=None
        elif not qty and ev['score']>=threshold and ev['regime']=='RISK_ON' and ev['features']['volatility_annual']<=0.70:
            fill=float(tomorrow['o'])*(1+fee_bps/10000)
            take=balance*0.90
            n=int(take/fill)
            if n>0:qty=n;entry=fill;entry_day=i;balance-=n*fill
        mark=balance+qty*float(tomorrow['c'])
        peak=max(peak,mark);maxdd=max(maxdd,(peak-mark)/peak)
        equity.append(mark)
    if qty:
        balance+=qty*float(bars[-1]['c'])*(1-fee_bps/10000);trades+=1;wins+=int(bars[-1]['c']>entry)
    first=equity[0] if equity else 10000;last=balance
    ret=(last/10000-1)
    # Buy and hold uses first signal-eligible next open, same fee per entry/exit.
    ref0=float(bars[202]['o']);ref1=float(bars[-1]['c'])
    benchmark_ret=(ref1/ref0-1-2*fee_bps/10000) if ref0>0 else None
    return {'status':'COMPUTED','strategy':kind,'bars':len(bars),'start_day':bars[202]['day'],
            'end_day':bars[-1]['day'],'trades':trades,'win_rate':round(wins/trades,5) if trades else None,
            'return_pct':round(ret*100,3),'buy_hold_pct':round(100*benchmark_ret,3) if benchmark_ret is not None else None,
            'max_drawdown_pct':round(100*maxdd,3),'fee_slippage_bps_per_side':fee_bps,
            'survivorship_bias':'PRESENT: configured current-stock watchlist, delistings not covered',
            'corporate_action_risk':'UNVERIFIED for stooq; raw Alpaca bars lack corporate-action adjustment'}
