"""Recorded opportunity economics and historical proxy cost-distance screening."""
from __future__ import annotations

import gzip
import json
from collections import defaultdict, deque
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from statistics import median

from v45_analyze import decode_decision, decode_features, decode_signal

from autotrader.research.data import load_dataset
from autotrader.shadow.versions import frozen_module


def main() -> None:
    root = Path('docs/evidence/v4_5_rc2')
    with gzip.open('docs/evidence/v4_5/observations.jsonl.gz', 'rt') as stream:
        records = [json.loads(line) for line in stream]
    instruments = {p['symbol']: p for p in json.loads(Path('docs/evidence/v4_5/current-public-instruments.json').read_text())['pairs']}
    cases = []
    distances = defaultdict(list)
    for record in records:
        if record.get('identity') == 'official' or record.get('kind') != 'account':
            continue
        if not record['record']['manifest'].get('execution_fingerprint'):
            continue
        data = record['data']
        features = [decode_features(f['payload_json']) for f in data['features']]
        signals = {s.signal_id: s for s in (decode_signal(s['payload_json']) for s in data['signals'])}
        for f in features:
            ask = D(str(f.metadata.get('best_ask', 0)))
            if ask > 0 and f.atr:
                distances[f.symbol].append(float(2*f.atr/ask*10000))
        for raw in data['decisions']:
            decision = decode_decision(raw['payload_json'])
            if not decision.accepted or decision.action.value != 'BUY':
                continue
            stamp = signals[decision.signal_ids[0]].timestamp
            f = next(f for f in features if f.timestamp == stamp and f.symbol == decision.symbol)
            m = f.metadata
            entry = decision.entry_price
            fee, slip, quantity = D(10), D(8), decision.proposed_quantity
            purchase_unit = entry * (1+slip/10000) * (1+fee/10000)
            sale_factor = (1-slip/10000)*(1-fee/10000)
            target_net = [quantity*(target*sale_factor-purchase_unit) for target in decision.take_profit_targets]
            net_stop_loss = quantity*(purchase_unit-decision.stop_loss*sale_factor)
            cases.append({'decision_id': decision.decision_id, 'experiment_id': record['identity'],
                'symbol': decision.symbol, 'candle_at': stamp.isoformat(), 'entry': str(entry),
                'bid': m.get('best_bid'), 'ask': m.get('best_ask'), 'proposed_quote': str(decision.proposed_quote_amount),
                'proposed_quantity': str(quantity), 'fee_bps_per_side': str(fee), 'slippage_bps_per_side': str(slip),
                'round_trip_fee_slippage_bps_approx': '36', 'recorded_spread_bps': m.get('spread_bps'),
                'target_prices': [str(v) for v in decision.take_profit_targets],
                'target_distance_bps': [str((v/entry-1)*10000) for v in decision.take_profit_targets],
                'stop_price': str(decision.stop_loss), 'stop_distance_bps': str((1-decision.stop_loss/entry)*10000),
                'conditional_target_net_eur': [str(v) for v in target_net],
                'conditional_reward_vs_net_stop_risk': [str(v/net_stop_loss) for v in target_net] if net_stop_loss > 0 else None,
                'recorded_bid_depth': m.get('bid_depth'), 'recorded_ask_depth': m.get('ask_depth'),
                'instruments': instruments.get(decision.symbol),
                'precision_metadata_status': 'Current RC1 public metadata; historical precision at event time NOT_VERIFIED',
                'depth_status': 'This feature export contains aggregate depth; exact submitted L2 is now independently verified in durable_rejected_order_cost_evidence.',
                'allocation_status': 'Proposal size shown here; actual submitted quantities and rejected orders are independently verified in durable_rejected_order_cost_evidence.',
                'expected_value': 'NOT_ESTIMABLE: conditional payoff is not probability-weighted expected return',
                'historical_execution_outcome': 'Historical execution outcome not verified'})
    catalog = json.loads(Path('.data/research/catalog.json').read_text())
    market_metrics = []
    for manifest in catalog['manifests']:
        if manifest['timeframe'] not in {'5m', '15m', '1h'}:
            continue
        bars = load_dataset(Path('.data/research'), manifest)
        true_ranges, target_bps = deque(maxlen=14), []
        previous_close = None
        for bar in bars:
            high, low, close = D(bar.high), D(bar.low), D(bar.close)
            true_ranges.append(max(high-low, abs(high-previous_close), abs(low-previous_close)) if previous_close else high-low)
            if len(true_ranges) == 14:
                target_bps.append(float(2*sum(true_ranges)/14/close*10000))
            previous_close = close
        market_metrics.append({'symbol': manifest['symbol'], 'timeframe': manifest['timeframe'],
            'observations': manifest['observations'], 'missing_observations': manifest['missing_observations'],
            'dataset_sha256': manifest['file_sha256'], 'median_two_atr_distance_bps': median(target_bps) if target_bps else None,
            'fraction_two_atr_below_46bps_proxy_cost': sum(v <= 46 for v in target_bps)/len(target_bps) if target_bps else None,
            'spread_bps': 'ASSUMED_10; historical measured spread unavailable', 'depth': 'NOT_RECORDED',
            'interpretation': 'Volatility/cost-distance screen only; not a strategy signal, executable reward, entry recommendation or return estimate'})
    output = {'evidence_class': 'REAL_PRODUCTION_READ_ONLY_OBSERVATION_WITH_EXPLICIT_CONDITIONAL_COST_CALCULATION',
        'accepted_recorded_cases': cases,
        'symbol_observation_distance_screen': {s: {'observations': len(v), 'median_two_atr_bps': median(v),
            'fraction_below_36bps_fee_slippage': sum(x <= 36 for x in v)/len(v),
            'interpretation': 'Hypothetical 2 ATR distance on recorded evaluated features; not additional accepted opportunities'} for s,v in distances.items()},
        'historical_proxy_market_screen': market_metrics,
        'frozen_parameters_changed': False, 'new_strategy_promoted': False,
        'untouched_holdout': False, 'conclusion': 'Cost feasibility is necessary, not sufficient. Four recorded ETH A2 first targets cannot cover modeled costs. No evidence warrants weakening the gateway or promoting a strategy.'}
    snapshot = root/'production-final.json'
    current = json.loads((snapshot if snapshot.exists() else root/'production-current.json').read_text())
    output['production_snapshot_at'] = current['captured_at']
    original_ids = {c['decision_id'] for c in cases}
    detailed = []
    domain = frozen_module('domain', 'v44')
    quality_engine = frozen_module('execution.quality', 'v44').ExecutionQualityEngine()
    frozen_clock = frozen_module('clock', 'v44')
    for account in current['accounts']:
        for order in account.get('recent_orders', []):
            payload = json.loads(order['execution_json'])
            if not payload.get('admission_quality'):
                continue
            decision = decode_decision(order['decision_payload'])
            instrument = instruments[order['symbol']]
            pair = domain.TradingPair(order['symbol'], instrument['base_asset'], 'EUR',
                price_step=D(instrument['price_step']), quantity_step=D(payload['quantity_step']),
                min_order_quote=D(instrument['min_order_quote']), min_order_base=D(instrument['min_order_base']))
            book = payload['book']
            observation = domain.OrderBook(order['symbol'], datetime.fromisoformat(book['timestamp']),
                tuple(domain.OrderBookLevel(D(p),D(q)) for p,q in book['bids']),
                tuple(domain.OrderBookLevel(D(p),D(q)) for p,q in book['asks']), book['source'])
            stored = payload['admission_quality']
            observed_at = observation.timestamp + timedelta(seconds=float(stored['entry']['book_age_seconds']))
            with frozen_clock.at(observed_at):
                replay = quality_engine.evaluate(pair, observation, D(order['quantity']), D(order['quote_amount']),
                    D(payload['fee_bps']), D(payload['slippage_bps']), [D(t) for t in payload['targets']]).payload()
            keys = ('rejection_reasons', 'breakeven_bid', 'immediate_round_trip_net', 'target_net_scenarios')
            assert all(replay[k] == stored[k] for k in keys), order['order_id']
            for key in ('fillable_quantity','vwap','gross_notional','fee','net_cash_change','allocations'):
                assert replay['entry'][key] == stored['entry'][key], (order['order_id'], key)
            entry = stored['entry']
            risk = -D(entry['net_cash_change']) - D(entry['fillable_quantity'])*D(payload['stop_loss'])*(1-D(payload['fee_bps'])/10000)*(1-D(payload['slippage_bps'])/10000)
            detailed.append({'order_id': order['order_id'], 'decision_id': order['decision_id'],
                'symbol': order['symbol'], 'status': order['status'], 'recorded_rejection': order['rejection_reason'],
                'submitted_quantity': order['quantity'], 'submitted_quote': order['quote_amount'],
                'decision_entry_price': str(decision.entry_price), 'modeled_entry_vwap': entry['vwap'],
                'fee_bps_per_side': payload['fee_bps'], 'slippage_bps_per_side': payload['slippage_bps'],
                'target_prices': payload['targets'], 'stop_price': payload['stop_loss'],
                'target_distances_bps': [str((D(t)/decision.entry_price-1)*10000) for t in payload['targets']],
                'stop_distance_bps': str((1-D(payload['stop_loss'])/decision.entry_price)*10000),
                'quantity_step_at_submission': payload['quantity_step'], 'current_precision_and_minimum_metadata': instrument,
                'historical_price_step_and_minimum': 'NOT_RECORDED; current metadata supplied separately. These do not change the replayed cost-destroyed-target verdict.',
                'book_timestamp': book['timestamp'], 'stored_bid_levels': len(book['bids']), 'stored_ask_levels': len(book['asks']),
                'recorded_bid': entry['best_bid'], 'recorded_ask': entry['best_ask'], 'spread_bps': entry['spread_bps'],
                'bid_depth': entry['bid_depth'], 'ask_depth': entry['ask_depth'],
                'conditional_target_net_eur': stored['target_net_scenarios'],
                'conditional_reward_vs_net_stop_risk': [str(D(v)/risk) for v in stored['target_net_scenarios']] if risk > 0 else None,
                'frozen_v44_quality_replay': 'EXACT_MATCH', 'executed_fill': False,
                'original_rc1_decision': order['decision_id'] in original_ids,
                'historical_stage_trace': 'NOT_RECORDED; no stage events manufactured',
                'expectancy': 'NOT_ESTIMABLE: target-hit probability is not known'})
    output['durable_rejected_order_cost_evidence'] = detailed
    output['correction_to_rc1_summary'] = {
        'original_rc1_raw_order_count': 4, 'original_rc1_summary_zero_orders': 'INCORRECT',
        'current_captured_rejected_orders': len(detailed), 'original_decisions_matched': sum(d['original_rc1_decision'] for d in detailed),
        'confirmed_gate': 'execution_quality:first_target_destroyed_by_execution_costs',
        'historical_rc1_assessment': 'Historical execution outcome not verified',
        'updated_evidence': 'Actual immutable order records identify the refusals. Missing stage traces remain unknown; engineering replay is independent.'}
    (root/'execution-cost-analysis.json').write_text(json.dumps(output, indent=2, default=str)+'\n')
    print(json.dumps({'accepted_cases': len(cases), 'historical_symbol_timeframe_screens': len(market_metrics)}))


if __name__ == '__main__':
    main()
