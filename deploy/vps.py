"""Project-scoped deployment operations. Never removes volumes or other projects."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT=Path(__file__).resolve().parents[1]
CORE=['backend','worker','frontend']


def database_state(dc) -> str:
    """A running PostgreSQL container is not proof of a migrated database."""
    probe=dc('exec','-T','postgres','psql','-U','autotrader','-d','autotrader','-Atc',
        "SELECT json_build_object('tables',(SELECT count(*) FROM information_schema.tables WHERE table_schema='public'),'version_table',to_regclass('public.alembic_version') IS NOT NULL)")
    info=json.loads(probe)
    if info['tables']==0:
        return 'FRESH'
    if not info['version_table']:
        raise RuntimeError('Unversioned nonempty database: automatic initialization refused.')
    revision=dc('exec','-T','postgres','psql','-U','autotrader','-d','autotrader','-Atc','SELECT version_num FROM alembic_version').decode().strip()
    if not revision:
        raise RuntimeError('Nonempty database has no Alembic revision; automatic initialization refused.')
    counts=json.loads(dc('exec','-T','postgres','psql','-U','autotrader','-d','autotrader','-Atc',
        "SELECT json_build_object('accounts',(SELECT count(*) FROM accounts),'journal',(SELECT count(*) FROM financial_journal),'balances',(SELECT count(*) FROM balances),'orders',(SELECT count(*) FROM orders),'fills',(SELECT count(*) FROM fills),'positions',(SELECT count(*) FROM positions),'reservations',(SELECT count(*) FROM capital_reservations))"))
    return 'SCHEMA_ONLY' if not any(counts.values()) else 'POPULATED'


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['inventory','sync-research','build','up','verify','logs','stop','backup','restore','upgrade','rollback'])
    parser.add_argument('--project',default='autotrader-v41')
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env')
    parser.add_argument('--backup',type=Path,help='Complete nine-database backup-set.json')
    parser.add_argument('--candidate-image',help='Immutable candidate image ID for isolated restore')
    parser.add_argument('--rollback-image',help='Recorded known-good image ID for isolated rollback proof')
    parser.add_argument('--release',type=Path,help='Previously verified release.json for image rollback')
    parser.add_argument('--release-commit',help='Full approved immutable Git commit; required for production source operations')
    parser.add_argument('--release-manifest',type=Path,help='Verified release-manifest.json accompanying that commit')
    args=parser.parse_args()
    if not re.fullmatch(r'autotrader-[a-z0-9][a-z0-9-]{0,45}',args.project):
        parser.error('An independent autotrader-* Compose project is required.')
    if args.action=='inventory':
        subprocess.run(['docker','ps','--format','{{.Names}} | {{.Image}} | {{.Ports}}'],check=True)
        return
    if args.project=='autotrader-v41' and args.action in {'build','up','upgrade','rollback'}:
        if not args.release_commit or not args.release_manifest:
            parser.error('Production source operations require --release-commit and --release-manifest after explicit release approval.')
        import importlib.util
        spec=importlib.util.spec_from_file_location('autotrader_release',ROOT/'deploy'/'release.py')
        release_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(release_module)
        verified=release_module.verify_source_release(ROOT,args.release_manifest.resolve(),args.release_commit)
        if args.action in {'up','upgrade'}:
            release_module.verify_release_preflight(ROOT)
        print('Verified immutable release: '+verified['commit'])
    env_file=args.env_file.resolve()
    private=ROOT/'.tools'/'deployments'/args.project
    private.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(private,0o700)
    compose=['docker','compose','--project-directory',str(ROOT),'-f',str(ROOT/'docker-compose.yml'),'-p',args.project,'--env-file',str(env_file)]
    def run(command: list[str],data: bytes | None = None) -> bytes:
        result=subprocess.run(command,input=data,capture_output=True,cwd=ROOT,check=False)
        if result.returncode:
            raise RuntimeError('Project operation failed: '+result.stderr.decode(errors='replace')[-2500:])
        return result.stdout
    def dc(*parts: str,data: bytes | None = None) -> bytes:
        return run([*compose,*parts],data)
    values=dict(line.split('=',1) for line in env_file.read_text().splitlines() if '=' in line and not line.startswith('#'))
    for key in ('DASHBOARD_PASSWORD','POSTGRES_PASSWORD'):
        if len(values.get(key,''))<20 or 'REPLACE' in values.get(key,''):
            raise ValueError('Generate strong private deployment secrets before operating.')
    dc('config','--quiet')
    def persist_tag(tag: str) -> None:
        lines=env_file.read_text().splitlines()
        lines=[line for line in lines if not line.startswith('AUTOTRADER_IMAGE_TAG=')]
        lines.append('AUTOTRADER_IMAGE_TAG='+tag)
        temporary=env_file.with_suffix('.private-tmp')
        descriptor=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(descriptor,'w') as stream:
            stream.write('\n'.join(lines)+'\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,env_file)
    def verify() -> dict:
        settings=json.loads(dc('config','--format','json'))
        for service in ('postgres','redis'):
            if settings['services'][service].get('ports'):
                raise RuntimeError('Database/cache ports must remain private.')
        for service in ('backend','frontend'):
            if any(p.get('host_ip')!='127.0.0.1' for p in settings['services'][service].get('ports',[])):
                raise RuntimeError('Only loopback application publishing is permitted.')
        port=int(values.get('API_PORT','8000'))
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',auth=(values.get('DASHBOARD_USERNAME','admin'),values['DASHBOARD_PASSWORD']),timeout=15) as client:
            response=client.get('/readyz');response.raise_for_status()
            overview=client.get('/api/overview');overview.raise_for_status()
            health=client.get('/api/system');health.raise_for_status()
            result={'ready':response.json(),'version':overview.json().get('application_version'),
                'portfolio':overview.json()['portfolio'],'health':health.json()}
            if result['health']['postgresql']!='ok' or result['health']['reconciliation']['problems']:
                raise RuntimeError('Post-deployment database reconciliation failed.')
            if result['health']['worker']!='ok' or result['health'].get('operational_state') in {'SYSTEM_ERROR','RECOVERY_REQUIRED'}:
                raise RuntimeError('Post-deployment worker operational verification failed.')
        ids=dc('ps','-q').decode().split()
        result['containers']=[{'name':r['Name'],'image':r['Image'],'state':r['State']['Status'],
            'health':r['State'].get('Health',{}).get('Status'),'ports':r['NetworkSettings']['Ports']}
            for r in json.loads(run(['docker','inspect',*ids]))] if ids else []
        result['project']=args.project
        return result
    import importlib.util
    spec = importlib.util.spec_from_file_location('financial_set', ROOT/'deploy'/'financial_set.py')
    financial_set = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(financial_set)

    def backup() -> Path:
        manifest = financial_set.backup_all(dc, private)
        print('Verified complete retained database backup set: ' + str(manifest))
        return manifest

    def restore(path: Path, rollback_image: str | None = None) -> dict:
        configured = json.loads(dc('config','--format','json'))
        image = args.candidate_image or configured['services']['backend']['image']
        postgres_id = dc('ps','-q','postgres').decode().strip()
        postgres_image = run(['docker','inspect','--format','{{.Image}}',postgres_id]).decode().strip()
        return financial_set.restore_isolated(path.resolve(), image, postgres_image,
                                              rollback_image or args.rollback_image)

    if args.action=='sync-research':
        code="""from pathlib import Path
