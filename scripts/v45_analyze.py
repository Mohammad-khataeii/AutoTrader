"""Reproduce gate attribution from sanitized recorded production inputs, offline."""
from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from dataclasses import fields
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path

from autotrader.domain import (
    DataQuality,
    DecisionAction,
    MarketFeatures,
    StrategySignal,
    TradingDecision,
)
from autotrader.shadow.diagnostics import explain
from autotrader.shadow.gates import aggregate
from autotrader.shadow.versions import convert, legacy_module


def decode_features(payload):
    data = json.loads(payload)
    for f in fields(MarketFeatures):
        if f.name not in {'symbol', 'timestamp', 'timeframe', 'data_quality', 'metadata'}:
            data[f.name] = D(data[f.name]) if data.get(f.name) is not None else None
    data['timestamp'] = datetime.fromisoformat(data['timestamp'])
    data['data_quality'] = DataQuality(data['data_quality'])
    return MarketFeatures(**data)


def decode_signal(payload):
    data = json.loads(payload)
    data['timestamp'] = datetime.fromisoformat(data['timestamp'])
    data['data_quality'] = DataQuality(data['data_quality'])
    for k in ('score', 'estimated_cost_bps'):
        data[k] = D(data[k])
    return StrategySignal(**data)


def decode_decision(payload):
    data = json.loads(payload)
    data['timestamp'] = datetime.fromisoformat(data['timestamp'])
    data['action'] = DecisionAction(data['action'])
    for k in ('proposed_quote_amount', 'proposed_quantity', 'entry_price', 'stop_loss'):
        data[k] = D(data[k]) if data.get(k) is not None else None
    data['take_profit_targets'] = tuple(D(v) for v in data['take_profit_targets'])
    return TradingDecision(**data)


