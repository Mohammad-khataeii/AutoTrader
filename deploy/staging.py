"""Immutable Aruba staging operations. Never operates on the old production project.

Run on Aruba from an extracted, verified release. Preparation and Linux images
originate locally. Activation requires successful backup, isolated restoration,
profile rehearsal, flat-account checks and an exact image/source binding.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from release import verify_source_release

ROOT=Path(__file__).resolve().parents[1]
BASE=Path('/opt/personal-plan/staging')
PROJECT='autotrader-aruba-test'
CORE=('backend','worker','frontend','research-worker')


def run(args: list[str], data: bytes | None=None) -> bytes:
    result=subprocess.run(args,input=data,capture_output=True,check=False)
    if result.returncode:
        # Compose config and process environments may contain secrets. Never
        # echo their output on failure; diagnostics stay in the private folder.
        errors=BASE/'evidence/v48-operation-errors';errors.mkdir(exist_ok=True,mode=0o700)
        record=errors/(datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')+'.log')
        record.write_bytes(result.stdout+b'\n'+result.stderr);record.chmod(0o600)
        raise RuntimeError('staging_operation_failed:'+Path(args[0]).name+':'+str(result.returncode))
    return result.stdout


def dc(*args: str) -> bytes:
    return run([str(BASE/'ops/compose'),*args])


def api(path: str) -> dict:
    values=dict(line.split('=',1) for line in (BASE/'config/.env.staging').read_text().splitlines() if '=' in line and not line.startswith('#'))
    auth=base64.b64encode((values.get('DASHBOARD_USERNAME','admin')+':'+values['DASHBOARD_PASSWORD']).encode()).decode()
    request=urllib.request.Request('http://127.0.0.1:18000'+path,headers={'Authorization':'Basic '+auth})
    with urllib.request.urlopen(request,timeout=45) as response:return json.load(response)


def inventory() -> dict:
    ids=run(['docker','ps','-aq','--filter','label=com.docker.compose.project='+PROJECT]).decode().split()
    records=json.loads(run(['docker','inspect',*ids])) if ids else []
    services={}
    for r in records:
        if r['Config']['Labels'].get('com.docker.compose.oneoff')=='True':continue
        service=r['Config']['Labels']['com.docker.compose.service']
        services[service]={'image':r['Image'],'state':r['State']['Status'],
            'health':r['State'].get('Health',{}).get('Status'),
            'volumes':sorted(m['Name'] for m in r['Mounts'] if m['Type']=='volume'),
            'ports':r['NetworkSettings']['Ports']}
    return {'project':PROJECT,'services':services,'observed_at':datetime.now(UTC).isoformat()}


def check_config(command: list[str]) -> None:
    configured=json.loads(run([*command,'config','--format','json']))
    if configured.get('name')!=PROJECT:raise ValueError('staging_project_mismatch')
    for service in ('backend','worker','research-worker'):
        e=configured['services'][service]['environment']
        if (e.get('ENVIRONMENT')!='staging' or e.get('LIVE_TRADING_ENABLED')!='false'
                or e.get('PAPER_TRADING_ENABLED')!='true' or e.get('PERSONAL_PAPER_ENABLED')!='true'
                or e.get('APPROVED_STRATEGY_IDS') or not e.get('DATABASE_URL','').endswith('/autotrader_aruba_staging')):
            raise ValueError('staging_paper_authority_mismatch')
    for service in ('postgres','redis'):
        if configured['services'][service].get('ports'):raise ValueError('private_data_port_exposed')
    for service,port in [('backend',18000),('frontend',13000)]:
        ports=configured['services'][service].get('ports',[])
        if len(ports)!=1 or ports[0].get('host_ip')!='127.0.0.1' or int(ports[0]['published'])!=port:
            raise ValueError('existing_loopback_port_mismatch')


CONTROL='''import asyncio,json,sys
from autotrader.config import get_settings
from autotrader.persistence.database import make_engine,make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.personal_paper.service import PersonalPaperService
from autotrader.personal_paper.policy import INITIAL,VERSION,fingerprint
from autotrader.research.data import canonical,digest
async def main():
 s=get_settings();assert s.environment=='staging' and not s.live_trading_enabled
 e=make_engine(s);v=PersonalPaperService(PersistentTradingRepository(make_session_factory(e)),s)
 try:
  r=await v.repository();assert r and r.manifest['official_database']=='autotrader_aruba_staging'
  assert await r.verify_invariants(INITIAL)==[]
  action=sys.argv[1]
  if action in {'pause','pause_all'}:
   await r.set_control('pause')
   if action=='pause_all':
    from autotrader.shadow.lab import ShadowLab
    lab=ShadowLab(v.official,s)
    try:
     for record in await lab.records():
      if record['state'] not in {'CREATING','STOPPED'} and not record.get('archived_at'):await lab.control(record['experiment_id'],'pause')
    finally:await lab.close()
  elif action=='revision':
   assert digest(canonical(r.manifest))==sys.argv[2],'parent_profile_changed'
   r=await v.create_runtime_revision('Explicitly authorized V4.8 paper-only Aruba staging release')
   assert r.manifest['version']==VERSION and r.manifest['runtime_fingerprint']==fingerprint()
  elif action=='resume':
   assert r.manifest['version']==VERSION and r.manifest['runtime_fingerprint']==fingerprint()
   await r.set_control('resume')
  else:raise ValueError('unknown_control_action')
  print(json.dumps({'status':'PASS','action':action,'profile_hash':digest(canonical(r.manifest)),'control':await r.control_state(),'reconciliation':[]}))
 finally:await v.close();await e.dispose()
asyncio.run(main())
'''

SHADOWS='''import asyncio,json
from autotrader.config import get_settings
from autotrader.persistence.database import make_engine,make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.shadow.lab import ShadowLab
from autotrader.raoe import IDENTITIES
from autotrader.opportunity.engine import SUCCESSOR_REGISTRY
async def main():
 s=get_settings();assert s.environment=='staging' and not s.live_trading_enabled
 e=make_engine(s);lab=ShadowLab(PersistentTradingRepository(make_session_factory(e)),s)
 try:
  result=[]
  wanted=[*[x.strategy_id for x in SUCCESSOR_REGISTRY],*IDENTITIES]
  existing=await lab.records()
  remaining=sum(not any(r['manifest']['strategy_id']==identity and r['name']=='V4.8 forward comparison '+identity for r in existing) for identity in wanted)
  assert sum(not r.get('archived_at') for r in existing)+remaining<=8,'forward_comparison_slots_unavailable'
  for identity in [*[x.strategy_id for x in SUCCESSOR_REGISTRY],*IDENTITIES]:
   record=await lab.create('v48-forward-1-'+identity,'V4.8 forward comparison '+identity,identity)
   assert record['reconciliation']==[] and record['manifest']['data_kind']=='LIVE_MARKET_SHADOW'
   await lab.control(record['experiment_id'],'pause')
   result.append({'experiment_id':record['experiment_id'],'strategy_id':identity,'account_id':record['account_id'],'initial_cash':'500'})
  print(json.dumps({'status':'PASS','independent_ledgers':result,'primary_funding_created':False}))
 finally:await lab.close();await e.dispose()
asyncio.run(main())
'''

LEDGER_INVENTORY='''import asyncio,json
from decimal import Decimal
from autotrader.config import get_settings
from autotrader.persistence.database import make_engine,make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.shadow.lab import ShadowLab
from autotrader.shadow.versions import compatibility
async def main():
 s=get_settings();assert s.environment=='staging' and not s.live_trading_enabled
 e=make_engine(s);lab=ShadowLab(PersistentTradingRepository(make_session_factory(e)),s)
 try:
  rows=[]
  for record in await lab.records():
   assert record['state']!='CREATING','incomplete_retained_shadow'
   repo=await lab.repository(record['experiment_id'])
   rows.append({'experiment_id':record['experiment_id'],'strategy_id':record['manifest']['strategy_id'],
    'portfolio':await repo.snapshot(),'runtime_compatibility':compatibility(record['manifest']),
    'reconciliation':await repo.verify_invariants(Decimal(500))})
  print(json.dumps(rows))
 finally:await lab.close();await e.dispose()
asyncio.run(main())
'''

SHADOW_RESUME='''import asyncio,json,sys
from autotrader.config import get_settings
from autotrader.persistence.database import make_engine,make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.shadow.lab import ShadowLab
from autotrader.shadow.versions import compatibility
from autotrader.raoe import IDENTITIES
from autotrader.opportunity.engine import SUCCESSOR_REGISTRY
async def main():
 s=get_settings();assert s.environment=='staging' and not s.live_trading_enabled
 selected=json.loads(sys.argv[1]);assert len(selected)==6
 assert set(selected.values())=={*[x.strategy_id for x in SUCCESSOR_REGISTRY],*IDENTITIES}
 e=make_engine(s);lab=ShadowLab(PersistentTradingRepository(make_session_factory(e)),s)
 try:
  records={r['experiment_id']:r for r in await lab.records()}
  for identity,strategy in selected.items():
   record=records[identity]
   assert record['manifest']['strategy_id']==strategy
   assert record['name']=='V4.8 forward comparison '+strategy
   assert compatibility(record['manifest'])['compatible']
  for identity in selected:await lab.control(identity,'resume')
  print(json.dumps({'status':'PASS','resumed_experiment_ids':list(selected)}))
 finally:await lab.close();await e.dispose()
asyncio.run(main())
'''


def flat_portfolio(portfolio: dict) -> bool:
    """Unknown exposure is never eligible for image recovery or quarantine."""
    return all(Decimal(str(portfolio[key])) == 0
               for key in ('positions', 'pending_orders', 'reserved_cash'))


def validate_ledgers(rows: list[dict], selected: dict[str, str], *, running: bool=False,
                     maintenance: bool=False) -> dict:
    """Retain old frozen identities without authorizing them on a new runtime."""
    identities=[r['experiment_id'] for r in rows]
    if len(set(identities))!=len(identities) or not set(selected).issubset(identities):
        raise ValueError('forward_experiment_identity_missing_or_duplicate')
    quarantined=[]
    for row in rows:
        identity=row['experiment_id'];portfolio=row['portfolio']
        if row.get('reconciliation')!=[]:
            raise ValueError('forward_experiment_reconciliation_failed:'+identity)
        if maintenance and (portfolio['control'] not in {'PAUSED','STOPPED'} or not flat_portfolio(portfolio)):
            raise ValueError('maintenance_requires_all_retained_ledgers_flat_paused:'+identity)
        compatible=row.get('runtime_compatibility',{}).get('compatible') is True
        if identity in selected:
            if row['strategy_id']!=selected[identity] or not compatible:
                raise ValueError('selected_forward_runtime_or_identity_failed:'+identity)
            if running and portfolio['control']!='RUNNING':
                raise ValueError('selected_forward_experiment_not_running:'+identity)
        elif not compatible:
            if portfolio['control'] not in {'PAUSED','STOPPED'} or not flat_portfolio(portfolio):
                raise ValueError('retained_unknown_runtime_requires_flat_paused_account:'+identity)
            quarantined.append(identity)
    return {'status':'PASS','selected_experiments':len(selected),
            'retained_incompatible_paused':quarantined,'registered_experiments':len(rows)}


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value,indent=2)+'\n');path.chmod(0o600)


def verify_runtime(commit: str, manifest: dict, images: dict, *, running: bool=False) -> dict:
    ready=api('/readyz');paper=api('/api/personal-paper')
    if (ready.get('live_trading_enabled') is not False or not paper.get('runtime_matches')
            or paper.get('reconciliation') or paper['manifest']['version']!='4.8.0-paper.1'
            or paper['portfolio']['risk_state']!='HEALTHY'):
        raise ValueError('staging_runtime_or_financial_integrity_failed')
    if not paper.get('worker_health',{}).get('fresh'):raise ValueError('staging_protective_or_scan_heartbeat_stale')
    if running and paper['portfolio']['control']!='RUNNING':raise ValueError('staging_entries_not_running')
    if api('/api/monitoring/summary').get('live_trading_enabled') is not False:raise ValueError('monitoring_projection_failed')
    intelligence=api('/api/intelligence')
    if intelligence['status']!='CURRENT' or not intelligence['rows']:raise ValueError('intelligence_observations_not_current')
    containers=inventory()
    for service in CORE:
        expected=images['frontend' if service=='frontend' else 'app']
        if containers['services'][service]['image']!=expected or containers['services'][service]['state']!='running':
            raise ValueError('staging_image_or_process_mismatch')
    expected={n.removeprefix('src/autotrader/'):v for n,v in manifest['files'].items() if n.startswith('src/autotrader/') and n.endswith('.py')}
    code="import hashlib,json,autotrader;from pathlib import Path;p=Path(autotrader.__file__).parent;print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*.py')}))"
    for service in ('backend','worker','research-worker'):
        if json.loads(dc('exec','-T',service,'python','-c',code))!=expected:raise ValueError('installed_source_hash_mismatch')
    return {'status':'PASS','commit':commit,'source_fingerprint':manifest['source_fingerprint'],
        'installed_modules':len(expected),'images':images,'containers':containers,
        'portfolio':paper['portfolio'],'performance':paper['performance'],'worker_health':paper['worker_health'],
        'profile_hash':hashlib.sha256(json.dumps(paper['manifest'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
        'intelligence_markets':len({r['symbol'] for r in intelligence['rows']}),
        'supported_eur':intelligence['discovery'].get('supported_eur'),'live_enabled':False,'reconciliation':[]}


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['inspect','activate','verify'])
    parser.add_argument('--commit',required=True);parser.add_argument('--images',type=Path)
    parser.add_argument('--wait-flat-seconds',type=int,default=7200)
    args=parser.parse_args()
    if ROOT!=BASE/'releases'/args.commit or not re.fullmatch('[a-f0-9]{40}',args.commit):
        raise ValueError('immutable_aruba_staging_release_path_required')
    verify_source_release(ROOT,ROOT/'release-manifest.json',args.commit)
    manifest=json.loads((ROOT/'release-manifest.json').read_text())
    if not manifest['version'].startswith('4.8.'):raise ValueError('V48_staging_only')
    readiness=json.loads((ROOT/'docs/evidence/v4_8/staging-readiness.json').read_text())
    required={'backend-tests.json','frontend-tests.json','browser-tests.json','linux-tests.json','research-summary.json','staging-correction.json'}
    if readiness.get('status')!='PASS' or readiness.get('source_fingerprint')!=manifest['source_fingerprint'] or not required.issubset(readiness.get('gates',{})):
        raise ValueError('staging_verification_gates_incomplete')
    for name,digest in readiness['gates'].items():
        if Path(name).name!=name:raise ValueError('invalid_staging_gate_path')
        data=(ROOT/'docs/evidence/v4_8'/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=digest or json.loads(data).get('status')!='PASS':
            raise ValueError('staging_gate_hash_or_status_failed')
    os.umask(0o077)
    if args.action=='inspect':
        print(json.dumps({'inventory':inventory(),'primary':api('/api/personal-paper')['portfolio']},indent=2));return
    if not args.images:raise ValueError('immutable_image_binding_required')
    binding=json.loads(args.images.read_text())
    if binding.get('commit')!=args.commit:raise ValueError('image_binding_commit_mismatch')
    images={k:binding[k] for k in ('app','frontend')}
    for image in images.values():
        if not re.fullmatch('sha256:[a-f0-9]{64}',image):raise ValueError('full_image_digest_required')
        config=json.loads(run(['docker','image','inspect',image]))[0]
        if config['Architecture']!='amd64' or config['Os']!='linux':raise ValueError('linux_amd64_image_required')
    expected={n.removeprefix('src/autotrader/'):v for n,v in manifest['files'].items() if n.startswith('src/autotrader/') and n.endswith('.py')}
    code="import hashlib,json,autotrader;from pathlib import Path;p=Path(autotrader.__file__).parent;print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*.py')}))"
    if json.loads(run(['docker','run','--rm','--network','none','--read-only',images['app'],'python','-c',code]))!=expected:
        raise ValueError('candidate_image_source_does_not_match_release')
    for image in images.values():
        metadata=json.loads(run(['docker','image','inspect',image]))[0]
        if metadata['Config'].get('Labels',{}).get('org.opencontainers.image.revision')!=args.commit:
            raise ValueError('candidate_image_revision_label_mismatch')
    directory=BASE/'evidence'/('v48-'+args.commit[:12]);directory.mkdir(exist_ok=True,mode=0o700)
    if args.action=='verify':
        result=verify_runtime(args.commit,manifest,images,running=True);save(directory/'verification.json',result)
        print(json.dumps(result,indent=2));return
    lock=(BASE/'ops/v48-release.lock').open('a')
    import fcntl
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    previous=inventory();save(directory/'previous-containers.json',previous)
    before=api('/api/personal-paper');save(directory/'financial-before.json',{'portfolio':before['portfolio'],'performance':before['performance'],'manifest':before['manifest']})
    if before.get('reconciliation') or before['portfolio']['risk_state']!='HEALTHY':raise ValueError('existing_financial_health_failed')
    # Never force-sell to cut over. Existing protection keeps running while new
    # entries are paused; a nonflat account leaves this release deferred.
    dc('exec','-T','backend','python','-c',CONTROL,'pause')
    paused=api('/api/personal-paper')
    if not 0<=args.wait_flat_seconds<=21600:raise ValueError('bounded_deferred_cutover_wait_required')
    deadline=time.monotonic()+args.wait_flat_seconds
    while paused['performance']['open_positions'] or any(o['status'] in {'PENDING','ACCEPTED'} for o in paused['orders']):
        status={'phase':'WAITING_FOR_EXISTING_PLAN_EXIT','open_positions':paused['performance']['open_positions'],
            'control':paused['portfolio']['control'],'protective_monitor_age_seconds':paused.get('worker_health',{}).get('monitor_age_seconds'),
            'observed_at':datetime.now(UTC).isoformat()}
        print(json.dumps(status),flush=True);save(directory/'deferred-cutover.json',status)
        if paused.get('reconciliation') or paused['portfolio']['control']!='PAUSED':raise ValueError('deferred_cutover_financial_or_control_failure')
        age=paused.get('worker_health',{}).get('monitor_age_seconds')
        if age is None or age>60 or age < -5:raise ValueError('deferred_cutover_protection_not_fresh')
        if time.monotonic()>=deadline:raise ValueError('deferred_cutover_timeout_old_protection_retained')
        time.sleep(15)
        paused=api('/api/personal-paper')
    before=paused
    save(directory/'financial-paused-flat.json',{'portfolio':before['portfolio'],'performance':before['performance'],'manifest':before['manifest']})
    old_wrapper=(BASE/'ops/compose').read_text();(directory/'previous-compose').write_text(old_wrapper)
    overrides=directory/'images.json'
    save(overrides,{'services':{s:{'image':images['frontend' if s=='frontend' else 'app']} for s in (*CORE,'migrate','research-init')}})
    command=['docker','compose','--project-directory',str(ROOT),'-p',PROJECT,'--profile','research','--env-file',str(BASE/'config/.env.staging'),
        '-f',str(ROOT/'docker-compose.yml'),'-f',str(BASE/'config/compose.staging.yml'),'-f',str(overrides)]
    check_config(command)
    retained=json.loads(run([*command,'run','--rm','--no-deps','backend','python','-c',LEDGER_INVENTORY]))
    save(directory/'retained-ledger-preflight.json',validate_ledgers(retained,{},maintenance=True))
    print(json.dumps({'phase':'FLAT_ACCOUNT_BACKUP_AND_RESTORE_REHEARSAL'}),flush=True)
    backup=json.loads(run([sys.executable,str(ROOT/'deploy/staging_backup.py'),'--restore-test','--candidate-image',images['app'],'--rehearse-profile']))
    if not backup.get('restore_test') or backup.get('candidate_profile_rehearsal',{}).get('status')!='PASS':
        raise ValueError('backup_restore_or_candidate_rehearsal_failed')
    save(directory/'backup-restore.json',backup)
    try:
        dc('stop','worker','research-worker','backend')
        # The same PostgreSQL image/volume is retained. Recreate only to apply
        # the corrected DB-aware healthcheck; no migration or data restore.
        run([*command,'up','-d','--wait','--no-build','--no-deps','postgres'])
        run([*command,'run','--rm','--no-deps','backend','python','-c',CONTROL,'revision',hashlib.sha256(json.dumps(before['manifest'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()])
        wrapper='#!/bin/sh\nexec '+shlex.join(command)+' "$@"\n'
        temporary=BASE/'ops/compose.v48.tmp';temporary.write_text(wrapper);temporary.chmod(0o700);os.replace(temporary,BASE/'ops/compose')
        # Every retained ledger is flat and paused. Keep the worker stopped
        # until all new ledgers are paused and their restore proof passes.
        run([*command,'up','-d','--wait','--no-build','--no-deps',*[s for s in CORE if s!='worker']])
        current=inventory()
        for service in ('postgres','redis'):
            if current['services'][service]['image']!=previous['services'][service]['image']:
                raise ValueError('retained_database_or_cache_image_changed')
            if current['services'][service]['volumes']!=previous['services'][service]['volumes']:
                raise ValueError('financial_volume_identity_changed')
        shadows=json.loads(dc('exec','-T','backend','python','-c',SHADOWS));save(directory/'shadow-provisioning.json',shadows)
        selected={r['experiment_id']:r['strategy_id'] for r in shadows['independent_ledgers']}
        if len(selected)!=6 or len(set(selected.values()))!=6:raise ValueError('six_distinct_forward_experiments_required')
        competition=api('/api/intelligence/competition')
        save(directory/'forward-ledger-validation.json',validate_ledgers(competition['experiments'],selected,maintenance=True))
        # Scheduled backups must cover the new separate ledgers as well.
        backup_wrapper="import runpy\nrunpy.run_path("+repr(str(ROOT/'deploy/staging_backup.py'))+",run_name='__main__')\n"
        (BASE/'ops/backup.py').write_text(backup_wrapper);(BASE/'ops/backup.py').chmod(0o600)
        after_backup=json.loads(run([sys.executable,str(ROOT/'deploy/staging_backup.py'),'--restore-test','--candidate-image',images['app']]))
        if not after_backup.get('restore_test') or after_backup.get('restore',{}).get('status')!='PASS':
            raise ValueError('all_ledger_backup_restore_required_before_resume')
        save(directory/'all-ledger-backup-restore.json',after_backup)
        run([*command,'up','-d','--wait','--no-build','--no-deps','worker'])
        # Wait for genuine new-loop protection and observation evidence.
        for attempt in range(30):
            try:
                verified=verify_runtime(args.commit,manifest,images)
                break
            except (ValueError,urllib.error.URLError):
                if attempt==29:raise
                time.sleep(5)
        resumed=json.loads(dc('exec','-T','backend','python','-c',SHADOW_RESUME,json.dumps(selected)))
        save(directory/'forward-ledger-resume.json',resumed)
        save(directory/'forward-ledger-running.json',validate_ledgers(api('/api/intelligence/competition')['experiments'],selected,running=True))
        dc('exec','-T','backend','python','-c',CONTROL,'resume')
        verified=verify_runtime(args.commit,manifest,images,running=True)
        save(directory/'verification.json',verified)
        print(json.dumps(verified,indent=2))
    except Exception:
        # Do not blindly roll financial data backward. Keep diagnostics and
        # pause entries; protection remains available on whichever worker is up.
        try:dc('exec','-T','backend','python','-c',CONTROL,'pause_all')
        except Exception as pause_error:
            save(directory/'pause-diagnostic.json',{'error_type':type(pause_error).__name__})
        save(directory/'activation-failed.json',{'status':'FAILED','at':datetime.now(UTC).isoformat(),'inventory':inventory(),
            'backup':backup['manifest'],'previous_compose':str(directory/'previous-compose'),
            'automatic_database_restore':False,'separate_correction_release_required':True})
        # Image recovery is allowed only when all ledgers are known flat.
        # Unknown/open shadow exposure retains the candidate protection loop.
        try:
            paper=api('/api/personal-paper');competition=api('/api/intelligence/competition')
            flat=flat_portfolio(paper['portfolio']) and all(flat_portfolio(r['portfolio']) for r in competition['experiments'])
        except Exception:
            flat=False
        if flat:
            (BASE/'ops/compose').write_text(old_wrapper);(BASE/'ops/compose').chmod(0o700)
            try:
                dc('up','-d','--wait','--no-build','--no-deps',*CORE)
                save(directory/'safe-image-recovery.json',{'status':'MONITORING_ONLY','financial_restore':False,'inventory':inventory()})
            except Exception as recovery_error:
                save(directory/'recovery-diagnostic.json',{'error_type':type(recovery_error).__name__,'manual_recovery_required':True})
        else:
            save(directory/'protection-retained.json',{'automatic_rollback':False,'reason':'open_or_unknown_exposure','entries_paused':True})
        raise


if __name__=='__main__':main()
