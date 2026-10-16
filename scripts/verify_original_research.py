"""Read-only exact replay of a frozen original historical research run."""
import argparse
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from autotrader.research.artifacts import source_fingerprint
from autotrader.research.data import digest, load_dataset
from autotrader.research.simulation import ResearchSimulation
from autotrader.research.strategies import StrategyParameters

replay_source=source_fingerprint()[0]
parser=argparse.ArgumentParser(description='Reproduce every archived original strategy field without modifying the original run.')
parser.add_argument('--root',type=Path,default=Path('.data/research'))
parser.add_argument('--run',default='research-20261016T044934')
parser.add_argument('--output',type=Path,default=Path('.tools/original-reproduction.json'))
args=parser.parse_args()
root=args.root;run=root/'runs'/args.run
manifest=json.loads((run/'manifest.json').read_text());rows=[]
for tf in ('5m','15m'):
 bars=[b for m in manifest['datasets'] if m['timeframe']==tf for b in load_dataset(root,m)]
 sim=ResearchSimulation(bars)
 for path in sorted(run.glob(tf+'-*-test.json')):
  old=json.loads(path.read_text())
  params=StrategyParameters(**{k:Decimal(v) for k,v in old['parameters'].items()})
  new=sim.run(start=datetime.fromisoformat(old['start']),end=datetime.fromisoformat(old['end_exclusive']),strategy_ids=set(old['strategy_ids']),parameters=params)
  comparisons={key:new[key]==old[key] for key in old}
  row={'artifact':path.name,'original_sha256':digest(path.read_bytes()),'all_fields_exact':all(comparisons.values()),'different_fields':[k for k,v in comparisons.items() if not v],'net_profit':new['net_profit'],'trades':new['trades'],'fills':len(new['fills'])}
  rows.append(row);print(json.dumps(row),flush=True)
  if not row['all_fields_exact']:raise AssertionError(row)
report={'original_source':manifest['source_fingerprint'],'replay_source':replay_source,'source_unchanged_during_replay':replay_source==source_fingerprint()[0],'deterministic_tolerance':'exact equality across every original artifact field, including fills and equity curves','results':rows}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,indent=2)+'\n')