def analyze(records, output):
    summaries, parity, quality, examples = {}, {}, {}, []
    allocation_path = output / 'allocation-records.json'
    allocations = json.loads(allocation_path.read_text()) if allocation_path.exists() else {}
    for record in records:
        if record.get('kind') != 'account' or record['identity'] == 'official':
            continue
        account, data = record['record'], record['data']
        manifest = account['manifest']
        features = [decode_features(f['payload_json']) for f in data['features']]
        by_stamp = {(f.symbol, f.timestamp): f for f in features}
        signals = {s.signal_id: s for s in [decode_signal(s['payload_json']) for s in data['signals']]}
        explanations, mismatches, primary_mismatches = [], [], []
        parameters = legacy_module('research.strategies').StrategyParameters(**{k:D(v) for k,v in manifest['parameters'].items()})
        engine = legacy_module('research.experimental').ExperimentalStrategyEngine(parameters, {manifest['strategy_id']})
        for raw in data['decisions']:
            decision = decode_decision(raw['payload_json'])
            selected = [signals[s] for s in decision.signal_ids if s in signals]
            if not selected:
                continue
            timestamp = selected[0].timestamp
            f = by_stamp.get((decision.symbol, timestamp))
            if f is None:
                continue
            benchmarks = {s: by_stamp[s, timestamp] for s in ('BTC-EUR', 'ETH-EUR') if (s, timestamp) in by_stamp}
            runner = 'native-v44' if manifest.get('execution_fingerprint') else 'verified-v42'
            row = explain(f, selected, decision, manifest, runner, benchmarks)
            advice = next((a for a in allocations.get(record['identity'], []) if a['key'] == 'alloc:' + decision.decision_id), None)
            if decision.accepted and advice:
                payload = json.loads(advice['payload_json'])
                row['allocation'] = {'reached': True, 'accepted': payload['accepted'], 'reason': payload['reasons']}
                row['execution'] = {'reached': True, 'stage': 'entry', 'refusal_gate':'unobserved_pre_order_outcome',
                                    'reason':'NOT_VERIFIED: V4.4 lost accepted-decision explanation; no order persisted. Invocation inferred from accepted allocation and executed runtime source.'}
                row['final_state'] = 'EXECUTION_OUTCOME_UNOBSERVED'
            explanations.append(row)
            replay = engine.generate(convert(f), convert(benchmarks.get('BTC-EUR')), convert(benchmarks.get('ETH-EUR')))
            # Compare every actual eligibility/veto/regime, excluding generated IDs.
            observed = {s.strategy_id:(s.evidence['entry_eligible'],s.evidence['veto'],s.evidence['regime']) for s in selected}
            actual = {s.strategy_id:(s.evidence['entry_eligible'],s.evidence['veto'],s.evidence['regime']) for s in replay}
            if observed.get(manifest['strategy_id']) != actual.get(manifest['strategy_id']):
                primary_mismatches.append(decision.decision_id)
            if observed != actual:
                mismatches.append(decision.decision_id)
        summary = aggregate(explanations)
        summary.update(state=account['state'], strategy=manifest['strategy_id'],
                       recorded_decisions=len(data['decisions']), window_decision_counts=data['window_decision_counts'],
                       first_evaluation=data['decisions'][0]['created_at'] if data['decisions'] else None,
                       last_evaluation=data['decisions'][-1]['created_at'] if data['decisions'] else None,
                       lifetime_financial_counts=data['counts'],
                       allocation_attempts_observed=sum(r.get('allocation',{}).get('reached',False) for r in explanations),
                       allocation_inference='BUY allocation uses separately persisted alloc records. WAIT allocation calls are not trade attempts. Entry invocation after accepted allocation is control-flow inference; missing refusal reasons remain NOT_VERIFIED.')
        summaries[record['identity']] = summary
        parity[record['identity']] = {'recorded_evaluations_replayed':len(explanations), 'primary_strategy_mismatches':primary_mismatches, 'signal_eligibility_veto_regime_mismatches':mismatches,
                                     'full_decision_execution_replay':'NOT_VERIFIED; controlled database lifecycle and reconstructed accepted inputs tested separately. Historical L2 and exact benchmark batch membership were not retained.',
                                     'diagnostic_condition_mismatches':summary['diagnostic_mismatches'],
                                     'momentum_component_mismatches':sum(r['momentum_component_parity'] is False for r in explanations),
                                     'benchmark_reconstruction_limitation':'V4.4 did not retain the benchmark timestamps actually available in each scan batch. Matching final candle timestamps can add a benchmark observed in a later scan. Two active-window veto discrepancies are NOT_VERIFIED, not demonstrated indicator bugs.'}
        quality[record['identity']] = {
            'data_quality':dict(Counter(f.data_quality.value for f in features)),
            'context_15m_ready':sum(f.metadata.get('experimental_context',{}).get('15m',{}).get('ready',False) for f in features),
            'context_1h_ready':sum(f.metadata.get('experimental_context',{}).get('60m',{}).get('ready',False) for f in features),
            'missing_required_metadata':dict(Counter(k for r in explanations for k,v in r['inputs'].items() if v is None)),
            'sources':data['candle_sources'],
            'prestrategy_skip_counts':'NOT_VERIFIED; old completed scans were overwritten; latest scanner snapshot preserved separately.',
        }
        examples.extend(explanations[:1])
    def save(name,value):
        (output/name).write_text(json.dumps(value,indent=2,default=str)+'\n')
    save('trade-gate-attribution.json', {'window_hours_requested':24,'accounts':summaries,'decision_examples':examples})
    save('legacy-runner-parity.json', {'status':'PARTIAL', 'legacy_v42_status': 'PASS' if all(not parity[r['identity']]['signal_eligibility_veto_regime_mismatches'] for r in records if r.get('record',{}).get('manifest',{}).get('source_fingerprint') == '9f03f481049165cba9b54082d6f45f6e06e76d4b0a1625832b5f8434f8ace23a') else 'FAIL','accounts':parity,
                                     'scope':'Offline exact frozen strategy on recorded decimal feature/context inputs; not a prospective return estimate.'})
    market = {'accounts': quality,
              'selection_limitation': 'Stored strategy features are post-validation survivors. Historical pre-strategy rejections were overwritten; no all-request success or zero-stale-data claim follows.'}
    http_path = output / 'public-http-events.jsonl.gz'
    if http_path.exists():
        with gzip.open(http_path, 'rt') as stream:
            events = [json.loads(line) for line in stream]
        times = [datetime.strptime(e['timestamp_utc'], '%Y-%m-%d %H:%M:%S,%f') for e in events]
        count = Counter(e['endpoint'] + ':' + e['status'] for e in events)
        seconds = (max(times)-min(times)).total_seconds() if times else 0
        market['worker_http_log_measurement'] = {
            'source': 'Read-only docker logs; retained worker lifetime is shorter than requested 24h',
            'start_utc': min(times).isoformat() if times else None,
            'end_utc': max(times).isoformat() if times else None,
            'seconds': seconds, 'endpoint_symbol_status_counts': dict(count),
            'counts_per_minute': {k:round(v*60/seconds,5) for k,v in count.items()} if seconds else {},
            'limitation': 'HTTP observations, not all shared-counter history. Cache hits have no HTTP line; retries are separate requests.'}
    production = output / 'production-readonly-diagnostics.json'
    if production.exists():
        market['production_market_health_snapshot'] = json.loads(production.read_text())['api']['/api/market-data/health']['data']
    save('market-data-quality.json', market)
    save('momentum-veto-breakdown.json',{'component_evidence_limitations': {'extension_falling_volume_spread_regime':'Exact stored feature/context/signal values', 'bearish_benchmark':'Reconstructed final timestamps can include peers observed later; exact native V4.4 component frequency NOT_VERIFIED. See parity discrepancies.', 'justification':'All five OR components exist in the immutable original D2 implementation. No component disabled or threshold lowered.'}, 'accounts':{k:{'components':v['momentum_components'],
                                                       'otherwise_eligible':v['counts']['eligible_signals'],
                                                       'intersections':v['pairwise_intersections'],
                                                       'first_blockers':v['causal_first_blockers']} for k,v in summaries.items()}})
    print(json.dumps({k:{'strategy':v['strategy'],'state':v['state'],'counts':v['counts'],'blockers':v['causal_first_blockers'],
                         'failures':v['independent_failures']} for k,v in summaries.items()},indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=Path('docs/evidence/v4_5/observations.jsonl.gz'))
    parser.add_argument('--output',type=Path,default=Path('docs/evidence/v4_5'))
    args=parser.parse_args()
    with gzip.open(args.input,'rt') as stream:
        rows=[json.loads(line) for line in stream]
    analyze(rows,args.output)
