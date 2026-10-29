"""Reproduce trade-level financial and price-path evidence from read-only exports."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from autotrader.domain import Candle
from autotrader.learning.features import stamp
from autotrader.raoe.regime import assess
from autotrader.research.data import canonical, digest

D = Decimal


def analysis(source: Path, candles_path: Path) -> dict:
    core = defaultdict(lambda: defaultdict(list));header = None;completed = set();last = None
    with gzip.open(source, 'rt') as f:
        for line in f:
            r = json.loads(line, parse_float=str);last = r
            if r.get('type') == 'header': header = r
            if r.get('type') == 'database_complete': completed.add(r['database'])
            if r.get('section'): core[r['database']][r['section']].append(r['row'])
    if last != {'type': 'complete', 'status': 'PASS'} or len(completed) != 17 or not header:
        raise ValueError('complete_seventeen_database_export_required')
    bars = defaultdict(dict);conflicts = []
    with gzip.open(candles_path, 'rt') as f:
        for line in f:
            r = json.loads(line, parse_float=str);c = Candle(r['symbol'], stamp(r['timestamp']),
                *[D(r[k]) for k in ('open', 'high', 'low', 'close', 'volume')], timeframe='5m', source=r['source'])
            old = bars[c.symbol].get(c.timestamp)
            if old and old != c: conflicts.append({'symbol': c.symbol, 'timestamp': c.timestamp.isoformat()})
            bars[c.symbol][c.timestamp] = c
    histories = {k: sorted(v.values(), key=lambda c: c.timestamp) for k, v in bars.items()}
    primary_name = header['registry']['primary']['database_name'];primary = core[primary_name]
    trades = []
    for position in primary['positions']:
        if not position['closed_at']: continue
        pid = position['position_id']
        orders = [o for o in primary['orders'] if o['position_id'] == pid]
        fills = [f for f in primary['fills'] if f['position_id'] == pid]
        entry = next(o for o in orders if o['side'] == 'BUY' and D(o['filled_quantity']) > 0)
        payload = entry['execution_json'];payload = json.loads(payload) if isinstance(payload, str) else payload
        evidence = payload['strategy_evidence'];opened, closed = stamp(position['opened_at']), stamp(position['closed_at'])
        quantity = sum((D(f['quantity']) for f in fills if f['side']=='BUY'), D(0))
        fees = sum((D(f['fee']) for f in fills), D(0));net = D(position['realized_pnl'])
        journal = [j for j in primary['financial_journal'] if j.get('position_id') == pid]
        linked_cash = sum((D(j['cash_delta']) for j in journal), D(0))
        if linked_cash != net: raise ValueError('linked_position_journal_mismatch')
        exit_order = next(o for o in reversed(orders) if o['side'] == 'SELL' and D(o['filled_quantity'])>0)
        sell_payload = exit_order['execution_json'];sell_payload = json.loads(sell_payload) if isinstance(sell_payload, str) else sell_payload
        reasons = [i['reason'] for i in primary['exit_intents'] if i['position_id']==pid]
        reg = evidence.get('raoe_regime') or evidence.get('regime_assessment')
        future = []
        for horizon in (15, 30, 60, 120, 240):
            when = closed+timedelta(minutes=horizon)
            available = [c for c in histories.get(position['symbol'], []) if c.timestamp+timedelta(minutes=5)<=when]
            last_bar = available[-1] if available else None
            fresh = bool(last_bar and timedelta(0)<=when-last_bar.timestamp-timedelta(minutes=5)<timedelta(minutes=5))
            future.append({'minutes_after_exit': horizon, 'status': 'OBSERVED_COMPLETED_MID_CLOSE' if fresh else 'MISSING_DATA',
                'completed_at': (last_bar.timestamp+timedelta(minutes=5)).isoformat() if fresh else None,
                'mid_close': str(last_bar.close) if fresh else None,
                'return_from_actual_exit': str(last_bar.close/D(exit_order['average_fill_price'])-1) if fresh else None,
                'executable_reentry_or_hold_return': False})
        original_bars = [c for c in histories.get(position['symbol'], []) if c.timestamp+timedelta(minutes=5) <= opened][-1152:]
        candidate_hash = digest(canonical([[c.timestamp.isoformat(), *[format(v.normalize(), 'f') for v in (c.close, c.high, c.low)]] for c in original_bars]))
        candle_proof = {'bars': len(original_bars), 'normalized_ohlc_hash': candidate_hash,
            'matches_original_entry_data_hash': candidate_hash == evidence.get('data_hash'),
            'limits': 'Original hash binds time, close, high, low only; first-seen availability is a separate check'}
        context = {}
        for name in ('BTC-EUR', 'ETH-EUR'):
            context[name] = {}
            for name_time, when in [('entry', opened), ('exit', closed)]:
                selected = [c for c in histories.get(name, []) if c.timestamp+timedelta(minutes=5)<=when]
                if selected:
                    context[name][name_time] = {'last_completed': selected[-1].timestamp.isoformat(),
                        'close': str(selected[-1].close), 'return_30m': str(selected[-1].close/selected[-7].close-1) if len(selected)>=7 else None,
                        'regime': assess(selected, when)['timeframes'], 'causality': 'RETROSPECTIVE_COMPLETED_BAR_RECONSTRUCTION_FIRST_SEEN_NOT_ESTABLISHED'}
        stop = D(position['initial_stop']);exit_bid = D(sell_payload['book']['bids'][0][0])
        plan = next(p for p in primary['exit_plans'] if p['position_id']==pid)
        trade = {'position_id': pid, 'symbol': position['symbol'], 'entry_at': position['opened_at'], 'exit_at': position['closed_at'],
            'strategy': payload['strategy_id'], 'execution_profile': evidence.get('execution_profile'),
            'backend_commit_at_entry': 'NOT_PERSISTED_IN_ORDER', 'signal_candle': evidence.get('as_of'),
            'quantity': str(quantity), 'entry_price': entry['average_fill_price'], 'exit_price': exit_order['average_fill_price'],
            'net_pnl_eur': str(net), 'gross_price_pnl_eur': str(net+fees), 'fees_eur': str(fees),
            'journal_reconciles': True, 'initial_stop': str(stop), 'final_stop': position['protective_stop'],
            'exit_bid': str(exit_bid), 'stop_condition_consistent': exit_bid<=stop if 'STOP' in reasons else None,
            'exit_reasons': reasons, 'recorded_entry_regime': reg, 'benchmark_reconstruction': context,
            'completed_candle_hash_reconstruction': candle_proof, 'original_entry_evidence': evidence, 'original_entry_book': payload['book'], 'original_exit_book': sell_payload['book'],
            'original_plan': plan['settings_json'], 'admission': {k: payload.get(k) for k in ('buy_admission','admission_quality','dispatch_quality','dispatch_buy_admission')},
            'post_exit': future, 'counterfactual': 'NO_EXECUTABLE_ALTERNATIVE_PROVEN',
            'assessment': 'Consistent protective exit; conditional favorable payoff did not imply probability of success' if 'STOP' in reasons else 'Recorded strategy exit; inspect original evidence and timing'}
        trades.append(trade)
    trades.sort(key=lambda t: t['entry_at'])
    by_profile = defaultdict(lambda: {'trades': 0, 'net_pnl_eur': D(0)})
    for t in trades:
        v = by_profile[t['execution_profile']];v['trades']+=1;v['net_pnl_eur']+=D(t['net_pnl_eur'])
    shadows = []
    for r in header['registry']['shadows']:
        rows = core[r['database_name']];closed_positions = [p for p in rows['positions'] if p['closed_at']]
        shadows.append({'database': r['database_name'], 'state': r['state'], 'strategy': r['manifest']['strategy_id'],
            'strategy_version': r['manifest']['strategy_version'], 'manifest_hash': digest(canonical(r['manifest'])),
            'control': [a['control'] for a in rows['accounts']], 'closed_positions': len(closed_positions),
            'open_positions': sum(not p['closed_at'] for p in rows['positions']),
            'net_realized_eur': str(sum((D(p['realized_pnl']) for p in closed_positions), D(0))),
            'fees_eur': str(sum((D(f['fee']) for f in rows['fills']), D(0))),
            'funding_events': sum(j['event_type']=='INITIAL_FUNDING' for j in rows['financial_journal']),
            'normalization': 'Independent EUR500 ledger; do not compare absolute pnl with EUR7000 primary'})
    total = sum((D(t['net_pnl_eur']) for t in trades), D(0))
    return {'status': 'PASS', 'collected_at': header['at'], 'primary': {'closed_positions': len(trades),
        'net_pnl_eur': str(total), 'fees_eur': str(sum((D(t['fees_eur']) for t in trades), D(0))),
        'wins': sum(D(t['net_pnl_eur'])>0 for t in trades), 'funding_events': sum(j['event_type']=='INITIAL_FUNDING' for j in primary['financial_journal']),
        'paper_only': all(o['simulated'] for rows in core.values() for o in rows['orders']),
        'accounts': primary['accounts']}, 'by_profile': {k: {**v, 'net_pnl_eur': str(v['net_pnl_eur'])} for k, v in by_profile.items()},
        'trades': trades, 'shadows': shadows, 'candle_conflicts': conflicts,
        'sources': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, candles_path)},
        'limitations': ['Per-database snapshots have different cutoffs; source exports are private local files',
            'No order embeds original backend Git SHA; execution profile is the durable attribution',
            'Retrospective completed candles do not establish first-seen availability; original decision evidence is authoritative',
            'Historical cases are development evidence; no avoided-loss, profitability or 30-day claim',
            'Later mid-price closes do not establish executable holds or missed trades']}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--candles',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();out=analysis(args.source,args.candles);args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps({'status':out['status'],'primary':out['primary'],'by_profile':out['by_profile'],'shadows':len(out['shadows'])}))


if __name__=='__main__':main()
