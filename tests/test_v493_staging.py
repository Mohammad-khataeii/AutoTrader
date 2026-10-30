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
    spec=importlib.util.spec_from_file_location('v493_staging_test',Path('deploy/staging_v493.py'))
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


@pytest.mark.parametrize('failure',[None,'pre_backup','pre_restore_status','post_backup','manifest_changed'])
def test_restore_order_resume_and_manifest_preservation(staging,monkeypatch,tmp_path,failure):
    commit='a'*40;base=tmp_path/'staging';root=base/'releases'/commit;gates=root/'docs/evidence/v4_9_3';gates.mkdir(parents=True)
    (base/'ops').mkdir();(base/'ops/compose').write_text('original compose\n');(base/'evidence').mkdir()
    names=['backend-tests.json','frontend-tests.json','browser-tests.json','linux-tests.json','audit-analysis.json','financial-restore.json','runtime-compatibility.json','restart-recovery.json','learning-tests.json','model-validation.json','deployment-idempotency.json']
    data=b'{"status":"PASS","source_fingerprint":"source"}'
    for name in names:(gates/name).write_bytes(data)
    (gates/'staging-readiness.json').write_text(json.dumps({'status':'PASS','source_fingerprint':'source','gates':{n:hashlib.sha256(data).hexdigest() for n in names}}))
    manifest={'version':'4.9.3rc1','source_fingerprint':'source','files':{'src/autotrader/__init__.py':'source-hash'}};(root/'release-manifest.json').write_text(json.dumps(manifest))
    images={'commit':commit,'app':'sha256:'+'b'*64,'frontend':'sha256:'+'c'*64};binding=base/'binding.json';binding.write_text(json.dumps(images))
    import task_authorization
    monkeypatch.setattr(task_authorization,'bind',lambda *a:{'task_id':task_authorization.TASK,'commit':commit,'test_only':'fault_matrix'})
    policy=root/'deploy/authorizations/v493-once.json';policy.parent.mkdir(parents=True);policy.write_text(json.dumps({'task_id':task_authorization.TASK}))
    monkeypatch.setattr(staging,'compare_financial_backups',lambda *a:{'status':'PASS','databases':17,'identical_financial_table_seals':170})
    old=rows();events=[];p={'portfolio':{'control':'RUNNING','risk_state':'HEALTHY','positions':'0','pending_orders':'0','reserved_cash':'0'},'performance':{'open_positions':0},'manifest':{'version':'4.9.0-paper.1'},'reconciliation':[]}
    inventory={'services':{k:{'image':k,'volumes':['retained-'+k]} for k in ['postgres','redis',*staging.CORE]}}
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
            return json.dumps({'accounts':17,'restore_test':not (not pre and failure=='post_backup'),'restore':{'status':'FAIL' if pre and failure=='pre_restore_status' else 'PASS'},'candidate_profile_rehearsal':{'status':'PASS','profile':staging.PROFILE},'manifest':'retained-backup'}).encode()
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
    monkeypatch.setattr(sys,'argv',['staging_v493.py','activate','--commit',commit,'--task-authorization','--images',str(binding),'--wait-flat-seconds','0'])
    if failure is None:
        staging.main();assert events.index('pre_restore')<events.index('stop_previous')<events.index('post_restore')<events.index('start_worker')<events.index('resume_original_controls')<events.index('resume')
        assert [r['portfolio']['control'] for r in old[:8]]==['STOPPED']*8
        claim=json.loads((base/'ops/authorization-autotrader-v493-2026-10-30.json').read_text())
        assert claim['source_manifest_sha256']==hashlib.sha256((root/'release-manifest.json').read_bytes()).hexdigest()
        assert len(claim['engineering_verification_hashes'])==11
        assert claim['financial_verification_hashes']['stage_a_seventeen_ledger_restore']==hashlib.sha256(data).hexdigest()
        # Re-running activation of the installed release performs only read-only
        # verification, even when there are newer open positions.
        installed={'services':{s:{'image':images['frontend' if s=='frontend' else 'app']} for s in staging.CORE}}
        monkeypatch.setattr(staging,'inventory',lambda:copy.deepcopy(installed))
        p['manifest']['version']=staging.PROFILE
        p['portfolio']['positions']='1'
        events.clear()
        staging.main()
        assert events==[], 'Duplicate activation must not pause or restart a healthy account'

        # Resume a paused, already installed cutover using durable restore proof.
        # A failed restore proof must prevent even the first resume operation.
        evidence=base/'evidence'/('v493-'+commit[:12])
        proof_path=evidence/'all-ledger-backup-restore.json';original_proof=proof_path.read_text()
        proof=json.loads(original_proof);proof['restore']['status']='FAIL'
        proof_path.write_text(json.dumps(proof));p['portfolio']['control']='PAUSED'
        for row in old[8:]:row['portfolio']['control']='PAUSED'
        with pytest.raises(ValueError,match='resume_requires_verified_full_restore'):staging.main()
        assert events==[]
        proof_path.write_text(original_proof)
        financial_path=evidence/'financial-preservation.json';original_financial=financial_path.read_text()
        financial_path.write_text(json.dumps({'status':'FAIL','databases':17,'identical_financial_table_seals':170}))
        with pytest.raises(ValueError,match='resume_requires_verified_financial_preservation'):staging.main()
        assert events==[]
        financial_path.write_text(original_financial)
        staging.main()
        assert events==['resume_original_controls','resume']
        events.clear()
        monkeypatch.setattr(staging,'inventory',lambda:copy.deepcopy(inventory))
        with pytest.raises(ValueError,match='previously_completed_release_changed'):staging.main()
        assert events==[]

        proof=json.loads((base/'evidence'/('v493-'+commit[:12])/'control-preservation.json').read_text());assert proof['new_ledgers_created']==proof['ledgers_archived']==0
    else:
        with pytest.raises((ValueError,RuntimeError)):staging.main()
        assert p['portfolio']['control']=='PAUSED' and 'resume_original_controls' not in events and 'resume' not in events
        assert (base/'evidence'/('v493-'+commit[:12])/'activation-failed.json').is_file()
        if failure in {'pre_backup','pre_restore_status'}:assert 'stop_previous' not in events


def test_financial_seals_must_match_all_seventeen_ledgers(staging,monkeypatch,tmp_path):
    monkeypatch.setattr(staging,'BASE',tmp_path)
    tables=['balances','financial_journal','orders','fills','positions','capital_reservations','exit_intents','exit_targets','exit_plans','order_transitions']
    rows=[{'database':'db-'+str(i),'financial_seal':{t:{'rows':i,'sha256':str(i)*64} for t in tables}} for i in range(17)]
    root=tmp_path/'backups';root.mkdir();a=root/'before.json';b=root/'after.json'
    a.write_text(json.dumps({'databases':rows}));b.write_bytes(a.read_bytes())
    assert staging.compare_financial_backups({'manifest':str(a)},{'manifest':str(b)})['identical_financial_table_seals']==170
    changed=copy.deepcopy(rows);changed[-1]['financial_seal']['fills']['rows']+=1
    b.write_text(json.dumps({'databases':changed}))
    with pytest.raises(ValueError,match='financial_history_changed'):staging.compare_financial_backups({'manifest':str(a)},{'manifest':str(b)})
    with pytest.raises(ValueError,match='scope_failed'):staging.compare_financial_backups({'manifest':str(tmp_path/'outside.json')},{'manifest':str(b)})
