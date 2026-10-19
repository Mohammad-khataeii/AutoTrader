"""New entry research must retain causal timing and count unfilled watches."""
import importlib.util
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from autotrader.research.data import HistoricalBar
from autotrader.research.simulation import ResearchSimulation
from v46_support import successor_frame


def test_successor_research_prefix_is_causal_and_limit_watches_can_expire():
    observation=successor_frame('A3_COST_AWARE_CONTINUATION')
    bars=[]
    for symbol,market in observation['markets'].items():
        for candle in market['candles']:
            bars.append(HistoricalBar('SYNTHETIC-CAUSAL',symbol,symbol.split('-')[0],'EUR',candle['timestamp'],'5m',
                candle['open'],candle['high'],candle['low'],candle['close'],candle['volume'],candle['timestamp'],()))
        last=bars[-1]
        for i in range(1,7):
            stamp=(datetime.fromisoformat(last.start)+timedelta(minutes=5*i)).isoformat()
            bars.append(replace(last,start=stamp,open='129.2',high='129.3',low='129.15',close='129.2',volume='1000'))
    start=datetime.fromisoformat(observation['markets']['BTC-EUR']['candles'][-1]['timestamp'])+timedelta(minutes=5)
    cutoff=start+timedelta(minutes=15)
    whole=ResearchSimulation(bars,successor=True)
    prefix=ResearchSimulation([b for b in bars if datetime.fromisoformat(b.start)<cutoff],successor=True)
    options={'start':start,'end':cutoff,'strategy_ids':{'A3_COST_AWARE_CONTINUATION'}}
    assert whole.run(**options)==prefix.run(**options)
    immediate=whole.run(start=start,end=start+timedelta(minutes=30),strategy_ids=options['strategy_ids'])
    assert immediate['opportunity_counts']['actual_simulated_buy_fills']>0
    conditional=whole.run(start=start,end=start+timedelta(minutes=30),strategy_ids=options['strategy_ids'],entry_method='BID_IOC')
    assert conditional['opportunity_counts']['conditional_entry_watches']>0
    assert conditional['opportunity_counts']['missed_fills']>0
    assert not [f for f in conditional['fills'] if f['side']=='BUY']


def test_v46_activation_evidence_is_source_bound_and_does_not_authorize_deployment(tmp_path):
    spec=importlib.util.spec_from_file_location('release_v46',Path('deploy/release.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    (tmp_path/'pyproject.toml').write_text('[project]\nversion="4.6.0"\n')
    source=tmp_path/'src/autotrader';source.mkdir(parents=True);(source/'__init__.py').write_text('VERSION="synthetic"\n')
    folder=tmp_path/'docs/evidence/v4_6';folder.mkdir(parents=True)
    evidence={}
    for name in ('tests.json','runtime-compatibility.json','container-tests.json','financial-restore.json'):
        path=folder/name;path.write_text('{"status":"PASS"}');evidence[name]=module.digest(path.read_bytes())
    readiness={'recommendation':'READY','engineering_evidence':evidence,'application_source_fingerprint':module.digest(module.canonical({'__init__.py':module.digest((source/'__init__.py').read_bytes())}))}
    (folder/'deployment-readiness.json').write_text(json.dumps(readiness))
    assert module.verify_release_preflight(tmp_path)['deployment_authorized'] is False
    (source/'__init__.py').write_text('# changed\n')
    with pytest.raises(ValueError,match='different application source'):module.verify_release_preflight(tmp_path)
