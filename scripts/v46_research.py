"""Preregistered bounded successor comparisons. No financial account or research pointer mutation."""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from autotrader.opportunity.engine import SuccessorParameters
from autotrader.research.data import canonical, digest, load_dataset
from autotrader.research.simulation import Costs, ResearchSimulation
from autotrader.research.strategies import StrategyParameters

NEW = ('A3_COST_AWARE_CONTINUATION', 'B3_STATEFUL_BREAKOUT', 'E3_ADAPTIVE_RELATIVE_STRENGTH')
OLD = ('A2_CONFIRMED_PULLBACK', 'B2_CONFIRMED_COMPRESSION', 'E2_ABSOLUTE_RELATIVE_STRENGTH')


def compact(report):
    keys = ('net_profit', 'trades', 'fills_count', 'max_drawdown', 'sharpe_ratio', 'profit_factor',
            'win_rate', 'expectancy', 'fees', 'total_return', 'exposure', 'rejections', 'opportunity_counts',
            'regime_observations', 'grouped_closed_position_statistics', 'costs', 'start', 'end_exclusive',
            'pending_conditional_entries_at_end', 'open_positions_at_end')
    return {k: report[k] for k in keys if k in report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=60)
    parser.add_argument('--output', type=Path, default=Path('.tools/v46-research'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    root = Path('.data/research')
    catalog = json.loads((root/'catalog.json').read_text())
    manifests = [m for m in catalog['manifests'] if m['timeframe'] == '5m']
    end = min(datetime.fromisoformat(m['requested_end_exclusive']) for m in manifests)
    start = end - timedelta(days=args.days)
    bars = [b for m in manifests for b in load_dataset(root, m) if start <= datetime.fromisoformat(b.start) < end]
    times = sorted({datetime.fromisoformat(b.start) for b in bars})
    train_end, validation_start = times[int(len(times)*.6)-1], times[int(len(times)*.6)+72]
    validation_end, test_start = times[int(len(times)*.8)-1], times[int(len(times)*.8)+72]
    first = times[min(720, len(times)//10)]
    p = SuccessorParameters()
    grids = {
        NEW[0]: [p, replace(p, target_basis='5m', target_atr=D(3)), replace(p, target_basis='5m', target_atr=D(4)),
                 replace(p, target_basis='STRUCTURE'), replace(p, holding_bars=72, target_atr=D(3))],
        NEW[1]: [p, replace(p, compression_width=D('.015'), breakout_volume=D('1.5'), retest_bars=6),
                 replace(p, compression_width=D('.03'), breakout_volume=D('1.2'), retest_bars=12),
                 replace(p, target_basis='5m', target_atr=D(3))],
        NEW[2]: [p, replace(p, relative_z=D('.5')), replace(p, relative_z=D('1.25')),
                 replace(p, target_basis='5m', target_atr=D(4)), replace(p, holding_bars=72)]}
    import autotrader
    package = Path(autotrader.__file__).parent
    closure = [*(package/'opportunity').glob('*.py'), package/'research/simulation.py',
               package/'research/panel.py', package/'risk.py', package/'execution/pricing.py']
    identity = {str(p.relative_to(package)): digest(p.read_bytes()) for p in sorted(closure)}
    preregistered = {'engineering_class': 'HISTORICAL_PROXY_RESEARCH', 'code_files': identity,
        'code_fingerprint': digest(canonical(identity)), 'dataset_hashes': {m['symbol']: m['file_sha256'] for m in manifests},
        'requested_period_days': args.days, 'actual_start': first.isoformat(), 'end_exclusive': end.isoformat(),
        'split': {'train_end_exclusive': train_end.isoformat(), 'validation_start': validation_start.isoformat(),
            'validation_end_exclusive': validation_end.isoformat(), 'test_start': test_start.isoformat(), 'purge_embargo_bars': 72},
        'grid': {k: [p.payload() for p in ps] for k, ps in grids.items()}, 'selection': 'Training PnL minus EUR500*drawdown; >=8 closed positions; no validation/test retuning',
        'untouched_holdout': False, 'multiple_comparisons': sum(len(ps) for ps in grids.values()) + 30,
        'limits': ['Previously studied Coinbase EUR intervals; chronological test is not untouched.',
            'Current surviving asset universe, incomplete candles, no historical connected-exchange L2.',
            'Fixed 10bps spread, 10bps per-side fee, 8bps per-side slippage, 1% prior completed volume depth.',
            'Conditional-limit research retries IOC at subsequent observed opens for three bars; missed fills and invalidation counted, no queue position, first-touch or guaranteed passive fill.']}
    (args.output/'preregistered.json').write_text(json.dumps(preregistered, indent=2)+'\n')
    print('Preparing original matched baseline', flush=True)
    baseline = ResearchSimulation(bars, experimental=True)
    legacy = {s: compact(baseline.run(start=test_start, end=end, strategy_ids={s}, parameters=StrategyParameters(stop_atr=D(2), target_atr=D(2)))) for s in OLD}
    print('Preparing causal successor panel', flush=True)
    baseline.enable_successors()
    sim = baseline
    results, frozen = {}, {}
    for strategy in NEW:
        training = []
        for index, param in enumerate(grids[strategy]):
            run = sim.run(start=first, end=train_end, strategy_ids={strategy}, successor_parameters=param)
            training.append(compact(run))
            print(strategy, 'train', index, round(run['net_profit'], 4), run['trades'], flush=True)
        chosen = max(range(len(training)), key=lambda i: training[i]['net_profit'] - 500*training[i]['max_drawdown'] if training[i]['trades'] >= 8 else -1e9)
        param = grids[strategy][chosen]
        frozen[strategy] = param.payload()
        (args.output/'frozen-training-selection.json').write_text(json.dumps({'parameters': frozen, 'preregistered_sha256': digest((args.output/'preregistered.json').read_bytes())}, indent=2)+'\n')
        validation = sim.run(start=validation_start, end=validation_end, strategy_ids={strategy}, successor_parameters=param)
        test = sim.run(start=test_start, end=end, strategy_ids={strategy}, successor_parameters=param)
        sensitivity = sim.run(start=test_start, end=end, strategy_ids={strategy}, successor_parameters=param,
            costs=Costs(fee_bps=D(15), slippage_bps=D(12), spread_bps=D(15)))
        narrow = sim.run(start=test_start, end=end, strategy_ids={strategy}, successor_parameters=param,
            universe={'BTC-EUR', 'ETH-EUR', 'SOL-EUR'})
        old_regime = sim.run(start=test_start, end=end, strategy_ids={strategy}, successor_parameters=param, regime_model='LEGACY_BULL_FILTER')
        timing = {method: compact(sim.run(start=test_start, end=end, strategy_ids={strategy}, successor_parameters=param, entry_method=method))
                  for method in ('BID_IOC', 'PULLBACK_IOC', 'RETEST_IOC')}
        walk = []
        # Parameters remain locked from the first 60%; disjoint subsequent windows
        # measure stability, without calling earlier samples out-of-sample.
        for lo, hi in ((.6, .73), (.73, .86), (.86, 1.0)):
            a = times[int(len(times)*lo)+72]
            b = times[int(len(times)*hi)-1] if hi < 1 else end
            walk.append(compact(sim.run(start=a, end=b, strategy_ids={strategy}, successor_parameters=param)))
        gates = {'positive_validation': validation['net_profit'] > 0, 'positive_test': test['net_profit'] > 0,
            'test_closed_positions_at_least_30': test['trades'] >= 30, 'cost_stress_positive': sensitivity['net_profit'] > 0,
            'drawdown_below_five_percent': test['max_drawdown'] < .05,
            'positive_sharpe': (test.get('sharpe_ratio') or -1) > 0,
            'positive_two_of_three_locked_forward_windows': sum(w['net_profit'] > 0 for w in walk) >= 2,
            'untouched_holdout_verified': False}
        results[strategy] = {'training_grid': training, 'chosen_grid_index': chosen, 'parameters': param.payload(),
            'validation': compact(validation), 'test': compact(test), 'cost_stress': compact(sensitivity),
            'three_market_comparison': compact(narrow), 'legacy_regime_filter': compact(old_regime),
            'entry_timing': timing, 'locked_forward_windows': walk, 'validation_gates': gates,
            'status': 'UNVALIDATED' if not all(gates.values()) else 'RESEARCH_REVIEW_REQUIRED'}
        (args.output/(strategy+'.json')).write_text(json.dumps(results[strategy], indent=2)+'\n')
        print(strategy, 'test', test['net_profit'], test['trades'], 'gates', gates, flush=True)
    assert identity == {str(p.relative_to(package)): digest(p.read_bytes()) for p in sorted(closure)}, 'Research implementation changed during execution; rerun from an immutable snapshot'
    report = {'evidence_class': 'HISTORICAL_PROXY_RESEARCH', 'preregistered': preregistered, 'baseline': legacy,
        'successors': results, 'duration_seconds': round(time.monotonic()-started, 2), 'new_accounts_created': False,
        'new_allocations': False, 'promotions': [], 'verdict': 'No automatic promotion. Entry frequency is not evidence of positive expected return.'}
    (args.output/'comparison-v46.json').write_text(json.dumps(report, indent=2)+'\n')
    destination = Path('docs/evidence/v4_6');destination.mkdir(parents=True, exist_ok=True)
    (destination/'research-comparison.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
