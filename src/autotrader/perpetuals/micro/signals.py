"""Causal deterministic hypotheses. Thresholds are research inputs, not learned edge. Untested and unvalidated."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from autotrader.perpetuals.market import MINUTE, Bar
from autotrader.perpetuals.micro.types import Candle, Candidate, Features, POLICIES, Regime, Side

D = Decimal
LOOKBACK = 90


def grouped(rows: tuple[Candle, ...], minutes: int, cutoff: int) -> tuple[Candle, ...]:
    """UTC aligned groups only; the first/last partial group cannot enter features."""
    by_start = {row.start: row for row in rows}
    period = minutes * MINUTE
    first = ((rows[0].start + period - 1) // period) * period
    output = []
    for start in range(first, cutoff - period + 1, period):
        group = [by_start[t] for t in range(start, start + period, MINUTE)]
        volumes = [row.volume for row in group]
        output.append(Candle(start, minutes, group[0].open, max(row.high for row in group),
                             min(row.low for row in group), group[-1].close,
                             sum((v for v in volumes if v is not None), D(0))
                             if all(v is not None for v in volumes) else None))
    return tuple(output)


def features(bars: dict[int, Bar], cutoff: int, known_at: int) -> Features:
    if cutoff % MINUTE or not cutoff <= known_at <= cutoff + 90_000:
        raise ValueError('stale_or_future_micro_features')
    source = [bars.get(t) for t in range(cutoff - LOOKBACK * MINUTE, cutoff, MINUTE)]
    if any(row is None for row in source):
        raise ValueError('incomplete_micro_feature_window')
    one = tuple(Candle(row.start, 1, row.open, row.high, row.low, row.close, row.volume)
                for row in source if row is not None)
    for row in one:
        values = (row.open, row.high, row.low, row.close)
        if (any(not value.is_finite() or value <= 0 for value in values)
                or not row.low <= min(row.open, row.close) <= max(row.open, row.close) <= row.high
                or row.volume is not None and (not row.volume.is_finite() or row.volume < 0)):
            raise ValueError('invalid_micro_candle')
    three, five = grouped(one, 3, cutoff), grouped(one, 5, cutoff)
    close = one[-1].close
    changes = [one[i].close - one[i - 1].close for i in range(len(one) - 12, len(one))]
    path = sum((abs(v) for v in changes), D(0))
    efficiency = abs(sum(changes, D(0))) / path if path else D(0)
    sign = 1 if sum(changes, D(0)) > 0 else -1
    persistence = D(sum(sign * value > 0 for value in changes)) / len(changes)
    tr = [max(one[i].high - one[i].low, abs(one[i].high - one[i - 1].close),
              abs(one[i].low - one[i - 1].close)) for i in range(1, len(one))]
    atr = sum(tr[-14:], D(0)) / 14 / close
    old = sum(tr[-28:-14], D(0)) / 14
    expansion = (sum(tr[-5:], D(0)) / 5 / old) if old else D(0)
    m1, m3, m5 = (close / one[-1 - n].close - 1 for n in (1, 3, 5))
    acceleration = m3 - (one[-4].close / one[-7].close - 1)
    regime: Regime = ('DISORDERED' if atr == 0 or expansion > D('2.5') else
              ('TREND_UP' if sign == 1 else 'TREND_DOWN')
              if efficiency >= D('.45') and persistence >= D('.58') else
              'RANGE' if efficiency <= D('.25') else 'DISORDERED')
    volumes = [row.volume for row in one[-21:]]
    baseline = sum((v for v in volumes[:-1] if v is not None), D(0)) / 20
    ratio = volumes[-1] / baseline if all(v is not None for v in volumes) and baseline > 0 else None
    encoded = json.dumps([[r.start, str(r.open), str(r.high), str(r.low), str(r.close),
                           str(r.volume) if r.volume is not None else None] for r in one], separators=(',', ':'))
    return Features(cutoff, known_at, close, atr, efficiency, m1, m3, m5, acceleration,
                    persistence, expansion, ratio, regime, one, three, five,
                    hashlib.sha256(encoded.encode()).hexdigest())


def candidates(f: Features) -> tuple[Candidate, ...]:
    one, price, atr = f.one, f.reference, f.atr_fraction
    side: Side = 1 if f.momentum_5m >= 0 else -1
    trend = f.regime == ('TREND_UP' if side == 1 else 'TREND_DOWN')
    # Completed 3m and 5m direction confirmation, not resampled partial bars.
    aligned = all(side * (frame[-1].close - frame[-2].close) > 0 for frame in (f.three, f.five))
    span = (max(r.high for r in one[-12:]) - min(r.low for r in one[-12:])) / price
    extension = abs(price / (sum((r.close for r in one[-8:]), D(0)) / 8) - 1)
    body = abs(one[-1].close - one[-1].open) / max(one[-1].high - one[-1].low, D('1e-12'))
    pullback = any(side * (r.close - r.open) < 0 for r in one[-4:-1])
    reasons = []
    if not trend or not aligned: reasons.append('trend_or_multiframe_confirmation_missing')
    if side * f.acceleration <= 0: reasons.append('momentum_not_accelerating')
    if not pullback: reasons.append('controlled_micro_pullback_missing')
    if extension > 2 * atr or body < D('.5'): reasons.append('move_extended_or_weak_close')
    if not D('.8') <= f.expansion <= D('1.8'): reasons.append('compression_expansion_not_controlled')
    if f.volume_ratio is None: reasons.append('relative_volume_unknown')
    elif f.volume_ratio < 1: reasons.append('relative_volume_not_confirmed')
    continuation = Candidate(POLICIES[0], side, f.cutoff, f.known_at, price,
        min(span * D('.8'), 4 * atr), max(atr * D('1.8'), extension / 2), 12, None,
        ('completed_1m_3m_5m_continuation_hypothesis',), tuple(reasons))

    # The break must be in a previous completed candle. The following two
    # completed bars must retest and reclaim; touching a level is never a fill.
    history, breakout, retest, confirm = one[-16:-3], one[-3], one[-2], one[-1]
    upper, lower = max(r.high for r in history), min(r.low for r in history)
    breakout_side: Side = 1 if breakout.close > upper else -1
    level = upper if breakout_side == 1 else lower
    broke = breakout.close > upper if breakout_side == 1 else breakout.close < lower
    tolerance = price * atr / 2
    touched = retest.low <= level + tolerance and retest.high >= level - tolerance
    reclaimed = (breakout_side * (confirm.close - level) > 0
                 and breakout_side * (confirm.close - confirm.open) > 0
                 and breakout_side * (retest.close - level) >= -tolerance)
    reasons = []
    if not broke or not touched or not reclaimed: reasons.append('confirmed_break_retest_reclaim_missing')
    if not trend or breakout_side != side: reasons.append('retest_regime_mismatch')
    if abs(price / level - 1) > 2 * atr: reasons.append('retest_entry_already_extended')
    if f.volume_ratio is None or f.volume_ratio < D('.8'): reasons.append('retest_volume_unconfirmed')
    retest_candidate = Candidate(POLICIES[1], breakout_side, f.cutoff, f.known_at, price,
        min((upper - lower) / price, 5 * atr), max(atr * D('1.5'), abs(price / level - 1) + atr / 2),
        15, level, ('completed_break_then_retest_then_reclaim_hypothesis',), tuple(reasons))

    window = one[-31:-1]
    upper, lower = max(r.high for r in window), min(r.low for r in window)
    width, midpoint = upper - lower, (upper + lower) / 2
    range_side: Side = 1 if price <= midpoint else -1
    range_target = range_side * (midpoint / price - 1)
    edge_distance = (price - lower if range_side == 1 else upper - price) / max(width, D('1e-12'))
    rejected_edge = (one[-1].low < one[-2].low and one[-1].close > one[-1].open if range_side == 1
                     else one[-1].high > one[-2].high and one[-1].close < one[-1].open)
    edge_hits = sum(r.low <= lower + width * D('.15') for r in window)
    edge_hits_other = sum(r.high >= upper - width * D('.15') for r in window)
    reasons = []
    if f.regime != 'RANGE': reasons.append('range_regime_required')
    if not 0 <= edge_distance <= D('.2') or min(edge_hits, edge_hits_other) < 2:
        reasons.append('supported_range_extreme_missing')
    if not rejected_edge: reasons.append('range_rejection_unconfirmed')
    if f.expansion > D('1.2'): reasons.append('range_breakout_risk')
    range_candidate = Candidate(POLICIES[2], range_side, f.cutoff, f.known_at, price,
        range_target, max(atr * D('1.5'), range_side * (price - (lower if range_side == 1 else upper)) / price + atr / 2),
        10, lower if range_side == 1 else upper, ('supported_range_edge_to_midpoint_hypothesis',), tuple(reasons))
    return continuation, retest_candidate, range_candidate
