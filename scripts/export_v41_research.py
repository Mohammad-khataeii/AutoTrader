"""Export matching-source complete intraday research; refuse diagnostic/partial runs."""
from __future__ import annotations

import csv
import gzip
import io
import json
from pathlib import Path
from typing import Any

from autotrader.research.artifacts import source_fingerprint
from autotrader.research.data import atomic_write, canonical, digest


def csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    stream=io.StringIO(newline='')
    fields=list(dict.fromkeys(key for row in rows for key in row))
    writer=csv.DictWriter(stream,fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({k:json.dumps(v,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in row.items()})
    return stream.getvalue().encode()


def main() -> None:
    root=Path('.data/research')
    current=source_fingerprint()[0]
    candidates=[]
    for path in root.glob('runs/*/summary.json'):
        report=json.loads(path.read_bytes())
        if (report.get('source_fingerprint')==current and set(report.get('timeframes',{}))=={'5m','15m'} and
            all(len(group['strategies'])==6 for group in report['timeframes'].values())):
            candidates.append((path,report))
    if not candidates:
        raise RuntimeError('No completed matching-source full intraday study. Finish it before exporting.')
    path,report=max(candidates,key=lambda p:p[0].parent.name)
    output=Path('docs/evidence')
    atomic_write(output/'v4_1-research-results.json',(json.dumps(report,indent=2)+'\n').encode())
    manifest=json.loads((path.parent/'manifest.json').read_bytes())
    atomic_write(output/'v4_1-research-manifest.json',(json.dumps(manifest,indent=2)+'\n').encode())
    trades,curves,groups=[],[],[]
    lines=['# V4.1 executed five-minute research','',f"Run `{report['run_id']}`; source `{current}`.",
        f"Full JSON artifacts: `{path.parent}`. Reproduce: `python3 -m autotrader.research.cli research evaluate --root .data/research --timeframes 5m 15m`.",'',
        '**'+report['verdict']+'**. Historical simulated results are not forecasts. No strategy is automatically approved.','',
        '| TF | Strategy | Net EUR | Closed trades | Max DD | Profit factor | Fee stress EUR | Spread/slippage stress EUR | Passed |',
        '|---|---|---:|---:|---:|---:|---:|---:|---|']
    validation=['# V4.1 statistical validation','',f"Run `{report['run_id']}`. {report['verdict']}.",'',
        'The original criteria remain: positive OOS net return/expectancy, PF above 1.2, at least 60 closed positions and 30 independent entry dates, drawdown at most 10%, positive sufficiently populated results in at least three assets/two regimes, at least three of four profitable walk-forward windows, robust cost stress and neighboring training parameters, positive familywise-adjusted weekly block-bootstrap lower bound, complete position data, positive validation and multiple-timeframe validation. Counts are only part of sufficiency.','',
        'Train/validation/test fractions are 60/20/20 with 12-bar purge and one-bar embargo. Three predeclared choices are selected using training only. The full strict test replay freezes its training choice. Separate rolling walk-forward experiments may train on earlier observations available at each later window; their results do not retune the full strict test. All failures are retained.','',
        'Historical dates overlap previous engineering evidence and these studies have been replayed during development. They are not described as newly untouched. No future pilot has elapsed. Bootstrap blocks of active entry weeks and unique entry dates approximate dependence; sparse/no-entry weeks and heuristic regimes limit confidence.','',
        '| TF | Strategy | Train grid index | Validation EUR | Independent entry dates | Block interval | Failed gates |',
        '|---|---|---:|---:|---:|---|---|']
    regimes=['# V4.1 market-regime results','',f"Run `{report['run_id']}`. Regimes are causal heuristic labels at entry, not hindsight ground truth.",'',
        'The strategy engine uses the prior completed five-minute feature cross-section and complete four-bar confirmation (20m for 5m; 1h for 15m). No unfinished higher candle is joined. Future-candle mutation and prefix invariance tests cover the causal boundary. Current-bar final volume is unavailable at the open: modeled shared depth uses previous completed volume. Real historical Revolut X L2 is unavailable.','',
        'Group P&L includes marked remaining positions. Group returns/drawdown use a shared EUR500 attribution denominator; they are contributions to the common portfolio, not independent allocations or standalone asset strategy returns. Per-asset and regime machine-readable statistics are exported alongside full curves.','',
        '| TF | Strategy | Entry regime | Closed trades | Net contribution EUR | Fees EUR | PF |',
        '|---|---|---|---:|---:|---:|---:|']
    for tf,group in report['timeframes'].items():
        for strategy,result in group['strategies'].items():
            metric=result['out_of_sample'];pf=metric['profit_factor']
            pf_text=f'{pf:.4f}' if pf is not None else 'undefined'
            stress=result['sensitivity']
            lines.append(f"| {tf} | {strategy} | {metric['net_profit']:.4f} | {metric['trades']} | {metric['max_drawdown']:.4%} | {pf_text} | {stress[0]['net_profit']:.4f} | {stress[1]['net_profit']:.4f} | {result['gates']['passed']} |")
            validation.append(f"| {tf} | {strategy} | {group['frozen_parameters']['selected_grid_index'][strategy]} | {result['validation']['net_profit']:.4f} | {metric['effective_independent_entry_dates']} | {result['gates']['weekly_four_block_bootstrap_interval']} | {', '.join(result['gates']['failure_reasons'])} |")
            full=json.loads((path.parent/f'{tf}-{strategy}-test.json').read_bytes())
            trades.extend({'run_id':report['run_id'],'timeframe':tf,'strategy':strategy,**f} for f in full['fills'])
            dd={r['timestamp']:r['drawdown'] for r in full['drawdown_curve']}
            curves.extend({'run_id':report['run_id'],'timeframe':tf,'strategy':strategy,**r,'drawdown':dd[r['timestamp']]} for r in full['curve'])
            for dimension,values in metric['grouped_closed_position_statistics'].items():
                for name,stats in sorted(values.items()):
                    groups.append({'run_id':report['run_id'],'timeframe':tf,'strategy':strategy,'dimension':dimension,'group':name,**stats})
                    if dimension=='regime':
                        gpf=stats['profit_factor'];gpf_text=f'{gpf:.4f}' if gpf is not None else 'undefined'
                        regimes.append(f"| {tf} | {strategy} | {name} | {stats['closed_positions']} | {stats['net_profit']:.4f} | {stats['fees']} | {gpf_text} |")
    lines+=['','## Frozen intervals','']
    for tf,group in report['timeframes'].items():
        f=group['frozen_parameters']
        lines.append(f"- {tf}: training ends {f['training_end']}; validation {f['validation_start']} to {f['validation_end_exclusive']}; strict test {f['test_start']} to {f['test_end_exclusive']}. Ends exclusive; UTC.")
    lines+=['','## Common-capital references','','| TF | Reference | Net EUR | Return | Max DD |','|---|---|---:|---:|---:|']
    for tf,group in report['timeframes'].items():
        for name,r in group['benchmarks'].items():
            lines.append(f"| {tf} | {name} | {r['net_profit']:.4f} | {r['total_return']:.4%} | {r['max_drawdown']:.4%} |")
    lines+=['','Costs: 10 bps per-side fees, 10 bps full spread, 8 bps per-side slippage; fee stress 20 bps; friction stress 25 bps spread and 20 bps slippage. Shared liquidity is assumed at 1% of previous completed volume. Current-bar final volume is never known at the open. Fixed historical quantity precision is an assumption. No actual historical order book is claimed.','',
        'Cash, BTC/ETH buy-and-hold, current-universe equal-weight, legacy signals on common execution, runtime-default V4 parameters, independently frozen V4.1 members, and the validated ensemble use EUR500 initial capital. Passive references use full capital with estimated endpoint liquidation costs and have different exposure; bot positions obey the existing reserve and risk controls. Residual positions are marked, not forcibly liquidated. Mock AI is an integration comparison only.','',
        f"Exports: {len(trades)} fills and {len(curves)} equity/drawdown rows across 12 independent strategy/timeframe simulations. See gzip CSV exports and grouped statistics. These are not real-market paper-account fills.",'',
        'BTC/ETH have longer five-minute training coverage than other assets; the cross-sectional universe therefore changes as genuine data becomes available. Missing recent histories block signals. No absence of a trade is imputed as a zero-price candle. Per-asset diagnostics are portfolio contributions and do not establish a standalone edge.']
    for file,body in [('V4_1_FIVE_MINUTE_BACKTESTS.md',lines),('V4_1_STRATEGY_VALIDATION.md',validation),('V4_1_MARKET_REGIME_RESULTS.md',regimes)]:
        Path('docs',file).write_text('\n'.join(body)+'\n')
    exports={}
    for name,rows in [('trades',trades),('equity',curves),('groups',groups)]:
        payload=gzip.compress(csv_bytes(rows),mtime=0)
        target=output/f'v4_1-research-{name}.csv.gz';atomic_write(target,payload)
        exports[target.name]={'sha256':digest(payload),'rows':len(rows),'bytes':len(payload)}
    atomic_write(output/'v4_1-export-manifest.json',canonical({'run_id':report['run_id'],'source_fingerprint':current,'exports':exports}))
    print(report['run_id'],report['verdict'],len(trades),'fills',len(curves),'curve rows')


if __name__=='__main__':
    main()
