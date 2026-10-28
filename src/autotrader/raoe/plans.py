"""Meaningful structure supplies scenarios; economics never manufactures levels."""
from __future__ import annotations

import itertools
from datetime import datetime
from decimal import Decimal
from typing import Any

from autotrader.domain import Candle, OrderBook, TradingPair, quantize_down
from autotrader.raoe import PARAMETERS
from autotrader.raoe.structure import classify

D=Decimal


def construct(identity: str, bars: list[Candle], pair: TradingPair, book: OrderBook,
              regime: dict[str,Any], pattern: dict[str,Any], *, structural_assessment: dict[str,Any] | None = None) -> dict[str,Any]:
    ask,distance=book.best_ask,D(regime['atr'])
    if not ask or distance<=0 or not pattern.get('stop_anchor') or pair.price_step<=0:
        return {'valid':False,'stop':'0','targets':[],'alternatives':[],'reason':'structure_unavailable'}
    stop=quantize_down(D(pattern['stop_anchor'])-distance*D(PARAMETERS['stop_atr_buffer']),pair.price_step)
    structure=structural_assessment if structural_assessment is not None else classify(bars,datetime.fromisoformat(regime['as_of']),ask)
    overhead=D(structure['overhead'][0]['price']) if structure['overhead'] else None
    measured=None;level=None
    if identity.startswith('RAOE_BREAKOUT') and pattern.get('range_high') and pattern.get('range_low'):
        level=D(pattern['range_high']);height=level-D(pattern['range_low'])
        if height>0:measured=[level+height*f for f in (D('.5'),D('.75'),D(1))]
    elif structure['price_discovery']:
        level=D(structure['completed_range']['high']);height=level-D(structure['completed_range']['low'])
        measured=[level+height*f for f in (D('.5'),D('.75'),D(1))]
    if measured and (overhead is None or measured[-1]<overhead):
        raw=measured;ceiling=measured[-1];basis='bounded_completed_range_projection'
    elif overhead is not None:
        ceiling=overhead;raw=[ceiling-distance*f for f in (D('.75'),D('.4'),D('.1'))]
        basis='approach_to_nearest_meaningful_unbroken_zone'
    else:
        ceiling=D(0);raw=[];basis='missing_supported_profit_scenario'
    targets=[quantize_down(t,pair.price_step) for t in raw]
    patient=quantize_down(min(ask,bars[-1].close-distance*D('.25')),pair.price_step)
    valid=bool(len(targets)==3 and 0<stop<ask and targets[0]>ask and ask-stop>=distance
               and ask-bars[-1].close<=distance*D('.5')
               and all(a<b for a,b in itertools.pairwise(targets)) and not structure['pending_breaks'])
    reason=('structural_plan_available' if valid else 'meaningful_resistance_break_not_confirmed' if structure['pending_breaks']
            else 'missing_supported_profit_scenario' if not targets else 'insufficient_runway_noise_or_chased_entry')
    return {'valid':valid,'entry_method':'CONFIRMED_CONTINUATION_IOC' if identity=='RAOE_BREAKOUT_CONTINUATION' else 'CONFIRMED_REACTION_IOC',
        'entry':str(ask),'stop':str(stop),'targets':[str(t) for t in targets],'ceiling':str(ceiling),
        'target_basis':basis,'structure':structure,'next_overhead':str(overhead) if overhead else None,
        'broken_resistance_as_support':pattern.get('level'),'range_projection_origin':str(level) if level else None,
        'holding_seconds':int(pattern.get('holding_bars',PARAMETERS['holding_bars']))*300,
        'exit_version':'4.9.0-continuation-exit.1' if identity=='RAOE_BREAKOUT_CONTINUATION' else '4.9.0-structure-exit.1',
        'alternatives':[{'method':'CONFIRMED_REACTION_IOC','entry':str(ask),'executable_now':True},
            {'method':'PATIENT_IOC','entry':str(patient),'executable_now':ask<=patient,'same_structural_stop':str(stop),
             'reason':'A future fresh executable ask is required; a candle touch is not a fill'},
            {'method':'NO_TRADE','entry':None,'executable_now':False}], 'reason':reason}
