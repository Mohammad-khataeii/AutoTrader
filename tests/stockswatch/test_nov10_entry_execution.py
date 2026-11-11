"""Regression tests for causal, protected EOD price admission."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from stockswatch.entry_execution import assess, MINUTES_AFTER_OPEN

OPEN = datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc)


def bars(symbol_price, now):
    end = now.replace(second=0,microsecond=0)
    return [
        {"t":(end-timedelta(minutes=i)).isoformat(),
         "c":str(symbol_price+Decimal(i)*Decimal("0.03")),
         "l":str(symbol_price-Decimal("0.2")),
         "h":str(symbol_price+Decimal("0.2"))}
        for i in [3,2,1]
    ]


def run(now, stock, spy=None, quote=None):
    return assess(
        now=now,opening=OPEN,certified_close="100.00",
        stock_bars=stock,benchmark_bars=spy or bars(Decimal("500"),now),
        quote=quote or {"t":now.isoformat(),"bp":"99.97","ap":"100.00"},
    )


def test_opening_12_minutes_never_admitted():
    now=OPEN+timedelta(minutes=3)
    assert run(now,bars(Decimal("100"),now))["reason"]=="adaptive_observing_open"


def test_stabilized_fresh_quote_reprices_and_respects_eod_cap():
    now=OPEN+timedelta(minutes=20)
    result=run(now,bars(Decimal("100"),now))
    assert result["status"]=="READY"
    assert Decimal(result["limit_price"])<=Decimal("100.50")
    assert Decimal(result["limit_price"])>=Decimal("100")


def test_falling_stock_is_not_instantly_purchased():
    now=OPEN+timedelta(minutes=20)
    series=bars(Decimal("100"),now)
    series[0]["c"],series[1]["c"],series[2]["c"]="101","100.6","100"
    assert run(now,series)["reason"]=="adaptive_stock_still_declining"


def test_broker_quote_stale_fails_closed():
    now=OPEN+timedelta(minutes=20)
    q={"t":(now-timedelta(minutes=4)).isoformat(),"bp":"99.97","ap":"100.00"}
    assert run(now,bars(Decimal("100"),now),quote=q)["reason"]=="adaptive_quote_stale"


def test_ask_above_previous_day_cap_skips_not_chases():
    now=OPEN+timedelta(minutes=20)
    q={"t":now.isoformat(),"bp":"100.8","ap":"100.85"}
    assert run(now,bars(Decimal("100"),now),quote=q)["reason"] in (
        "adaptive_bar_quote_disagreement","adaptive_price_above_eod_cap")


def test_spy_selloff_guard_does_not_use_future_bar():
    now=OPEN+timedelta(minutes=20)
    spy=bars(Decimal("500"),now)
    spy[0]["c"],spy[1]["c"],spy[2]["c"]="503","501","500"
    assert run(now,bars(Decimal("100"),now),spy=spy)["reason"]=="adaptive_market_selling_accelerating"


def test_expired_window_no_entry():
    now=OPEN+timedelta(minutes=57)
    assert run(now,bars(Decimal("100"),now))["reason"]=="adaptive_entry_window_ended"


def test_forming_future_bars_cannot_authorize_entry():
    now=OPEN+timedelta(minutes=20)
    future=[{"t":(now+timedelta(minutes=i)).isoformat(),"c":"100","l":"99","h":"101"} for i in range(1,5)]
    assert run(now,future)["status"]=="WAIT"
