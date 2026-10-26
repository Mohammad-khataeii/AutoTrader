"""Scoped Mac backup and read-only restore proof. Never targets a VPS."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from deploy.financial_set import FINANCIAL_TABLES, backup_all, financial_seal, validate_inventory

ROOT=Path(__file__).resolve().parents[1]
COMPOSE=['docker','compose','--project-directory',str(ROOT),'-p','autotrader-v46-mac',
    '--env-file',str(ROOT/'.env.local'),'-f',str(ROOT/'docker-compose.yml'),'-f',str(ROOT/'docker-compose.mac.yml')]


def run(args,data=None):
    result=subprocess.run(args,input=data,capture_output=True,check=False)
    if result.returncode:raise RuntimeError(result.stderr.decode()[-2000:])
    return result.stdout


def dc(*parts,data=None):return run([*COMPOSE,*parts],data)


VERIFY='''
import asyncio,json,hashlib
from decimal import Decimal
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from autotrader.persistence.repository import PersistentTradingRepository
async def main():
 manifest=json.loads(Path('/backup-set.json').read_text());out=[]
 for r in manifest['databases']:
  e=create_async_engine('postgresql+asyncpg://autotrader@restore-postgres:5432/'+r['database'],connect_args={'server_settings':{'default_transaction_read_only':'on'}},isolation_level='REPEATABLE READ')
  try:
   async with e.connect() as c,c.begin():
    f=async_sessionmaker(bind=c,expire_on_commit=False);repo=PersistentTradingRepository(f);repo.account_id=r['account_id']
    initial=Decimal(7000) if r['account_id']=='PERSONAL_PLAN_PAPER_7000' else Decimal(500)
    async with f() as s:assert await repo._verify(s,initial)==[]
    actual=list((await c.execute(text('SELECT account_id FROM accounts'))).scalars());assert actual==[r['account_id']]
    funding=(await c.execute(text("SELECT count(*),sum(cash_delta) FROM financial_journal WHERE event_type='INITIAL_FUNDING'"))).one();assert funding==(1,initial)
    for t,expected in r['financial_seal'].items():
     rows=(await c.execute(text('SELECT to_jsonb(t)::text FROM '+t+' t ORDER BY to_jsonb(t)::text'))).scalars().all()
     assert {'rows':len(rows),'sha256':hashlib.sha256(b''.join(x.encode()+b'\\n' for x in rows)).hexdigest()}==expected
    if r['manifest']:
     marker=(await c.execute(text('SELECT manifest_json,manifest_hash FROM shadow_identity WHERE singleton=1'))).one();assert json.loads(marker[0])==r['manifest'] and marker[1]==r['manifest_hash']
    if r.get('active_profile'):
     profile=await c.scalar(text('SELECT payload_json FROM system_state WHERE key=:key'),{'key':'paper_profile:'+r['active_profile']['version']});assert json.loads(profile)==r['active_profile']
    out.append({'account_id':r['account_id'],'initial_cash':str(initial),'funding_count':1,'reconciliation':[],'financial_seals_unchanged':True})
  finally:await e.dispose()
 print(json.dumps({'status':'PASS','accounts':out,'read_only':True,'schema_migration':False,'synthetic_funding':False}))
asyncio.run(main())
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--image',required=True);parser.add_argument('--label',required=True);parser.add_argument('--restart-stores',action='store_true');args=parser.parse_args()
    token='autotrader-v47-proof-'+uuid4().hex[:10];network=token+'-net';container=token+'-pg'
    base=ROOT/'.tools/v47';base.mkdir(exist_ok=True)
    dc('stop','worker','research-worker','backend')
    manifest=backup_all(dc,base/('backup-'+args.label),required=frozenset())
    body=json.loads(manifest.read_text());validate_inventory(body['databases'],required=frozenset())
    for r in body['databases']:
        contents=(manifest.parent/r['file']).read_bytes();assert hashlib.sha256(contents).hexdigest()==r['sha256']
    verifier=base/'verify-clone.py';verifier.write_text(VERIFY)
    run(['docker','network','create','--internal','--label','autotrader.v47.proof='+token,network])
    run(['docker','run','-d','--name',container,'--network',network,'--network-alias','restore-postgres',
        '--label','autotrader.v47.proof='+token,'--tmpfs','/var/lib/postgresql/data','-e','POSTGRES_USER=autotrader','-e','POSTGRES_DB=postgres','-e','POSTGRES_HOST_AUTH_METHOD=trust','postgres:16-alpine'])
    # A failed proof retains only these named diagnostic resources and stops
    # the update. It never restores into the running Mac financial databases.
    for _ in range(60):
        if subprocess.run(['docker','exec',container,'pg_isready','-U','autotrader'],capture_output=True,check=False).returncode==0:break
        time.sleep(.5)
    else:raise RuntimeError('isolated_restore_postgres_unavailable')
    for r in body['databases']:
        run(['docker','exec',container,'createdb','-U','autotrader',r['database']])
        run(['docker','exec','-i',container,'pg_restore','--exit-on-error','--no-owner','-U','autotrader','-d',r['database']],(manifest.parent/r['file']).read_bytes())
    proof=json.loads(run(['docker','run','--rm','--network',network,'--read-only','--tmpfs','/tmp',
        '-e','PYTHONDONTWRITEBYTECODE=1','-v',str(verifier)+':/verify-clone.py:ro',
        '-v',str(manifest)+':/backup-set.json:ro',args.image,'python','/verify-clone.py']))
    proof.update({'backup_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'database_count':len(body['databases']),'network_internal':True,'vps_accessed':False,
        'source_image':args.image,'postgres_redis_restarted':args.restart_stores,'preserved_tables':list(FINANCIAL_TABLES)})
    proof_path=ROOT/'docs/evidence/v4_7'/('financial-'+args.label+'.json')
    # Check the source databases themselves were untouched by restore proofs.
    for r in body['databases']:assert financial_seal(dc,r['database'])==r['financial_seal']
    run(['docker','rm','-f',container]);run(['docker','network','rm',network])
    if args.restart_stores:
        dc('restart','postgres','redis')
        for _ in range(60):
            try:
                dc('exec','-T','postgres','pg_isready','-U','autotrader')
                dc('exec','-T','redis','redis-cli','ping')
                break
            except RuntimeError:
                time.sleep(.5)
        else:raise RuntimeError('local_stores_restart_failed')
        for r in body['databases']:assert financial_seal(dc,r['database'])==r['financial_seal']
    dc('--profile','research','up','-d','--wait','--no-build','--no-deps','backend','worker','research-worker')
    dc('restart','frontend')
    dc('up','-d','--wait','--no-build','--no-deps','frontend')
    proof['services_resumed']=True
    proof_path.write_text(json.dumps(proof,indent=2)+'\n')
    print('PASS:',len(body['databases']),'local financial domains backed up, restored read-only and reconciled; Mac services resumed.')


if __name__=='__main__':main()
