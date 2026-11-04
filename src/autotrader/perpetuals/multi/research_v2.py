"""Opt-in V2 hypotheses: independent long/short observations, no account authority.

V1's signal generator, policy hash and financial rules are preserved. These thresholds
are engineering hypotheses requiring prospective comparison, not fitted edge.
"""
from __future__ import annotations

from pathlib import Path

from autotrader.perpetuals.micro.signals import features, grouped
from autotrader.perpetuals.multi.policy import D, digest
from autotrader.perpetuals.multi.strategies import Signal

EXPERIMENT = 'MULTI_USDT_MICRO_RESEARCH_V2'
POLICIES = ('MULTI_CONTINUATION_V2', 'MULTI_COMPRESSION_RETEST_V2',
            'MULTI_RANGE_V2', 'MULTI_FAILED_BREAK_REVERSAL_V2')
TERMS = {'experiment': EXPERIMENT, 'policies': POLICIES, 'version': '4.9.9-research.1',
         'execution': 'NONE_OBSERVATIONS_ONLY', 'directions': [-1, 1],
         'noise_floor_atr': '1.8', 'maximum_extension_atr': '1.5',
         'minimum_remaining_room': '.005', 'maximum_target': '.01',
         'target_buffer_atr': '.5', 'minimum_volume_ratio': '1',
         'range_distinct_touch_gap_minutes': 3, 'minimum_net_scenario_risk': '1.1',
         'success_probability': None, 'feature_schema': 'perp-micro-features/1'}
POLICY_HASH = digest({'terms': TERMS, 'source': Path(__file__).read_text(),
                     'dependencies': {name: (Path(__file__).parents[1]/name).read_text()
                                      for name in ('micro/signals.py', 'micro/execution.py', 'multi/policy.py',
                                                   'multi/contracts.py', 'multi/scanner.py', 'multi/research.py',
                                                   'multi/economics.py', 'multi/evidence.py')}})


