"""Causal, monotone profit-lock policy for StocksWatch EOD-owned LONG shares.

This module only calculates price levels. Broker orders are managed separately.
Stop-price *trigger* does not guarantee minimum realized profit after gaps.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_UP, InvalidOperation

D=Decimal
CENT=D(".01")


def decimal(value):
    try:
        x=D(str(value))
    except (InvalidOperation,TypeError,ValueError):
        raise ValueError("profit_lock_invalid_number") from None
    if not x.is_finite() or x<=0:
        raise ValueError("profit_lock_non_positive")
    return x


def floor_cent(value):
    return decimal(value).quantize(CENT,rounding=ROUND_DOWN)


def ceil_cent(value):
    return decimal(value).quantize(CENT,rounding=ROUND_UP)


def atr14(bars):
    """14-day true range from at least 15 chronological, trusted EOD OHLC bars."""
    if len(bars)<15:
        raise ValueError("profit_lock_atr_history_short")
    ranges=[]
    for prev,bar in zip(bars[-15:-1],bars[-14:]):
        o,h,l,c=(decimal(bar[k]) for k in ("o","h","l","c"))
        previous_close=decimal(prev["c"])
        if not l<=min(o,c)<=max(o,c)<=h:
            raise ValueError("profit_lock_invalid_ohlc")
        ranges.append(max(h-l,abs(h-previous_close),abs(l-previous_close)))
    return sum(ranges,D(0))/D(14)


@dataclass(frozen=True)
class Plan:
    entry: Decimal
    qty: Decimal
    atr: Decimal
    initial_stop: Decimal
    target: Decimal
    risk: Decimal
    rr: Decimal

    def data(self):
        return {k:str(getattr(self,k)) for k in (
            "entry","qty","atr","initial_stop","target","risk","rr")}


def initial(entry,qty,atr):
    """ATR-scaled 3%-8% initial risk; TP at 2.5× initial risk.

    This is an initial policy for paper validation, not a claimed optimal exit.
    """
    entry,qty,atr=map(decimal,(entry,qty,atr))
    risk=max(entry*D(".03"),min(entry*D(".08"),atr*D("2.5")))
    stop=floor_cent(entry-risk)
    target=ceil_cent(entry+D("2.5")*(entry-stop))
    if stop<=0 or target<=entry or target-stop<CENT*3:
        raise ValueError("profit_lock_levels_invalid")
    return Plan(entry,qty,atr,stop,target,entry-stop,(target-entry)/(entry-stop))


def next_stop(plan,previous_stop,highwater,current_bid):
    """Pure one-way ratchet, combining an ATR chandelier and MFE milestones.

    Stage thresholds are fractions of the original TP distance:
      >=40%: breakeven +0.2% of entry for possible transaction friction;
      >=60%: retain >=25% of peak profit;
      >=80%: retain >=60% of peak profit;
      >=90%: retain >=70% of peak profit.

    With $250 peak profit vs $300 TP, stage >=80% locks $150
    in *trigger-price* terms for an unchanged position quantity.
    """
    previous_stop=decimal(previous_stop)
    peak=max(decimal(highwater),plan.entry)
    bid=decimal(current_bid)
    if previous_stop<plan.initial_stop:
        raise ValueError("profit_lock_stop_decreased")
    progress=max(D(0),peak-plan.entry)/(plan.target-plan.entry)
    profit=max(D(0),peak-plan.entry)
    proposed=plan.initial_stop
    if progress>=D(".4"):
        proposed=max(proposed,plan.entry*D("1.002"))
    if progress>=D(".6"):
        proposed=max(proposed,plan.entry+profit*D(".25"))
    if progress>=D(".8"):
        proposed=max(proposed,plan.entry+profit*D(".60"))
    if progress>=D(".9"):
        proposed=max(proposed,plan.entry+profit*D(".70"))
    # Volatility-aware chandelier; never loosen existing broker protection.
    proposed=max(proposed,peak-D("2.7")*plan.atr,previous_stop)
    proposed=floor_cent(proposed)
    # Do not place/replace a stop at or above the fresh bid: avoid unintended
    # immediate execution, stop order rejection, and repeated churn.
    clearance=max(plan.atr*D(".55"),bid*D(".005"),CENT*2)
    max_below_bid=floor_cent(bid-clearance) if bid>clearance else CENT
    if proposed>max_below_bid:
        # If an older stop is already above this value, leave it unchanged;
        # broker may legitimately trigger it. Never lower protection.
        return floor_cent(previous_stop)
    return max(floor_cent(previous_stop),proposed)


def profit_dollars(plan,stop):
    return (decimal(stop)-plan.entry)*plan.qty


def feasible_oco(plan,bid):
    bid=decimal(bid)
    room=max(plan.atr*D(".55"),bid*D(".005"),CENT*2)
    # Broker OCO must have a stop strictly below market and TP above market.
    return plan.initial_stop+room<bid<plan.target-room
