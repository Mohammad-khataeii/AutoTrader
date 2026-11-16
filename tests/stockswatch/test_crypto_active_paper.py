from datetime import datetime,timedelta,timezone
from stockswatch.crypto_active_paper import assess, benchmark_ok


def bars():
    t=datetime(2026,11,1,tzinfo=timezone.utc)
    result=[]
    for i in range(24):
        price=100+i*.1
        result.append({'ts':(t+timedelta(hours=i)).isoformat(),
                       'o':price-.03,'h':price+.1,'l':price-.1,'c':price,'v':10})
    return result


def test_valid_signal_and_btc():
    b=bars()
    r=assess(b,102.2,101.5,.25,58)
    assert r['passed'],r
    assert r['stop']<b[-1]['c']<r['target']
    assert benchmark_ok(b[-4:],b[-1]['ts'])


def test_reject_untraded_or_discontinuous_candles():
    b=bars()
    b[-1]['v']=0
    assert not assess(b,102.2,101.5,.25,58)['passed']
    b=bars()
    b[-2]['ts']=b[-3]['ts']
    assert not assess(b,102.2,101.5,.25,58)['passed']


def test_reject_falling_and_extended():
    b=bars()
    b[-1]['c']=b[-2]['c']-.3
    assert not assess(b,101.5,101.6,.25,48)['passed']
    assert not assess(bars(),101,100,.25,58)['passed']


def test_benchmark_requires_recent_traded_stability():
    b=bars()
    b[-1]['c']=b[0]['c']*.90
    assert not benchmark_ok(b[-4:],b[-1]['ts'])
    b=bars()
    b[-1]['v']=0
    assert not benchmark_ok(b[-4:],b[-1]['ts'])