import json,os
from autotrader.research.seed import main
from autotrader.research.artifacts import load_latest,source_fingerprint
from autotrader.research.data import atomic_write,canonical,load_dataset
main()
report=load_latest(Path('/seed'))
assert report and report['source_fingerprint']==source_fingerprint()[0], 'Finish matching source research before publishing it'
catalog=json.loads(Path('/seed/catalog.json').read_bytes())
for manifest in catalog['manifests']: load_dataset(Path('/app/research'),manifest)
atomic_write(Path('/app/research/catalog.json'),canonical(catalog))
atomic_write(Path('/app/research/latest-run.json'),Path('/seed/latest-run.json').read_bytes())
for name in ('catalog.json','latest-run.json'): os.chown(Path('/app/research')/name,10001,10001)
print('Published verified matching-source research catalog and report pointer.')
"""
        print(dc('--profile','bootstrap','run','--rm','--no-deps','research-init','python','-c',code).decode())
    elif args.action=='build':
        dc('build','backend','frontend','postgres','redis')
    elif args.action=='up':
        if args.project=='autotrader-v41':
            raise RuntimeError('Production retains nine existing financial domains; use the approved upgrade workflow, never fresh initialization.')
        dc('up','-d','--wait','--no-build','postgres','redis')
        state=database_state(dc)
        if state=='POPULATED':
            raise RuntimeError('Populated deployments require upgrade with coordinated writer interruption and a complete isolated restore.')
        dc('run','--rm','--no-deps','migrate')
        dc('--profile','bootstrap','run','--rm','--no-deps','research-init')
        dc('up','-d','--wait','--no-build','--no-deps',*CORE)
        print(json.dumps(verify(),indent=2))
    elif args.action=='verify':
        result=verify();(private/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    elif args.action=='logs':
        print(dc('logs','--tail','100',*CORE).decode())
    elif args.action=='stop':
        dc('stop',*CORE)  # PostgreSQL/Redis volumes and unrelated services remain.
    elif args.action=='backup':
        backup()
    elif args.action=='restore':
        if args.backup is None:
            parser.error('--backup is required; restore always creates a new isolated database')
        print(json.dumps(restore(args.backup),indent=2))
    elif args.action=='upgrade':
        previous=verify()
        previous_tag=values.get('AUTOTRADER_IMAGE_TAG','4.1.0')
        stamp=datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
        release_dir=private/stamp;release_dir.mkdir(mode=0o700)
        (release_dir/'previous.json').write_text(json.dumps(previous,indent=2)+'\n')
        os.environ['AUTOTRADER_IMAGE_TAG']='upgrade-'+stamp.lower()
        dc('build','backend','frontend')  # Preserve existing database/cache images and containers.
        running=dc('ps','--services','--status','running').decode().split()
        stopped=[s for s in ('worker','backend','research-worker') if s in running]
        if stopped:
            dc('stop',*stopped)
        dump=backup()
        # RC2 requires the existing schema; no production migration is allowed.
        old_backend = next(c['image'] for c in previous['containers'] if c['name'].endswith('-backend-1'))
        restore_result=restore(dump, old_backend)
        dc('up','-d','--wait','--no-build','--no-deps',*CORE)
        current=verify()
        release={'before':previous,'after':current,'backup':str(dump),'restore':restore_result,
            'schema_change':False,'previous_tag':previous_tag,'image_tag':os.environ['AUTOTRADER_IMAGE_TAG'],'previous_images_retained':True}
        (release_dir/'release.json').write_text(json.dumps(release,indent=2)+'\n')
        persist_tag(os.environ['AUTOTRADER_IMAGE_TAG'])
        if 'research-worker' in running:
            dc('up','-d','--no-build','research-worker')
        print('Verified release: '+str(release_dir/'release.json'))
    elif args.action=='rollback':
        if args.release is None:
            parser.error('--release is required')
        release=json.loads(args.release.read_bytes())
        if release['before']['project']!=args.project:
            raise ValueError('Rollback belongs to a different Compose project.')
        backup_schema=release['restore']['candidate']['accounts'][0]['schema']
        financial_set.discover(dc)
        schema=dc('exec','-T','postgres','psql','-U','autotrader','-d','autotrader','-Atc','SELECT version_num FROM alembic_version').decode().strip()
        if schema!=backup_schema:
            raise RuntimeError('Schema changed: restore backup into a new database and review compatibility; automatic destructive downgrade forbidden.')
        containers=release['before']['containers']
        rollback_services=CORE+(['research-worker'] if any(c['name'].endswith('-research-worker-1') for c in containers) else [])
        images={service:next(c['image'] for c in containers if c['name'].endswith('-'+service+'-1')) for service in rollback_services}
        for image in images.values():
            run(['docker','image','inspect',image])
        override=private/('rollback-'+datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
        override.write_text(json.dumps({'services':{service:{'image':image} for service,image in images.items()}}))
        running=dc('ps','--services','--status','running').decode().split()
        writers=[service for service in ('worker','backend','research-worker') if service in running]
        if writers:
            dc('stop',*writers)
        latest=backup()
        restore(latest, images['backend'])
        # Image rollback preserves newer transactions; never restore financial databases.
        run([*compose,'-f',str(override),'up','-d','--wait','--no-build','--no-deps',*CORE])
        persist_tag(release.get('previous_tag','4.1.0'))
        if 'research-worker' in running:
            run([*compose,'-f',str(override),'up','-d','--no-build','--no-deps','research-worker'])
        print(json.dumps(verify(),indent=2))


if __name__=='__main__':
    main()
