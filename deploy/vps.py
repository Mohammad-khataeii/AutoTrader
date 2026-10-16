"""Project-scoped deployment operations. Never removes volumes or other projects."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

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
    parser.add_argument('--backup',type=Path)
    parser.add_argument('--release',type=Path,help='Previously verified release.json for image rollback')
    parser.add_argument('--release-commit',help='Full approved immutable Git commit; required for production source operations')
    parser.add_argument('--release-manifest',type=Path,help='Verified release-manifest.json accompanying that commit')
    args=parser.parse_args()
    if not re.fullmatch(r'autotrader-[a-z0-9][a-z0-9-]{0,45}',args.project):
        parser.error('An independent autotrader-* Compose project is required.')
    if args.project=='autotrader-v41' and args.action in {'build','up','upgrade'}:
        if not args.release_commit or not args.release_manifest:
            parser.error('Production source operations require --release-commit and --release-manifest after explicit release approval.')
        import importlib.util
        spec=importlib.util.spec_from_file_location('autotrader_release',ROOT/'deploy'/'release.py')
        release_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(release_module)
        verified=release_module.verify_source_release(ROOT,args.release_manifest.resolve(),args.release_commit)
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
    if args.action=='inventory':
        print(run(['docker','ps','--format','{{.Names}} | {{.Image}} | {{.Ports}}']).decode())
        return
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
    def backup_database(database: str = 'autotrader', account_id: str = 'paper-eur') -> Path:
        if database!='autotrader' and not re.fullmatch(r'autotrader_shadow_[a-f0-9]{32}',database):
            raise ValueError('Backup database is outside the registered AutoTrader domains.')
        stamp=datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:6]
        output=private/(stamp+'.dump')
        data=dc('exec','-T','postgres','pg_dump','-U','autotrader','-Fc',database)
        # Parse the archive before recording it as a usable backup.
        dc('exec','-T','postgres','pg_restore','--list',data=data)
        descriptor=os.open(output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        metadata={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'project':args.project,
            'database':database,'account_id':account_id,
            'schema':dc('exec','-T','postgres','psql','-U','autotrader','-d',database,'-Atc','SELECT version_num FROM alembic_version').decode().strip()}
        output.with_suffix('.json').write_text(json.dumps(metadata,indent=2)+'\n')
        output.with_suffix('.json').chmod(0o600)
        print('Verified backup archive: '+str(output))
        return output
    def backup() -> Path:
        output=backup_database()
        exists=dc('exec','-T','postgres','psql','-U','autotrader','-d','autotrader','-Atc',
            "SELECT to_regclass('public.shadow_experiments') IS NOT NULL").decode().strip()=='t'
        children=[]
        if exists:
            rows=json.loads(dc('exec','-T','postgres','psql','-U','autotrader','-d','autotrader','-Atc',
                "SELECT COALESCE(json_agg(json_build_object('id',experiment_id,'database',database_name,'state',state)),'[]'::json) FROM shadow_experiments"))
            for row in rows:
                if row['state']=='CREATING':
                    raise RuntimeError('Shadow provisioning is incomplete; backup set/deployment refused.')
                child=backup_database(row['database'],'shadow:'+row['id'])
                children.append(str(child))
        metadata=json.loads(output.with_suffix('.json').read_bytes())
        metadata['shadow_backups']=children
        output.with_suffix('.json').write_text(json.dumps(metadata,indent=2)+'\n')
        return output
    def restore(path: Path) -> dict:
        path=path.resolve()
        data=path.read_bytes()
        metadata=json.loads(path.with_suffix('.json').read_bytes())
        if hashlib.sha256(data).hexdigest()!=metadata['sha256']:
            raise RuntimeError('Backup checksum mismatch.')
        database='autotrader_restore_'+uuid4().hex[:12]
        dc('exec','-T','postgres','createdb','-U','autotrader',database)
        dc('exec','-T','postgres','pg_restore','--exit-on-error','--no-owner','-U','autotrader','-d',database,data=data)
        code=(ROOT/'deploy'/'verify_clone.py').read_text()
        code+='\nprint(json.dumps(asyncio.run(verify_clone('+repr(database)+','+repr(metadata.get('account_id','paper-eur'))+'))))\n'
        # Does not require the dashboard to be running, and never migrates the dump.
        check=json.loads(dc('run','--rm','--no-deps','backend','python','-c',code))
        children=[restore(Path(child)) for child in metadata.get('shadow_backups',[])]
        result={'restore_database':database,'account_id':metadata.get('account_id','paper-eur'),
            'reconciliation':check['reconciliation'],'verification':check,'original_database_modified':False,'backup_sha256':metadata['sha256'],
            'shadow_restores':children,'runtime_activation':'forbidden without isolated cluster or reviewed mapping'}
        (private/(database+'.json')).write_text(json.dumps(result,indent=2)+'\n')
        return result
    def stage_migration(database: str, account: str = 'paper-eur') -> dict:
        code=(ROOT/'deploy'/'verify_clone.py').read_text()
        code+='\nprint(json.dumps(asyncio.run(verify_clone('+repr(database)+','+repr(account)+',migrate=True))))\n'
        return json.loads(dc('run','--rm','--no-deps','backend','python','-c',code))

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
        dc('up','-d','--wait','--no-build','postgres','redis')
        state=database_state(dc)
        if state=='POPULATED':
            restored=restore(backup())
            stage_migration(restored['restore_database'])
            for child in restored['shadow_restores']:
                stage_migration(child['restore_database'],child['account_id'])
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
        # Backup parse + full isolated restore/reconciliation precede any migration.
        restore_result=restore(dump)
        migration_result=stage_migration(restore_result['restore_database'])
        shadow_migrations=[stage_migration(child['restore_database'],child['account_id']) for child in restore_result['shadow_restores']]
        dc('run','--rm','--no-deps','migrate')
        dc('up','-d','--wait','--no-build','--no-deps',*CORE)
        current=verify()
        release={'before':previous,'after':current,'backup':str(dump),'restore':restore_result,
            'staged_migration':migration_result,'shadow_migrations':shadow_migrations,'previous_tag':previous_tag,'image_tag':os.environ['AUTOTRADER_IMAGE_TAG'],'previous_images_retained':True}
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
        backup_schema=json.loads(Path(release['backup']).with_suffix('.json').read_bytes())['schema']
        schema=dc('exec','-T','postgres','psql','-U','autotrader','-d','autotrader','-Atc','SELECT version_num FROM alembic_version').decode().strip()
        if schema!=backup_schema:
            raise RuntimeError('Schema changed: restore backup into a new database and review compatibility; automatic destructive downgrade forbidden.')
        containers=release['before']['containers']
        images={service:next(c['image'] for c in containers if c['name'].endswith('-'+service+'-1')) for service in CORE}
        for image in images.values():
            run(['docker','image','inspect',image])
        override=private/'rollback.json'
        override.write_text(json.dumps({'services':{service:{'image':image} for service,image in images.items()}}))
        # `run migrate` from the old image is intentionally not called on rollback.
        run([*compose,'-f',str(override),'up','-d','--wait','--no-build','--no-deps',*CORE])
        persist_tag(release.get('previous_tag','4.1.0'))
        print(json.dumps(verify(),indent=2))


if __name__=='__main__':
    main()
