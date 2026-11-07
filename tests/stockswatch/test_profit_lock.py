"""Profit targets and upward-only stop ratchet — deterministic scenario tests."""
from decimal import Decimal as D

import pytest

from stockswatch.profit_lock import initial,next_stop,profit_dollars,feasible_oco,atr14


def test_volatility_scaled_entry_stop_and_fixed_reward_multiple():
    p=initial("100","100","2")
    assert p.initial_stop == D("95.00")
    assert p.risk==D("5.00")
    assert p.target==D("112.50")
    assert p.rr==D("2.5")
    assert feasible_oco(p,D("100"))


def test_initial_risk_is_bounded_between_three_and_eight_percent():
    assert initial("100",1,"0.2").initial_stop==D("97.00")
    assert initial("100",1,"12").initial_stop==D("92.00")


def test_stock_gain_250_target_300_locks_at_least_150_dollars():
    # 40 shares at $100 with 3% initial risk -> $300 planned TP.
    p=initial("100","40","0.48")
    assert (p.target-p.entry)*p.qty==D("300.00")
    bid=p.entry+D("250")/p.qty
    new=next_stop(p,p.initial_stop,bid,bid)
    assert profit_dollars(p,new)>=D("150")
    assert new<bid
    assert next_stop(p,new,bid-D("1"),bid-D("1"))==new


def test_stop_unchanged_if_quote_too_close_to_move_it_safely():
    p=initial("100","10","2")
    previous=D("103.00")
    # Drop toward an existing stop must never lower the stop.
    assert next_stop(p,previous,"110","103.20")==previous


def test_trailing_stop_monotonic_when_market_falls():
    p=initial("100","100","2")
    stop=p.initial_stop
    for h,b in [(100,100),(103,102),(108,107),(110,109),(107,106),
                (105,104),(108,107)]:
        latest=next_stop(p,stop,str(h),str(b))
        assert latest>=stop
        stop=latest


def test_invalid_levels_rejected_and_no_negative_stop():
    with pytest.raises(ValueError):
        initial("0",1,2)
    with pytest.raises(ValueError):
        initial("0.01",1,2)


def test_atr14_uses_prev_close_for_gap_risk():
    bars=[{"o":100,"h":102,"l":99,"c":101}]
    bars += [{"o":110,"h":112,"l":109,"c":111} for _ in range(14)]
    assert atr14(bars)>D("3")


def test_broker_oco_requires_current_bid_between_stop_and_target():
    p=initial("100",1,"2")
    assert feasible_oco(p,"100")
    assert not feasible_oco(p,"90")
    assert not feasible_oco(p,"120")
