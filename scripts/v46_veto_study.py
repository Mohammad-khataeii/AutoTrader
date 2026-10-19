"""Conditional diagnostic outcomes, not a causal profitability estimate or policy change."""
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from autotrader.research.data import load_dataset
from autotrader.research.experimental import ExperimentalStrategyEngine
from autotrader.research.panel import build_panel
from autotrader.research.regimes import Regime, classify


def main():
    comparison = json.loads(Path('docs/evidence/v4_6/research-comparison.json').read_text())
    start = datetime.fromisoformat(comparison['preregistered']['split']['test_start'])
    end = datetime.fromisoformat(comparison['preregistered']['end_exclusive'])
    root = Path('.data/research')
    manifests = [m for m in json.loads((root/'catalog.json').read_text())['manifests'] if m['timeframe']=='5m']
    bars = [b for m in manifests for b in load_dataset(root,m) if start-timedelta(days=3)<=datetime.fromisoformat(b.start)<end]
    frames, panel, _ = build_panel(bars, experimental_context=True)
    prices = {t:{c.symbol:c.open for c in cs} for t,cs in frames.items()}
    counts = Counter(); outcomes=defaultdict(list); accepted={}; engine=ExperimentalStrategyEngine()
    for t,context in sorted(panel.items()):
        if t<start: continue
        for symbol,f in context.items():
            if not f.metadata.get('history_contiguous',False): continue
            btc,eth=context.get('BTC-EUR'),context.get('ETH-EUR')
            peers=[p for p in (btc,eth) if p and p.timestamp==f.timestamp]
            c=f.metadata.get('experimental_context',{}); close=D(str(f.metadata.get('last_close',0)))
            previous=D(str(f.metadata.get('previous_close',0))); atr=f.atr or D(0)
            components={'extension':bool(atr>0 and f.ema_21 and (close-f.ema_21)/atr>2),
                'falling_price_volume':bool(close<previous and D(c.get('current_volume','0'))<D(c.get('previous_volume','0'))),
                'bearish_benchmarks':any(p.ema_21 and p.ema_50 and p.ema_21<p.ema_50 for p in peers),
                'spread':(f.spread_bps or 0)>25,
                'adverse_regime':classify(f,btc,eth).regime in {Regime.BEAR,Regime.LIQUIDITY_STRESS,Regime.UNCERTAIN}}
            signals=engine.generate(f,btc,eth)
            primary=any(s.evidence['entry_eligible'] for s in signals if not s.evidence['veto'])
            e2=next(s for s in signals if s.strategy_id.startswith('E2'))
            relative=e2.evidence['relative_return']
            counts['evaluations']+=1
            counts['e2_excess_above_two_percent']+=int(relative!='None' and D(relative)>D('.02'))
            counts['e2_all_primary_conditions']+=int(e2.evidence['entry_eligible'])
            counts['primary_setup_before_d2']+=int(primary)
            if not primary: continue
            future=t+timedelta(minutes=60)
            if symbol not in prices.get(t,{}) or symbol not in prices.get(future,{}):continue
            for name,active in components.items():
                counts['primary_with_'+name]+=int(active)
                if any(v for k,v in components.items() if k!=name): continue
                # A symbol contributes at most one nonoverlapping outcome per component.
                key=(symbol,name)
                if accepted.get(key,start)>t:continue
                accepted[key]=future
                result=prices[future][symbol]/prices[t][symbol]-1-D('.0046')
                outcomes[(name,bool(active))].append(float(result))
    names=('extension','falling_price_volume','bearish_benchmarks','spread','adverse_regime')
    rows=[]
    for name in names:
        groups={str(active):{'nonoverlapping_samples':len(v:=outcomes[(name,active)]), 'mean_net_mark_return':sum(v)/len(v) if v else None} for active in (False,True)}
        rows.append({'component':name,'conditional_other_vetoes_absent':groups,'independent_predictive_value':'NOT_ESTABLISHED'})
    report={'evidence_class':'REUSED_HISTORICAL_CONDITIONAL_DIAGNOSTIC','start':start.isoformat(),'end_exclusive':end.isoformat(),
        'counts':dict(counts),'d2_components':rows,'policy_changed':False,
        'limits':['Observational reused test interval, no causal inference or threshold tuning.',
            'Forward 60-minute open mark, fixed 46bps cost assumption; no stop/target or historical L2, not a strategy PnL.',
            'Nonoverlapping within symbol/component; cross-symbol dependence remains.',
            'Spread is fixed at 10bps in historical panel: independent wide-spread value cannot be identified.',
            'Conditioned strata may be empty or too small; no removal of a safeguard is supported.']}
    Path('docs/evidence/v4_6/veto-conditional-study.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
