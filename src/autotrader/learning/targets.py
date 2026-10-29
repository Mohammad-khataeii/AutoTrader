"""Costed forward path labels; a candle touch never proves an executable fill."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from autotrader.learning import TARGET_SCHEMA
from autotrader.learning.features import finite, stamp
from autotrader.research.data import canonical, digest


def label(event: dict[str, Any], candles: list[dict[str, Any]], horizon: int,
          *, cost_stress: float = 1.) -> dict[str, Any]:
    start = stamp(event['observed_at'])
    end = start+timedelta(minutes=horizon)
    # Exclude the partial entry candle; report that unavoidable blind interval.
    first = (int(start.timestamp())//300+1)*300
    rows: dict[int, dict[str, Any]] = {}
    for c in candles:
        t = int(stamp(c['timestamp']).timestamp())
        if t < first or t+300 > end.timestamp():
            continue
        if c['symbol'] != event['symbol'] or not c['source'].startswith('revolut-x'):
            raise ValueError('invalid_target_source')
        row = {k: c[k] for k in ('timestamp', 'open', 'high', 'low', 'close', 'symbol', 'source')}
        if t in rows and row != rows[t]:
            raise ValueError('conflicting_target_versions')
        rows[t] = row
    expected = list(range(first, int(end.timestamp())//300*300, 300))
    if not expected or sorted(rows) != expected:
        raise ValueError('incomplete_future_window')
    e = event['evidence'];m = e['economics']['measurements'];plan = e['entry_plan']
    entry = finite(m['entry']['vwap']);stop = finite(plan['stop'])
    targets = [finite(t) for t in plan['targets']]
    fee = finite(m['assumptions']['exit_fee_bps'])/10000*cost_stress
    slip = finite(m['assumptions']['slippage_bps'])/10000*cost_stress
    half_spread = finite(m['entry']['spread_bps'])/20000*cost_stress
    impact = finite(m.get('exit_now', {}).get('depth_impact_bps', 0))/10000*cost_stress
    unit_cost = finite(m['cost_basis_eur'])/finite(m['fillable_quantity'])
    # Extra entry-cost stress is added once; existing entry VWAP already includes costs.
    unit_cost += entry*(cost_stress-1)*(fee+slip)/cost_stress
    remaining, proceeds, max_high, min_low, next_target = 1., 0., entry, entry, 0
    ambiguity = False;exit_reason = 'HORIZON';exit_at = end.isoformat()
    for t in expected:
        c = rows[t];o, h, l, close = [finite(c[k]) for k in ('open', 'high', 'low', 'close')]
        if not 0 < l <= min(o, close) <= max(o, close) <= h:
            raise ValueError('invalid_future_bar')
        bid_open, bid_low, bid_high = [p*(1-half_spread) for p in (o, l, h)]
        max_high, min_low = max(max_high, bid_high), min(min_low, bid_low)
        if bid_low <= stop:
            ambiguity = ambiguity or (next_target < len(targets) and bid_high >= targets[next_target])
            proceeds += remaining*min(stop, bid_open)*(1-fee)*(1-slip)*(1-impact)
            remaining = 0.;exit_reason = 'STOP_FIRST_CONSERVATIVE';exit_at = c['timestamp'];break
        while next_target < len(targets) and bid_high >= targets[next_target]:
            fraction = min(remaining, (.3, .4, .3)[next_target])
            proceeds += fraction*targets[next_target]*(1-fee)*(1-slip)*(1-impact)
            remaining -= fraction;next_target += 1
        if remaining < 1e-9:
            remaining = 0.;exit_reason = 'TARGETS';exit_at = c['timestamp'];break
    if remaining:
        proceeds += remaining*finite(rows[expected[-1]]['close'])*(1-half_spread)*(1-fee)*(1-slip)*(1-impact)
    later = [rows[t] for t in expected if t > stamp(exit_at).timestamp()] if exit_reason == 'STOP_FIRST_CONSERVATIVE' else []
    feedback = {'later_completed_bars': len(later),
        'mid_recovered_entry_after_stop': any(finite(c['high']) >= entry for c in later),
        'mid_continued_below_stop': any(finite(c['low']) < stop for c in later),
        'scope': 'Within original horizon; bar-level path observation, no alternative fill proof'}
    net = proceeds/unit_cost-1
    risk = max((unit_cost-stop*(1-fee)*(1-slip)*(1-impact))/unit_cost, .000001)
    return {'schema': TARGET_SCHEMA, 'horizon_minutes': horizon, 'end_at': end.isoformat(),
            'net_return': net, 'net_r': net/risk, 'positive': int(net > 0),
            'exit_reason': exit_reason, 'exit_at': exit_at, 'ambiguous': ambiguity,
            'mfe': max_high/entry-1, 'mae': min_low/entry-1,
            'path_hash': digest(canonical([rows[t] for t in expected])),
            'cost_stress': cost_stress, 'exit_feedback': feedback, 'executable_outcome_proven': False,
            'evidence_category': 'RECORDED_PRICE_PATH_MODELED_EXECUTION',
            'limitations': ['No future depth; constant entry spread/impact assumption',
                           'Partial first/last candles excluded',
                           'Fixed targets/stop; no claimed replay of adaptive production exit policy']}
