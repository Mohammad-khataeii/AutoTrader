"""Exact-commit V4.9.2 primary upgrade; retains all seventeen existing ledgers.

The original seven V4.9 shadow controls retain their manifests, money, strategy
versions and execution fingerprint. No experiment is created, archived or funded.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shlex
import sys
import time
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

from release import verify_source_release
from staging_v49 import (BASE, CORE, PROJECT, CONTROL, LEDGER_INVENTORY, SHADOW_RESUME,
                         api, check_config, dc, flat_portfolio, inventory, run, save,
                         validate_ledgers, verify_private_access)

ROOT=Path(__file__).resolve().parents[1]
PROFILE='4.9.2-paper.1'
LEDGERS=LEDGER_INVENTORY.replace('import asyncio,json','import asyncio,json,hashlib').replace(
    "'runtime_compatibility':compatibility(record['manifest']),",
    "'manifest_hash':hashlib.sha256(json.dumps(record['manifest'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),'runtime_compatibility':compatibility(record['manifest']),")
CONTROL_491=CONTROL.replace('Explicitly authorized V4.9 paper-only Aruba staging release',
                            'Explicitly authorized V4.9.2 primary context upgrade; original shadow controls retained')


def selected_controls(rows):
    selected={r['experiment_id']:r['strategy_id'] for r in rows if not r.get('archived_at')}
    expected={'A3_COST_AWARE_CONTINUATION','B3_STATEFUL_BREAKOUT','E3_ADAPTIVE_RELATIVE_STRENGTH',
              'RAOE_EARLY_RECOVERY','RAOE_TREND_PULLBACK','RAOE_BREAKOUT_RETEST','RAOE_BREAKOUT_CONTINUATION'}
    if len(selected)!=7 or set(selected.values())!=expected:raise ValueError('seven_original_controls_required')
    validate_ledgers(rows,selected)
    return selected


def same_controls(before,after):
    original={r['experiment_id']:r['manifest_hash'] for r in before}
    current={r['experiment_id']:r['manifest_hash'] for r in after}
    if len(original)!=15 or original!=current:raise ValueError('retained_control_manifest_changed')
    return {'status':'PASS','registered_shadow_ledgers':15,'manifest_hashes':original,
            'new_ledgers_created':0,'ledgers_archived':0,'funding_created':False}


def verify_runtime(commit,manifest,images,*,running=False):
    access=verify_private_access();ready=api('/readyz');p=api('/api/personal-paper')
    if (ready.get('live_trading_enabled') is not False or not p.get('runtime_matches')
            or p.get('reconciliation') or p['manifest']['version']!=PROFILE
            or p['manifest']['execution_policy'].get('primary_admission',{}).get('version')!='4.9.1-primary-admission.1'
            or p['portfolio']['risk_state']!='HEALTHY' or not p.get('worker_health',{}).get('fresh')):
        raise ValueError('primary_runtime_or_integrity_verification_failed')
    if running and p['portfolio']['control']!='RUNNING':raise ValueError('primary_not_running')
    intel=api('/api/intelligence')
    if intel.get('status')!='CURRENT' or not intel.get('rows'):raise ValueError('fresh_recorded_scan_required')
    if not all(r.get('primary_admission',{}).get('version')=='4.9.1-primary-admission.1' for r in intel['rows']):
        raise ValueError('new_primary_context_observation_required')
    if not any(r.get('primary_admission',{}).get('inputs',{}).get('ready') is True
               and r['primary_admission'].get('gates',{}).get('primary_context_ready') is True for r in intel['rows']):
        raise ValueError('genuine_aligned_primary_context_required_before_activation')
    learning=api('/api/personal-paper/learning')
    if (learning.get('backend_version')!='4.9.2-rc.2' or learning.get('collector_stale') is not False
            or learning.get('live_authorized') is not False or learning.get('primary_promotion_automatic') is not False
            or learning.get('collection_failure')):raise ValueError('learning_collector_or_isolation_verification_failed')
    containers=inventory()
    for service in CORE:
        expected=images['frontend' if service=='frontend' else 'app']
        if containers['services'][service]['image']!=expected or containers['services'][service]['state']!='running':
            raise ValueError('runtime_image_or_process_mismatch')
    expected={n.removeprefix('src/autotrader/'):v for n,v in manifest['files'].items() if n.startswith('src/autotrader/') and n.endswith('.py')}
    code="import hashlib,json,autotrader;from pathlib import Path;p=Path(autotrader.__file__).parent;print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*.py')}))"
    for service in ('backend','worker','research-worker'):
        if json.loads(dc('exec','-T',service,'python','-c',code))!=expected:raise ValueError('installed_source_hash_mismatch')
    return {'status':'PASS','commit':commit,'profile':PROFILE,'source_fingerprint':manifest['source_fingerprint'],
            'installed_modules':len(expected),'images':images,'containers':containers,'portfolio':p['portfolio'],
            'performance':p['performance'],'worker_health':p['worker_health'],'private_access':access,
            'profile_hash':hashlib.sha256(json.dumps(p['manifest'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
            'live_enabled':False,'reconciliation':[]}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['inspect','activate','verify'])
    parser.add_argument('--commit',required=True);parser.add_argument('--approved-commit');parser.add_argument('--images',type=Path)
    parser.add_argument('--wait-flat-seconds',type=int,default=7200);args=parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}',args.commit) or ROOT!=BASE/'releases'/args.commit:raise ValueError('immutable_staging_release_required')
    verify_source_release(ROOT,ROOT/'release-manifest.json',args.commit);manifest=json.loads((ROOT/'release-manifest.json').read_text())
    if not manifest['version'].startswith('4.9.2'):raise ValueError('v492_release_required')
    readiness=json.loads((ROOT/'docs/evidence/v4_9_2/staging-readiness.json').read_text())
    required={'backend-tests.json','frontend-tests.json','browser-tests.json','linux-tests.json','audit-analysis.json','financial-restore.json','runtime-compatibility.json','restart-recovery.json','learning-tests.json','model-validation.json','deployment-idempotency.json'}
    if readiness.get('status')!='PASS' or readiness.get('source_fingerprint')!=manifest['source_fingerprint'] or not required.issubset(readiness.get('gates',{})):
        raise ValueError('release_gates_incomplete')
    for name,digest in readiness['gates'].items():
        if Path(name).name!=name:raise ValueError('unsafe_gate_path')
        data=(ROOT/'docs/evidence/v4_9_2'/name).read_bytes()
        if (hashlib.sha256(data).hexdigest()!=digest or json.loads(data).get('status')!='PASS'
                or json.loads(data).get('source_fingerprint')!=manifest['source_fingerprint']):raise ValueError('release_gate_hash_failed')
    os.umask(0o077)
    if not 0<=args.wait_flat_seconds<=21600:raise ValueError('bounded_wait_required')
    if args.action=='inspect':print(json.dumps({'inventory':inventory(),'primary':api('/api/personal-paper')['portfolio']}));return
    if args.action=='activate' and args.approved_commit!=args.commit:raise ValueError('exact_release_approval_required')
    if not args.images:raise ValueError('image_binding_required')
    binding=json.loads(args.images.read_text());images={k:binding[k] for k in ('app','frontend')}
    if binding.get('commit')!=args.commit:raise ValueError('image_binding_commit_mismatch')
    for image in images.values():
        if not re.fullmatch('sha256:[a-f0-9]{64}',image):raise ValueError('full_image_id_required')
        meta=json.loads(run(['docker','image','inspect',image]))[0]
        if meta['Architecture']!='amd64' or meta['Os']!='linux' or meta['Config'].get('Labels',{}).get('org.opencontainers.image.revision')!=args.commit:
            raise ValueError('image_platform_or_revision_mismatch')
    expected={n.removeprefix('src/autotrader/'):v for n,v in manifest['files'].items() if n.startswith('src/autotrader/') and n.endswith('.py')}
    code="import hashlib,json,autotrader;from pathlib import Path;p=Path(autotrader.__file__).parent;print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*.py')}))"
    if json.loads(run(['docker','run','--rm','--network','none','--read-only',images['app'],'python','-c',code]))!=expected:raise ValueError('candidate_source_mismatch')
    directory=BASE/'evidence'/('v492-'+args.commit[:12]);directory.mkdir(mode=0o700,exist_ok=True)
    if args.action=='verify':
        result=verify_runtime(args.commit,manifest,images,running=True);save(directory/'verification.json',result);print(json.dumps(result));return
    import fcntl
    lock=(BASE/'ops/v49-release.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (directory/'activation-failed.json').exists():raise ValueError('failed_release_requires_separately_approved_correction')
    # Duplicate activation must never pause a healthy already installed release.
    present=inventory()
    matches=all(present['services'][s]['image']==images['frontend' if s=='frontend' else 'app'] for s in CORE)
    if matches:
        p=api('/api/personal-paper')
        if p['manifest']['version']!=PROFILE:raise ValueError('candidate_images_without_expected_profile_stop_for_diagnostics')
        if p['portfolio']['control']=='RUNNING':
            result=verify_runtime(args.commit,manifest,images,running=True)
            save(directory/'verification.json',result)
            print(json.dumps({**result,'duplicate_invocation':'VERIFIED_WITHOUT_PAUSE_OR_RESTART'}));return
        # Resume only after durable original restore/preservation gates. This
        # branch handles an interruption after cutover and before final resume.
        for name in ('backup-restore.json','all-ledger-backup-restore.json','control-preservation.json','retained-preflight.json'):
            if not (directory/name).is_file():raise ValueError('incomplete_cutover_evidence_preserve_protection')
        for name in ('backup-restore.json','all-ledger-backup-restore.json'):
            proof=json.loads((directory/name).read_text())
            if proof.get('accounts')!=17 or not proof.get('restore_test') or proof.get('restore',{}).get('status')!='PASS':raise ValueError('resume_requires_verified_full_restore')
        rows=api('/api/intelligence/competition')['experiments'];selected=selected_controls(rows)
        current=json.loads(dc('exec','-T','backend','python','-c',LEDGERS))
        # original validation output carries rows through the saved snapshot.
        before_rows=json.loads((directory/'original-ledger-rows.json').read_text())
        same_controls(before_rows,current)
        verify_runtime(args.commit,manifest,images)
        dc('exec','-T','backend','python','-c',SHADOW_RESUME,json.dumps(selected))
        validate_ledgers(api('/api/intelligence/competition')['experiments'],selected,running=True)
        dc('exec','-T','backend','python','-c',CONTROL_491,'resume')
        result=verify_runtime(args.commit,manifest,images,running=True)
        save(directory/'verification.json',result);print(json.dumps({**result,'resumed_existing_cutover':True}));return
    if (directory/'verification.json').exists():raise ValueError('previously_completed_release_changed_do_not_reactivate')

    save(directory/'private-access-before.json',verify_private_access());previous=inventory();save(directory/'previous-containers.json',previous)
    before=api('/api/personal-paper');competition=api('/api/intelligence/competition');selected=selected_controls(competition['experiments'])
    if before.get('reconciliation') or before['portfolio']['risk_state']!='HEALTHY':raise ValueError('existing_financial_health_failed')
    save(directory/'financial-before.json',{'portfolio':before['portfolio'],'performance':before['performance'],'manifest':before['manifest']})
    dc('exec','-T','backend','python','-c',CONTROL_491,'pause_all')
    if not 0<=args.wait_flat_seconds<=21600:raise ValueError('bounded_wait_required')
    deadline=time.monotonic()+args.wait_flat_seconds
    while True:
        paused=api('/api/personal-paper');rows=api('/api/intelligence/competition')['experiments']
        if flat_portfolio(paused['portfolio']) and all(flat_portfolio(r['portfolio']) for r in rows):break
        age=paused.get('worker_health',{}).get('monitor_age_seconds')
        if paused.get('reconciliation') or paused['portfolio']['control']!='PAUSED' or age is None or not -5<=age<=60:raise ValueError('deferred_protection_or_integrity_failed')
        if time.monotonic()>=deadline:raise ValueError('deferred_wait_expired_old_protection_retained')
        status={'phase':'WAITING_FOR_EXISTING_EXIT','observed_at':datetime.now(UTC).isoformat(),'open_positions':paused['performance']['open_positions']}
        save(directory/'deferred-cutover.json',status);print(json.dumps(status),flush=True);time.sleep(15)
    before=paused;old_wrapper=(BASE/'ops/compose').read_text();(directory/'previous-compose').write_text(old_wrapper)
    overrides=directory/'images.json';save(overrides,{'services':{s:{'image':images['frontend' if s=='frontend' else 'app']} for s in (*CORE,'migrate','research-init')}})
    command=['docker','compose','--project-directory',str(ROOT),'-p',PROJECT,'--profile','research','--env-file',str(BASE/'config/.env.staging'),'-f',str(ROOT/'docker-compose.yml'),'-f',str(BASE/'config/compose.staging.yml'),'-f',str(overrides)]
    check_config(command)
    retained=json.loads(run([*command,'run','--rm','--no-deps','backend','python','-c',LEDGERS]));save(directory/'original-ledger-rows.json',retained);save(directory/'retained-preflight.json',validate_ledgers(retained,selected,maintenance=True))
    try:
        print(json.dumps({'phase':'BACKUP_17_AND_PROFILE_REHEARSAL'}),flush=True)
        backup=json.loads(run([sys.executable,str(ROOT/'deploy/staging_backup.py'),'--restore-test','--candidate-image',images['app'],'--rehearse-profile']))
        if (backup.get('accounts')!=17 or not backup.get('restore_test')
                or backup.get('restore',{}).get('status')!='PASS'
                or backup.get('candidate_profile_rehearsal',{}).get('status')!='PASS'
                or backup['candidate_profile_rehearsal'].get('profile')!=PROFILE):raise ValueError('full_retained_restore_required')
        save(directory/'backup-restore.json',backup)
    except Exception:
        save(directory/'activation-failed.json',{'status':'FAILED','phase':'PRE_CUTOVER_BACKUP_RESTORE','at':datetime.now(UTC).isoformat(),'new_release_activated':False,'entries_paused':True,'previous_protection_retained':True,'automatic_database_restore':False});raise
    try:
        dc('stop','worker','research-worker','backend')
        parent=hashlib.sha256(json.dumps(before['manifest'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        run([*command,'run','--rm','--no-deps','backend','python','-c',CONTROL_491,'revision',parent])
        tmp=BASE/'ops/compose.v492.tmp';tmp.write_text('#!/bin/sh\nexec '+shlex.join(command)+' "$@"\n');tmp.chmod(0o700);os.replace(tmp,BASE/'ops/compose')
        run([*command,'up','-d','--wait','--no-build','--no-deps',*[s for s in CORE if s!='worker']])
        current=inventory()
        for service in ('postgres','redis'):
            if any(current['services'][service][k]!=previous['services'][service][k] for k in ('image','volumes')):raise ValueError('retained_volume_or_image_changed')
        after=json.loads(dc('exec','-T','backend','python','-c',LEDGERS));save(directory/'control-preservation.json',same_controls(retained,after));validate_ledgers(after,selected,maintenance=True)
        (BASE/'ops/backup.py').write_text('import runpy\nrunpy.run_path('+repr(str(ROOT/'deploy/staging_backup.py'))+",run_name='__main__')\n");(BASE/'ops/backup.py').chmod(0o600)
        after_backup=json.loads(run([sys.executable,str(ROOT/'deploy/staging_backup.py'),'--restore-test','--candidate-image',images['app']]))
        if after_backup.get('accounts')!=17 or not after_backup.get('restore_test') or after_backup.get('restore',{}).get('status')!='PASS':raise ValueError('all_ledger_restore_before_resume_required')
        save(directory/'all-ledger-backup-restore.json',after_backup)
        run([*command,'up','-d','--wait','--no-build','--no-deps','worker'])
        for attempt in range(36):
            try:verify_runtime(args.commit,manifest,images);break
            except (ValueError,urllib.error.URLError):
                if attempt==35:raise
                time.sleep(5)
        resumed=json.loads(dc('exec','-T','backend','python','-c',SHADOW_RESUME,json.dumps(selected)));save(directory/'original-control-resume.json',resumed)
        validate_ledgers(api('/api/intelligence/competition')['experiments'],selected,running=True)
        dc('exec','-T','backend','python','-c',CONTROL_491,'resume')
        verified=verify_runtime(args.commit,manifest,images,running=True);save(directory/'verification.json',verified);print(json.dumps(verified,indent=2))
    except Exception:
        try:dc('exec','-T','backend','python','-c',CONTROL_491,'pause_all')
        except Exception as error:save(directory/'pause-diagnostic.json',{'error_type':type(error).__name__})
        save(directory/'activation-failed.json',{'status':'FAILED','at':datetime.now(UTC).isoformat(),'inventory':inventory(),'backup':backup['manifest'],'automatic_database_restore':False,'separate_correction_release_required':True})
        try:
            p=api('/api/personal-paper');c=api('/api/intelligence/competition');flat=flat_portfolio(p['portfolio']) and all(flat_portfolio(r['portfolio']) for r in c['experiments'])
        except Exception:flat=False
        if flat:
            (BASE/'ops/compose').write_text(old_wrapper);(BASE/'ops/compose').chmod(0o700)
            try:dc('up','-d','--wait','--no-build','--no-deps',*CORE);save(directory/'safe-image-recovery.json',{'financial_restore':False,'mode':'MONITORING_ONLY','inventory':inventory()})
            except Exception as error:save(directory/'recovery-diagnostic.json',{'error_type':type(error).__name__})
        else:save(directory/'protection-retained.json',{'reason':'open_or_unknown_exposure','automatic_rollback':False})
        raise


if __name__=='__main__':main()
