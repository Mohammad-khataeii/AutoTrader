"""Three distinct structural hypotheses. Thresholds are frozen, not fitted."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from autotrader.domain import Candle
from autotrader.indicators import _ema

D = Decimal


def setup(identity: str, bars: list[Candle], regime: dict[str, Any]) -> dict[str, Any]:
    if len(bars)<60 or not regime['ready']:
        return {'confirmed': False, 'reason': 'missing_completed_data', 'stop_anchor': None}
    a = D(regime['atr'])
    last, prior = bars[-1], bars[-2]
    e9 = _ema([c.close for c in bars[-60:]],9)
    assert e9 is not None
    exhausted = a<=0 or last.close-e9>2*a or last.high-last.low>3*a or (last.high-last.close>last.close-last.low)
    common = not exhausted and regime['benchmark'] in {'SUPPORTIVE','MIXED'}
    if identity=='RAOE_EARLY_RECOVERY':
        # Deliberately independent of hourly EMA direction. Two higher closes,
        # rising lows and recovery of the short mean reject a single spike.
        confirmed = common and regime['impulse'] and last.close>e9 and last.close>max(c.high for c in bars[-6:-2])
        anchor = min(c.low for c in bars[-6:])
        reason = 'two_completed_recovery_closes_and_local_break' if confirmed else 'recovery_unconfirmed_or_exhausted'
        level = None
    elif identity=='RAOE_TREND_PULLBACK':
        high = max(c.high for c in bars[-20:-4])
        reaction = last.close>prior.high and last.low>=min(c.low for c in bars[-4:-1])
        pulled = high-min(c.low for c in bars[-4:]) >= a
        confirmed = common and regime['timeframes']['15']['trend']=='BULLISH' and pulled and reaction and last.close<high
        anchor = min(c.low for c in bars[-5:])
        level = high
        reason = 'controlled_pullback_recovery_below_prior_high' if confirmed else 'pullback_reaction_not_confirmed'
    elif identity=='RAOE_BREAKOUT_RETEST':
        confirmed, anchor, level = False, min(c.low for c in bars[-5:]), None
        # A breakout close must precede a holding close and a later retest.
        # Reconstructing from completed bars makes restart state deterministic.
        for index in range(len(bars)-8, len(bars)-2):
            window = bars[index-20:index]
            resistance = max(c.high for c in window)
            bottom = min(c.low for c in window)
            if (resistance-bottom <= 8*a and bars[index].close>resistance+D('.1')*a
                    and all(c.close>=resistance for c in bars[index+1:-1])
                    and last.low<=resistance+D('.5')*a and last.close>=resistance
                    and last.close>last.open):
                confirmed = common
                level, anchor = resistance, min(resistance, min(c.low for c in bars[index+1:]))
                break
        reason = 'completed_breakout_hold_and_later_retest' if confirmed else 'breakout_hold_retest_not_confirmed'
    else:
        raise ValueError('unknown_raoe_strategy')
    return {'confirmed': bool(confirmed), 'reason': reason, 'stop_anchor': str(anchor),
        'level': str(level) if level is not None else None, 'exhausted': bool(exhausted),
        'event_id': f'{identity}:{bars[-1].symbol}:{bars[-1].timestamp.isoformat()}',
        'participation': 'price_structure_and_current_depth_only; traded_volume_unverified'}
