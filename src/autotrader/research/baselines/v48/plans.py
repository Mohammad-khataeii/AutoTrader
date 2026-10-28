"""Structural stops and reachable targets; patient prices never imply a fill."""
from __future__ import annotations

import itertools
from decimal import Decimal
from typing import Any

from autotrader.domain import Candle, OrderBook, TradingPair, quantize_down
from autotrader.research.baselines.v48 import PARAMETERS

D = Decimal


def construct(identity: str, bars: list[Candle], pair: TradingPair, book: OrderBook,
              regime: dict[str, Any], pattern: dict[str, Any]) -> dict[str, Any]:
    ask, distance = book.best_ask, D(regime['atr'])
    if not ask or distance<=0 or not pattern.get('stop_anchor') or pair.price_step<=0:
        return {'valid': False, 'stop': '0', 'targets': [], 'alternatives': [], 'reason': 'structure_unavailable'}
    anchor = D(pattern['stop_anchor'])
    stop = quantize_down(anchor-distance*D(PARAMETERS['stop_atr_buffer']), pair.price_step)
    # Confirmed pivots use two later bars, all available before the decision.
    pivots = [bars[i].high for i in range(2,len(bars)-2)
        if bars[i].high>=max(c.high for c in bars[i-2:i+3]) and bars[i].high>ask+pair.price_step]
    overhead = min(pivots) if pivots else None
    broken = D(pattern['level']) if identity=='RAOE_BREAKOUT_RETEST' and pattern.get('level') else None
    if broken is not None:
        # The broken level is support. A completed range projection supplies
        # runway only when no closer, still-unbroken pivot obstructs it.
        measured = broken-min(c.low for c in bars[-40:-8])
        ceiling = broken+measured
        if overhead is not None: ceiling=min(ceiling,overhead)
        basis = 'completed_range_projection_capped_at_next_unbroken_pivot'
    elif overhead is not None:
        ceiling = overhead
        basis = 'nearest_confirmed_overhead_pivot'
    else:
        # No invented volatility target when structure provides no runway.
        ceiling = D(0)
        basis = 'unknown_overhead_no_plan'
    runway = ceiling-ask
    targets = tuple(quantize_down(ask+runway*f, pair.price_step) for f in (D('.65'),D('.85'),D('.98'))) if runway>0 else ()
    patient = quantize_down(min(ask, bars[-1].close-distance*D('.25')),pair.price_step)
    alternatives = [
        {'method': 'CONFIRMED_REACTION_IOC', 'entry': str(ask), 'executable_now': True,
         'reason': 'Completed reaction then fresh ask-side depth validation'},
        {'method': 'PATIENT_IOC', 'entry': str(patient), 'executable_now': ask<=patient,
         'reason': 'Requires a future fresh executable ask at or below limit; candle touch is not a fill',
         'same_structural_stop': str(stop)},
        {'method': 'NO_TRADE', 'entry': None, 'executable_now': False, 'reason': 'Always available'}]
    valid = bool(targets and 0<stop<ask and targets[0]>ask and ask-stop>=distance
        and ask-bars[-1].close<=distance*D('.5') and all(a<b for a,b in itertools.pairwise(targets)))
    return {'valid': valid, 'entry_method': 'CONFIRMED_REACTION_IOC', 'entry': str(ask),
        'stop': str(stop), 'targets': [str(t) for t in targets], 'ceiling': str(ceiling),
        'target_basis': basis, 'broken_resistance_as_support': str(broken) if broken else None,
        'next_overhead': str(overhead) if overhead else None, 'alternatives': alternatives,
        'holding_seconds': int(PARAMETERS['holding_bars'])*300,
        'reason': 'structural_plan_available' if valid else 'insufficient_runway_noise_or_chased_entry'}