def generate_v2(symbol, bars, cutoff, now):
    f = features(bars, cutoff, now)
    one, price, atr = f.one, f.reference, f.atr_fraction
    hourly_context = grouped(one, 15, cutoff)
    output = []
    for side in (1, -1):
        trend = 'TREND_UP' if side == 1 else 'TREND_DOWN'
        aligned = all(side*(frame[-1].close-frame[-2].close) > 0 for frame in (f.three, f.five, hourly_context))
        anchor = sum((b.close for b in one[-9:-1]), D(0))/8
        extension = side*(price/anchor-1)
        # The most recent completed local high/low is a ceiling, not a target
        # projection of the entire range after the price has already traversed it.
        ceiling = max(b.high for b in one[-60:-3]) if side == 1 else min(b.low for b in one[-60:-3])
        room = side*(ceiling/price-1)-atr*D('.5')

        def add(index, reasons, target_room, stop_price, hold, **extra):
            stop_distance = side*(price-stop_price)/price
            if target_room < D('.005'): reasons.append('insufficient_remaining_structural_room')
            if not atr*D('1.8') <= stop_distance <= D('.01'): reasons.append('stop_inside_noise_or_excessive')
            if f.volume_ratio is None or f.volume_ratio < 1: reasons.append('completed_volume_unconfirmed')
            distance = min(max(target_room, D(0)), D('.01'))
            policy = POLICIES[index]
            output.append(Signal(digest([EXPERIMENT, POLICY_HASH, symbol, policy, side, cutoff]),
                symbol, policy, side, cutoff, now, price, stop_price, price*(1+side*distance),
                hold, f.regime, f.source_hash,
                {'experiment': EXPERIMENT, 'policy_hash': POLICY_HASH, 'research_only': True,
                 'qualification': 'UNVALIDATED_V2_RESEARCH', 'probability': None,
                 'expected_net_pnl_usdt': None, 'atr_fraction': atr, 'relative_volume': f.volume_ratio,
                 'extension_atr': extension/atr if atr else None, 'efficiency': f.efficiency,
                 'persistence': f.persistence, 'expansion': f.expansion,
                 'forecast_signed_move_fraction': distance, 'remaining_room_fraction': target_room,
                 'context_15m_closed_at': hourly_context[-1].start+15*60_000,
                 'source': 'COMPLETED_LAST_TRADE_CANDLES', **extra}, tuple(dict.fromkeys(reasons))))

        recent = one[-4:-1]
        pullback_extreme = min(b.low for b in recent) if side == 1 else max(b.high for b in recent)
        reclaim = max(b.high for b in one[-3:-1]) if side == 1 else min(b.low for b in one[-3:-1])
        reasons = []
        if f.regime != trend or not aligned: reasons.append('completed_multiframe_trend_mismatch')
        if not any(side*(b.close-b.open) < 0 for b in recent): reasons.append('controlled_pullback_missing')
        if side*(price-reclaim) <= 0: reasons.append('pullback_reclaim_missing')
        if side*f.acceleration <= 0 or side*f.momentum_3m <= 0: reasons.append('continuation_follow_through_missing')
        if extension > atr*D('1.5'): reasons.append('late_continuation_extended')
        if not D('.6') <= f.expansion <= D('1.8'): reasons.append('unstable_expansion')
        stop = min(pullback_extreme-price*atr/2, price*(1-atr*D('1.8'))) if side == 1 else max(pullback_extreme+price*atr/2, price*(1+atr*D('1.8')))
        add(0, reasons, room, stop, 15, structure=reclaim)

        box = one[-19:-3]; upper = max(b.high for b in box); lower = min(b.low for b in box)
        level = upper if side == 1 else lower
        breakout, retest, confirm = one[-3:]
        broad = max(b.high for b in one[-60:-3])-min(b.low for b in one[-60:-3])
        reasons = []
        if side*(breakout.close-level) <= 0: reasons.append('prior_completed_breakout_missing')
        if not retest.low <= level+price*atr/2 or not retest.high >= level-price*atr/2: reasons.append('retest_missing')
        if side*(retest.close-level) < -price*atr/2 or side*(confirm.close-retest.close) <= 0 or side*(confirm.close-level) <= 0:
            reasons.append('retest_hold_and_reclaim_missing')
        if broad <= 0 or (upper-lower) > broad*D('.5'): reasons.append('compression_not_established')
        if f.regime != trend or not aligned: reasons.append('breakout_context_mismatch')
        if abs(price/level-1) > atr*D('1.5') or f.expansion > 2: reasons.append('late_or_exhausted_breakout')
        retest_stop = min(retest.low, level)-price*atr/2 if side == 1 else max(retest.high, level)+price*atr/2
        add(1, reasons, min(room, (upper-lower)/price), retest_stop, 20, structure=level)

        window = one[-41:-1]; upper = max(b.high for b in window); lower = min(b.low for b in window)
        width, midpoint = upper-lower, (upper+lower)/2
        edge = (price-lower if side == 1 else upper-price)/max(width, D('1e-12'))
        # Adjacent candles at the same extreme count as one visit.
        def visits(is_lower):
            hits = [b.start for b in window if (b.low <= lower+width*D('.12') if is_lower else b.high >= upper-width*D('.12'))]
            distinct = []
            for stamp in hits:
                if not distinct or stamp-distinct[-1] >= 3*60_000: distinct.append(stamp)
            return len(distinct)
        reasons = []
        if f.regime != 'RANGE' or f.expansion > D('1.2'): reasons.append('stable_range_required')
        if not 0 <= edge <= D('.2') or min(visits(True), visits(False)) < 2: reasons.append('independent_range_edge_visits_missing')
        last = one[-1]
        wick = (min(last.open, last.close)-last.low) if side == 1 else (last.high-max(last.open, last.close))
        if side*(last.close-last.open) <= 0 or wick < abs(last.close-last.open)/2: reasons.append('range_rejection_wick_missing')
        if side*f.acceleration <= 0: reasons.append('range_recovery_decelerating')
        range_stop = lower-price*atr*D('1.8') if side == 1 else upper+price*atr*D('1.8')
        add(2, reasons, side*(midpoint/price-1)-atr/2, range_stop, 12, structure=lower if side == 1 else upper)

        box = one[-25:-4]; upper = max(b.high for b in box); lower = min(b.low for b in box)
        excursion = one[-3]; level = lower if side == 1 else upper
        failed = excursion.low < lower if side == 1 else excursion.high > upper
        reasons = []
        if not failed or not all(side*(b.close-level) > 0 for b in one[-2:]): reasons.append('two_closed_reclaims_missing')
        if side*(one[-1].close-one[-2].close) <= 0 or side*f.acceleration <= 0: reasons.append('reversal_follow_through_missing')
        if f.regime == ('TREND_DOWN' if side == 1 else 'TREND_UP') or f.efficiency > D('.65') or f.expansion > 2:
            reasons.append('countertrend_or_disordered_reversal')
        if abs(price/level-1) > atr*D('1.5'): reasons.append('late_reversal_extended')
        reversal_stop = excursion.low-price*atr*D('1.8') if side == 1 else excursion.high+price*atr*D('1.8')
        add(3, reasons, side*(((upper+lower)/2)/price-1)-atr/2, reversal_stop, 10, structure=level)
    return output
