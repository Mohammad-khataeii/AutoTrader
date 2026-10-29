"""A primary-only upgrade cannot reset the existing comparison experiments."""
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def staging(monkeypatch):
    monkeypatch.syspath_prepend(str(Path('deploy').resolve()))
    spec=importlib.util.spec_from_file_location('v491_staging_test',Path('deploy/staging_v491.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def rows():
    strategies=['A3_COST_AWARE_CONTINUATION','B3_STATEFUL_BREAKOUT','E3_ADAPTIVE_RELATIVE_STRENGTH',
                'RAOE_EARLY_RECOVERY','RAOE_TREND_PULLBACK','RAOE_BREAKOUT_RETEST','RAOE_BREAKOUT_CONTINUATION']
    return [{'experiment_id':str(i),'strategy_id':strategies[(i-8)%7],'manifest_hash':'original-'+str(i),
             'archived_at':'retained' if i<8 else None,'portfolio':{'control':'STOPPED' if i<8 else 'RUNNING',
             'positions':'0','pending_orders':'0','reserved_cash':'0'},
             'runtime_compatibility':{'compatible':i>=8},'reconciliation':[]} for i in range(15)]


def test_same_control_identity_history_and_missing_control_refusal(staging,monkeypatch):
    r=rows();selected=staging.selected_controls(r);assert len(selected)==7
    assert staging.same_controls(r,copy.deepcopy(r))['funding_created'] is False
    changed=copy.deepcopy(r);changed[-1]['manifest_hash']='modified'
    with pytest.raises(ValueError,match='manifest_changed'):staging.same_controls(r,changed)
    with pytest.raises(ValueError,match='seven_original'):staging.selected_controls(r[:-1])
    # A running process and a new policy label alone cannot validate the feed.
    p={'runtime_matches':True,'reconciliation':[], 'manifest':{'version':staging.PROFILE,
       'execution_policy':{'primary_admission':{'version':'4.9.1-primary-admission.1'}}},
       'portfolio':{'risk_state':'HEALTHY'},'worker_health':{'fresh':True}}
    intel={'status':'CURRENT','rows':[{'primary_admission':{'version':'4.9.1-primary-admission.1',
        'inputs':{'ready':False},'gates':{'primary_context_ready':False}}}]}
    monkeypatch.setattr(staging,'verify_private_access',lambda:{'status':'PASS'})
    monkeypatch.setattr(staging,'api',lambda path:{'live_trading_enabled':False} if path=='/readyz' else p if path=='/api/personal-paper' else intel)
    with pytest.raises(ValueError,match='genuine_aligned_primary_context'):staging.verify_runtime('a'*40,{}, {})


@pytest.mark.parametrize('failure',[None,'pre_backup','post_backup','manifest_changed'])
def test_restore_order_resume_and_manifest_preservation(staging,monkeypatch,tmp_path,failure):
    commit='a'*40;base=tmp_path/'staging';root=base/'releases'/commit;gates=root/'docs/evidence/v4_9_1';gates.mkdir(parents=True)
    (base/'ops').mkdir();(base/'ops/compose').write_text('original compose\n');(base/'evidence').mkdir()
    names=['backend-tests.json','frontend-tests.json','browser-tests.json','linux-tests.json','audit-analysis.json','financial-restore.json','runtime-compatibility.json','restart-recovery.json','api-history-resource.json','restore-startup.json']
    data=b'{"status":"PASS"}'
    for name in names:(gates/name).write_bytes(data)
    (gates/'staging-readiness.json').write_text(json.dumps({'status':'PASS','source_fingerprint':'source','gates':{n:hashlib.sha256(data).hexdigest() for n in names}}))
    manifest={'version':'4.9.1.dev1','source_fingerprint':'source','files':{'src/autotrader/__init__.py':'source-hash'}};(root/'release-manifest.json').write_text(json.dumps(manifest))
    images={'commit':commit,'app':'sha256:'+'b'*64,'frontend':'sha256:'+'c'*64};binding=base/'binding.json';binding.write_text(json.dumps(images))
    old=rows();events=[];p={'portfolio':{'control':'RUNNING','risk_state':'HEALTHY','positions':'0','pending_orders':'0','reserved_cash':'0'},'performance':{'open_positions':0},'manifest':{'version':'4.9.0-paper.1'},'reconciliation':[]}
    inventory={'services':{k:{'image':k,'volumes':['retained-'+k]} for k in ['postgres','redis']}}
    monkeypatch.setattr(staging,'BASE',base);monkeypatch.setattr(staging,'ROOT',root)
    monkeypatch.setattr(staging,'verify_source_release',lambda *a:None);monkeypatch.setattr(staging,'verify_private_access',lambda:{'status':'PASS'})
    monkeypatch.setattr(staging,'check_config',lambda *a:None);monkeypatch.setattr(staging,'inventory',lambda:copy.deepcopy(inventory))
    monkeypatch.setattr(staging,'api',lambda path:copy.deepcopy({'experiments':old} if path.endswith('/competition') else p))
    monkeypatch.setattr(staging,'verify_runtime',lambda *a,**kw:{'status':'PASS'})
    ledger_calls=0
    def run(args,data=None):
        nonlocal ledger_calls
        assert not any('await lab.create(' in str(x) or 'await lab.archive(' in str(x) for x in args)
        if args[:3]==['docker','image','inspect']:return json.dumps([{'Architecture':'amd64','Os':'linux','Config':{'Labels':{'org.opencontainers.image.revision':commit}}}]).encode()
        if args[:2]==['docker','run']:return b'{"__init__.py":"source-hash"}'
        if staging.LEDGERS in args:
            ledger_calls+=1;answer=copy.deepcopy(old)
            if ledger_calls==2 and failure=='manifest_changed':answer[-1]['manifest_hash']='changed'
            return json.dumps(answer).encode()
        if str(root/'deploy/staging_backup.py') in args:
            pre='--rehearse-profile' in args;events.append('pre_restore' if pre else 'post_restore')
            if pre and failure=='pre_backup':raise RuntimeError('restore-failed')
            return json.dumps({'accounts':17,'restore_test':not (not pre and failure=='post_backup'),'restore':{'status':'PASS'},'candidate_profile_rehearsal':{'status':'PASS','profile':staging.PROFILE},'manifest':'retained-backup'}).encode()
        if args[-1]=='worker' and 'up' in args:events.append('start_worker')
        return b'{}'
    def dc(*args):
        if staging.LEDGERS in args:return run(list(args))
        if args[0]=='stop':events.append('stop_previous')
        if staging.SHADOW_RESUME in args:
            assert json.loads(args[-1])=={str(i):old[i]['strategy_id'] for i in range(8,15)}
            for row in old[8:]:row['portfolio']['control']='RUNNING'
            events.append('resume_original_controls');return b'{"status":"PASS"}'
        if staging.CONTROL_491 in args:
            action=args[-1];events.append(action);p['portfolio']['control']='RUNNING' if action=='resume' else 'PAUSED'
            if action=='pause_all':
                for row in old[8:]:row['portfolio']['control']='PAUSED'
        return b'{}'
    monkeypatch.setattr(staging,'run',run);monkeypatch.setattr(staging,'dc',dc)
    monkeypatch.setattr(sys,'argv',['staging_v491.py','activate','--commit',commit,'--approved-commit',commit,'--images',str(binding),'--wait-flat-seconds','0'])
    if failure is None:
        staging.main();assert events.index('pre_restore')<events.index('stop_previous')<events.index('post_restore')<events.index('start_worker')<events.index('resume_original_controls')<events.index('resume')
        assert [r['portfolio']['control'] for r in old[:8]]==['STOPPED']*8
        proof=json.loads((base/'evidence'/('v491-'+commit[:12])/'control-preservation.json').read_text());assert proof['new_ledgers_created']==proof['ledgers_archived']==0
    else:
        with pytest.raises((ValueError,RuntimeError)):staging.main()
        assert p['portfolio']['control']=='PAUSED' and 'resume_original_controls' not in events and 'resume' not in events
        assert (base/'evidence'/('v491-'+commit[:12])/'activation-failed.json').is_file()
        if failure=='pre_backup':assert 'stop_previous' not in events
