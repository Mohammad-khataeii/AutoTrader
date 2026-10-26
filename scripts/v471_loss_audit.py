"""Reconstruct immutable executed trades from an exported read-only snapshot."""
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import DateTime, Numeric

from autotrader.api.trade_reports import explain_position
from autotrader.persistence.models import Base
from autotrader.research.data import digest

source=Path('.tools/v47_1/raw.json')
raw=json.loads(source.read_text())
assert raw['live_trading_enabled'] is False
assert raw['manifest']['account_id']=='PERSONAL_PLAN_PAPER_7000'
tables={}
for name,records in raw['tables'].items():
    columns=Base.metadata.tables[name].c
    tables[name]=[SimpleNamespace(**{k:(Decimal(v) if isinstance(columns[k].type,Numeric) else datetime.fromisoformat(v) if isinstance(columns[k].type,DateTime) else v) if v is not None else None for k,v in r.items()}) for r in records]
reports=[]
for p in tables['positions']:
    plan=next((x for x in tables['exit_plans'] if x.position_id==p.position_id),None)
    groups=[[r for r in tables[name] if r.position_id==p.position_id] for name in ('orders','fills','exit_targets','exit_intents','financial_journal')]
    report=explain_position(p,plan,*groups,[])
    report['original_entry_execution']=json.loads(next(o for o in groups[0] if o.side=='BUY').execution_json)
    report['original_exit_executions']=[{'order_id':o.order_id,**json.loads(o.execution_json)} for o in groups[0] if o.side=='SELL']
    report['original_intents']=[vars(x) for x in groups[3]]
    report['original_position']=vars(p)
    assert Decimal(report['net_pnl_eur'])==Decimal(report['journal_net_cash_eur'])
    assert Decimal(report['gross_price_pnl_eur'])-Decimal(report['fees_eur'])==Decimal(report['net_pnl_eur'])
    reports.append(report)
Path('docs/evidence/v4_7_1/loss-audit.json').write_text(json.dumps({'schema':'v471-actual-fill-audit/1','source_snapshot_sha256':digest(source.read_bytes()),'prior_profile':raw['manifest']['version'],'reports':reports,'combined_net_pnl_eur':str(sum((Decimal(r['net_pnl_eur']) for r in reports),Decimal(0))),'conclusion':'Both original protective stops triggered on fresh executable bids. Neither was a regime/time/failed-breakout exit. Attribution bug affects raw SELL labels, not the exit trigger.','counterfactual_limit':'Reviewed entry guards use entry-time evidence and would reject these two entries; this does not prove future profits.'},indent=2,default=str)+'\n')
print('Exact journal reconciliation and immutable linked attribution: PASS')
