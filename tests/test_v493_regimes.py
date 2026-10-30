"""Completed market interpretation stays causal and isolated from admission."""
import copy
from dataclasses import replace
from decimal import Decimal as D

from autotrader.learning import regimes as r
from test_v491_admission import CUTOFF, bars


def test_regime_future_invariance_and_missing_higher_context_caution():
    own=bars('TEST-EUR',1152);peers={s:bars(s,1152) for s in ('BTC-EUR','ETH-EUR')}
    original=r.assess(own,peers,CUTOFF)
    future=replace(own[-1],timestamp=CUTOFF,close=D(10000),high=D(10001))
    assert r.assess([*own,future],peers,CUTOFF)==original
    assert original['execution_authorized'] is False and original['primary_policy_changed'] is False
    assert all(k in original['timeframes'] for k in ('5','15','60','240'))
    short=r.assess(bars('TEST-EUR',300),{s:bars(s,300) for s in peers},CUTOFF)
    assert short['timeframes']['240']['trend']=='UNKNOWN'
    assert short['state']!='BULLISH_CONTINUATION'
    peers['ETH-EUR']=peers['ETH-EUR'][:-1]
    assert r.assess(own,peers,CUTOFF)['state']=='UNKNOWN'
    broken=own[:-1]+[replace(own[-1],close=D('NaN'))]
    assert r.assess(broken,peers,CUTOFF)['state']=='UNKNOWN'


def test_relief_requires_confirmation_before_research_recovery(monkeypatch):
    own=bars('TEST-EUR',1152);peers={s:bars(s,1152) for s in ('BTC-EUR','ETH-EUR')}
    own[-1]=replace(own[-1],volume=D(150))
    def frame(candles,minutes,as_of):
        peer=candles and candles[0].symbol in peers
        return {'unknown_reason':None,'trend':'BEARISH' if peer and minutes==60 else 'BULLISH',
                'close':'110','previous_close':'109','ema21':'108','ema9':'109',
                'ema9_slope_atr':'.2','extension_atr':'.5','bearish_persistence':0}
    monkeypatch.setattr(r,'frame',frame)
    state=r.assess(own,peers,CUTOFF)
    # Equal asset/benchmark returns do not establish relative strength.
    assert state['state']=='RELIEF_RALLY' and not state['transition_confirmation']
    own[-1]=replace(own[-1],close=own[-1].close+D('.01'),high=own[-1].high+D('.01'))
    state=r.assess(own,peers,CUTOFF)
    assert state['state']=='EMERGING_RECOVERY' and state['hourly_joint_bearish']
    gates={k:True for k in ('primary_context_ready','primary_current_candle','primary_local_reclaim','primary_recovery_reclaim')}
    e={'entry_eligible':False,'technical_eligible':True,'economic_eligible':True,'primary_admission':{'gates':gates}}
    before=copy.deepcopy(e);hyp=r.shadow_hypotheses(e,state)
    assert hyp['confirmed_transition'] and not hyp['primary_execution_authorized'] and e==before
    e['economic_eligible']=False
    assert not r.shadow_hypotheses(e,state)['confirmed_transition']


def test_observation_bridge_rejects_strategy_or_financial_source_mutation(tmp_path,monkeypatch):
    import shutil

    from autotrader.shadow import versions
    parent=versions.ROOT;copy_root=tmp_path/'autotrader';shutil.copytree(parent,copy_root,ignore=shutil.ignore_patterns('__pycache__'))
    monkeypatch.setattr(versions,'ROOT',copy_root);versions.verify_observation_bridge()
    target=copy_root/'execution/pricing.py';target.write_text(target.read_text()+'\n# changed\n')
    import pytest
    with pytest.raises(ValueError,match='source_integrity'):versions.verify_observation_bridge()
    assert versions.generation({'execution_fingerprint':versions.V492_EXECUTION}) is None
