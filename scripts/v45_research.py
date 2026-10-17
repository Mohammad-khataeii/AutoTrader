"""Fixed-parameter chronological A2/B2 study; never writes the source research store."""
from __future__ import annotations

import argparse
import json
import shutil
from decimal import Decimal
from pathlib import Path

from autotrader.research.strategies import StrategyParameters
from autotrader.research.workflow import run_full


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=Path('.data/research'))
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    if args.data_root.resolve() == args.output_root.resolve():
        raise ValueError('Use a separate output store; preserve existing research publication')
    args.output_root.mkdir(parents=True, exist_ok=True)
    for name in ('datasets', 'manifests'):
        target = args.output_root / name
        if not target.exists():
            shutil.copytree(args.data_root / name, target)
    catalog = json.loads((args.data_root / 'catalog.json').read_text())
    report = run_full(args.output_root, catalog, timeframes=('5m',), assets=('BTC', 'ETH', 'SOL'),
                      strategy_ids=('A2_CONFIRMED_PULLBACK', 'B2_CONFIRMED_COMPRESSION'),
                      grid=(StrategyParameters(relative_volume=Decimal('1.5'), stop_atr=Decimal(2), target_atr=Decimal(2)),),
                      experimental=True)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps({
        'status': 'EXECUTED',
        'scope': 'Historical Coinbase EUR proxy; fixed production parameters. Previously studied periods, no untouched holdout or native manifest migration.',
        'report': report,
    }, indent=2) + '\n')
    print(report['verdict'])


if __name__ == '__main__':
    main()
