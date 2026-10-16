"""Derive auditable group/period diagnostics without changing frozen research."""
from __future__ import annotations

import gzip
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from export_v41_research import csv_bytes

from autotrader.research.data import atomic_write, canonical, digest


def main() -> None:
    out=Path('docs/evidence')
    manifest=json.loads((out/'v4_1-export-manifest.json').read_bytes())
    root=Path('.data/research/runs')/manifest['run_id']
    closed,groups,periods=[],[],[]
    for path in sorted(root.glob('*-test.json')):
        full=json.loads(path.read_bytes())
        if len(full['strategy_ids'])!=1:
            continue
        prefix={'run_id':manifest['run_id'],'timeframe':full['timeframe'],'strategy':full['strategy_ids'][0]}
        positions=full['closed_positions'];fills=full['fills']
        closed.extend({**prefix,**p} for p in positions)
        for dimension,values in full['grouped_closed_position_statistics'].items():
            field='symbol' if dimension=='asset' else 'regime'
            for group,original in values.items():
                selected=[p for p in positions if p[field]==group]
                selected_fills=[f for f in fills if f[field]==group]
                pnls=[Decimal(p['realized_pnl']) for p in selected]
                wins=[p for p in pnls if p>0];losses=[p for p in pnls if p<0]
                streak=longest=0
                for p in selected:
                    streak=streak+1 if Decimal(p['realized_pnl'])<0 else 0
                    longest=max(longest,streak)
                holding=[(datetime.fromisoformat(p['closed_at'])-datetime.fromisoformat(p['opened_at'])).total_seconds() for p in selected]
                notional=sum((Decimal(f['quantity'])*Decimal(f['price']) for f in selected_fills),Decimal(0))
                entry=sum((Decimal(f['quantity'])*Decimal(f['price']) for f in selected_fills if f['side']=='BUY'),Decimal(0))
                groups.append({**prefix,'dimension':dimension,'group':group,**original,
                    'effective_independent_entry_dates':len({p['opened_at'][:10] for p in selected}),
                    'gross_profit':str(sum(wins,Decimal(0))),'gross_loss':str(-sum(losses,Decimal(0))),
                    'average_winning_trade':str(sum(wins)/len(wins)) if wins else None,
                    'average_losing_trade':str(sum(losses)/len(losses)) if losses else None,
                    'average_holding_seconds':sum(holding)/len(holding) if holding else None,
                    'longest_losing_streak':longest,'total_entry_notional_eur':str(entry),
                    'turnover_on_common_eur500':str(notional/500),
                    'confidence_interval':None,'confidence_limitation':'No standalone group confidence interval justified; entry dates approximate dependence.',
                    'sensitivity_scope':'Parameter/cost and walk-forward tests apply to the entire frozen strategy, not independently retuned subgroups.'})
        curves=defaultdict(list)
        for row in full['curve']:
            curves[row['timestamp'][:7]].append(row)
        prior=Decimal(500)
        for month,rows in sorted(curves.items()):
            final=Decimal(rows[-1]['equity'])
            month_positions=[p for p in positions if p['closed_at'][:7]==month]
            month_fills=[f for f in fills if f['timestamp'][:7]==month]
            high=prior;maxdd=Decimal(0)
            for row in rows:
                value=Decimal(row['equity']);high=max(high,value);maxdd=max(maxdd,(high-value)/high)
            pnl=[Decimal(p['realized_pnl']) for p in month_positions];gp=sum((p for p in pnl if p>0),Decimal(0));gl=-sum((p for p in pnl if p<0),Decimal(0))
            wins=[p for p in pnl if p>0];losses=[p for p in pnl if p<0]
            holding=[(datetime.fromisoformat(p['closed_at'])-datetime.fromisoformat(p['opened_at'])).total_seconds() for p in month_positions]
            streak=longest=0
            for value in pnl:
                streak=streak+1 if value<0 else 0
                longest=max(longest,streak)
            periods.append({**prefix,'utc_month':month,'first_observed':rows[0]['timestamp'],'last_observed':rows[-1]['timestamp'],
                'starting_marked_equity':str(prior),'ending_marked_equity':str(final),'net_marked_pnl':str(final-prior),
                'net_return_on_common_eur500':str((final-prior)/500),'closed_positions':len(pnl),
                'effective_independent_entry_dates_of_closed_positions':len({p['opened_at'][:10] for p in month_positions}),
                'gross_profit_closed_positions':str(gp),'gross_loss_closed_positions':str(gl),
                'win_rate':len(wins)/len(pnl) if pnl else None,
                'net_expectancy_closed_positions':str(sum(pnl)/len(pnl)) if pnl else None,
                'average_winning_trade':str(sum(wins)/len(wins)) if wins else None,
                'average_losing_trade':str(sum(losses)/len(losses)) if losses else None,
                'average_holding_seconds':sum(holding)/len(holding) if holding else None,
                'longest_losing_streak':longest,'confidence_interval':None,
                'profit_factor_closed_positions':str(gp/gl) if gl else None,'max_drawdown_within_period':str(maxdd),
                'fees':str(sum((Decimal(f['fee']) for f in month_fills),Decimal(0))),
                'slippage_cost':str(sum((Decimal(f['slippage_cost']) for f in month_fills),Decimal(0))),
                'spread_cost':str(sum((Decimal(f['spread_cost']) for f in month_fills),Decimal(0))),
                'average_observed_marked_exposure_eur':str(sum((Decimal(r['equity'])-Decimal(r['cash']) for r in rows),Decimal(0))/len(rows)),
                'turnover_on_common_eur500':str(sum((Decimal(f['quantity'])*Decimal(f['price']) for f in month_fills),Decimal(0))/500),
                'attribution':'Marked change since prior observed period endpoint; closed-position metrics use exit month; costs use fill month. Partial months and gaps retained.'})
            prior=final
    for name,rows in [('closed-positions',closed),('group-details',groups),('periods',periods)]:
        payload=gzip.compress(csv_bytes(rows),mtime=0);target=out/f'v4_1-research-{name}.csv.gz';atomic_write(target,payload)
        manifest['exports'][target.name]={'sha256':digest(payload),'rows':len(rows),'bytes':len(payload)}
        print(name,len(rows))
    atomic_write(out/'v4_1-export-manifest.json',canonical(manifest))


if __name__=='__main__':
    main()
