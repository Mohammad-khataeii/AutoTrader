"""Independent, unvalidated target/universe research on immutable historical proxies."""
from __future__ import annotations

import json
import shutil
from decimal import Decimal as D
from pathlib import Path

from autotrader.shadow.versions import V44_EXECUTION, frozen_module


def main() -> None:
    source = Path('.data/research').resolve()
    root = Path('.tools/rc2-research')
    root.mkdir(exist_ok=True)
    for name in ('datasets', 'manifests'):
        target = root / name
        if target.is_symlink():
            target.unlink()
        if not target.exists():
            shutil.copytree(source / name, target)
    catalog = json.loads((source / 'catalog.json').read_text())
    params = frozen_module('research.strategies', 'v44').StrategyParameters
    workflow = frozen_module('research.workflow', 'v44')
    report = workflow.run_full(root, catalog, timeframes=('5m',),
        assets=('BTC', 'ETH', 'SOL', 'XRP', 'ADA', 'LINK', 'AVAX', 'DOT'),
        strategy_ids=('A2_CONFIRMED_PULLBACK', 'B2_CONFIRMED_COMPRESSION', 'C2_LIQUID_RETEST', 'E2_ABSOLUTE_RELATIVE_STRENGTH'),
        grid=(params(stop_atr=D(2), target_atr=D(2)), params(stop_atr=D(2), target_atr=D(4))), experimental=True)
    output = {'evidence_class': 'HISTORICAL_PROXY_RESEARCH', 'status': 'EXECUTED',
        'runtime': V44_EXECUTION, 'production_parameters_changed': False, 'promotion': 'FORBIDDEN',
        'untouched_holdout': False, 'limitation': 'Previously studied intervals; chronological splits do not make them untouched. Current surviving Coinbase EUR universe; no historical Revolut X L2. Target 4 ATR is a separate hypothesis, never a manifest edit.',
        'report': report}
    Path('docs/evidence/v4_5_rc2/universe-target-research.json').write_text(json.dumps(output, indent=2) + '\n')
    print(report['verdict'], flush=True)
    # A separate existing V4 rule family supplies an honest timeframe diagnostic;
    # A2/B2/C2/E2 explicitly require 5m inputs and must not be relabeled as 15m/1h.
    timeframe = workflow.run_full(root, catalog, timeframes=('15m', '1h'),
        assets=('BTC', 'ETH', 'SOL', 'XRP', 'ADA', 'LINK', 'AVAX', 'DOT'),
        strategy_ids=('A_TREND_PULLBACK', 'B_COMPRESSION_BREAKOUT'),
        grid=(params(stop_atr=D(2), target_atr=D(2)), params(stop_atr=D(2), target_atr=D(4))), experimental=False)
    Path('docs/evidence/v4_5_rc2/timeframe-research.json').write_text(json.dumps({
        'evidence_class': 'HISTORICAL_PROXY_RESEARCH', 'strategy_identity': 'Separate original V4 rule family; not A2/B2/C2/E2',
        'untouched_holdout': False, 'promotion': 'FORBIDDEN', 'report': timeframe}, indent=2) + '\n')
    print(timeframe['verdict'], flush=True)


if __name__ == '__main__':
    main()
