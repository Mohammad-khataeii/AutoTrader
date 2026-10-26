"""Online exported-snapshot backups; keep the Mac protective worker running."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.financial_set import FINANCIAL_TABLES, discover, validate_inventory

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ['docker','compose','--project-directory',str(ROOT),'-p','autotrader-v46-mac',
    '--env-file',str(ROOT/'.env.local'),'-f',str(ROOT/'docker-compose.yml'),'-f',str(ROOT/'docker-compose.mac.yml')]
OWNER = '''import sys,json,hashlib,psycopg
from sqlalchemy.engine import make_url
from autotrader.config import get_settings
u=make_url(get_settings().database_url)
with psycopg.connect(dbname=sys.argv[1],user=u.username,password=u.password,host=u.host,port=u.port or 5432) as c:
 c.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
 snapshot=c.execute('SELECT pg_export_snapshot()').fetchone()[0]
 seal={}
 for table in json.loads(sys.argv[2]):
  rows=[r[0] for r in c.execute('SELECT to_jsonb(t)::text FROM '+table+' t ORDER BY to_jsonb(t)::text')]
  seal[table]={'rows':len(rows),'sha256':hashlib.sha256(b''.join(r.encode()+b'\\n' for r in rows)).hexdigest()}
 print(json.dumps({'snapshot':snapshot,'financial_seal':seal}),flush=True)
 sys.stdin.readline()
 c.rollback()
'''


def run(args, data=None):
    r=subprocess.run(args,input=data,capture_output=True,check=False)
    if r.returncode:raise RuntimeError(r.stderr.decode()[-1800:])
    return r.stdout


def dc(*parts,data=None):return run([*COMPOSE,*parts],data)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--image',required=True);args=parser.parse_args()
    worker=run(['docker','inspect','autotrader-v46-mac-worker-1','--format','{{.Id}} {{.State.StartedAt}}'])
    records=discover(dc,required=frozenset());validate_inventory(records,required=frozenset())
    stamp=datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    destination=ROOT/'.tools/v47_1/backups'/stamp;destination.mkdir(mode=0o700,parents=True)
    for r in records:
        owner=subprocess.Popen(['docker','exec','-i','autotrader-v46-mac-backend-1','python','-c',OWNER,r['database'],json.dumps(FINANCIAL_TABLES)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            line=owner.stdout.readline()
            if not line:raise RuntimeError('snapshot_owner_failed:'+owner.stderr.read().decode()[-1000:])
            snapshot=json.loads(line);r['financial_seal']=snapshot['financial_seal']
            data=dc('exec','-T','postgres','pg_dump','-U','autotrader','-Fc','--snapshot',snapshot['snapshot'],r['database'])
            dc('exec','-T','postgres','pg_restore','--list',data=data)
            path=destination/(r['database']+'.dump');fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
            r.update(file=path.name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),snapshot_exported=True)
        finally:
            owner.communicate(input=b'release\n',timeout=15)
        print('Snapshot saved:',r['account_id'],flush=True)
    body={'schema':'financial-backup-set/2','databases':records,'created_at':datetime.now(UTC).isoformat(),'required_identities':[],'method':'EXPORTED_REPEATABLE_READ_SNAPSHOT','worker_uninterrupted':True}
    manifest=destination/'backup-set.json';manifest.write_text(json.dumps(body,indent=2)+'\n');manifest.chmod(0o600)
    token='autotrader-v471-proof-'+uuid4().hex[:10];network=token+'-net';container=token+'-pg'
    run(['docker','network','create','--internal',network]);run(['docker','run','-d','--name',container,'--network',network,'--network-alias','restore-postgres','--tmpfs','/var/lib/postgresql/data','-e','POSTGRES_USER=autotrader','-e','POSTGRES_DB=postgres','-e','POSTGRES_HOST_AUTH_METHOD=trust','postgres:16-alpine'])
    for _ in range(60):
        if subprocess.run(['docker','exec',container,'pg_isready','-U','autotrader'],capture_output=True,check=False).returncode==0:break
        time.sleep(.25)
    else:raise RuntimeError('isolated_restore_unavailable')
    for r in records:
        data=(destination/r['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==r['sha256']
        run(['docker','exec',container,'createdb','-U','autotrader',r['database']])
        run(['docker','exec','-i',container,'pg_restore','--exit-on-error','--no-owner','-U','autotrader','-d',r['database']],data)
    spec=importlib.util.spec_from_file_location('macproof',ROOT/'scripts/v47_mac_financial_check.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    verifier=destination/'verify.py';verifier.write_text(module.VERIFY)
    proof=json.loads(run(['docker','run','--rm','--network',network,'--read-only','--tmpfs','/tmp','-e','PYTHONDONTWRITEBYTECODE=1','-v',str(verifier)+':/verify.py:ro','-v',str(manifest)+':/backup-set.json:ro',args.image,'python','/verify.py']))
    assert worker==run(['docker','inspect','autotrader-v46-mac-worker-1','--format','{{.Id}} {{.State.StartedAt}}'])
    proof.update(method=body['method'],database_count=len(records),worker_uninterrupted=True,source_databases_restored=False,backup_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),vps_accessed=False)
    out=ROOT/'docs/evidence/v4_7_1';out.mkdir(parents=True,exist_ok=True);(out/'financial-before.json').write_text(json.dumps(proof,indent=2)+'\n')
    (ROOT/'.tools/v47_1/backup-manifest-path.txt').write_text(str(manifest)+'\n')
    run(['docker','rm','-f',container]);run(['docker','network','rm',network]);print('PASS: four online backups restored read-only; worker uninterrupted.',flush=True)


if __name__=='__main__':main()
