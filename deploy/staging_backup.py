"""Staging-only consistent backups for every registered ledger; isolated restore proof."""
import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

B=Path('/opt/personal-plan/staging');R=Path(__file__).resolve().parents[1]
os.umask(0o077)
spec=importlib.util.spec_from_file_location('financial',R/'deploy/financial_set.py');f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
TABLES=f.FINANCIAL_TABLES

def run(args,data=None):
 p=subprocess.run(args,input=data,capture_output=True,check=False)
 if p.returncode:raise RuntimeError('staging_operation_failed:'+p.stderr.decode()[-1600:])
 return p.stdout

def dc(*args,data=None):return run([str(B/'ops/compose'),*args],data)

DISCOVER='''import asyncio,json
from autotrader.config import get_settings
from autotrader.persistence.database import make_engine,make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.personal_paper.service import PersonalPaperService
from autotrader.shadow.lab import ShadowLab
from autotrader.research.data import canonical,digest
async def main():
 s=get_settings();assert s.environment=='staging' and not s.live_trading_enabled and s.personal_paper_enabled
 e=make_engine(s);o=PersistentTradingRepository(make_session_factory(e));v=PersonalPaperService(o,s);r=await v.repository();assert r
 assert r.manifest['official_database']=='autotrader_aruba_staging'
 lab=ShadowLab(o,s)
 records=[{'account_id':'paper-eur','database':'autotrader_aruba_staging','initial':'500','manifest':None}, {'account_id':r.account_id,'database':r.manifest['database_name'],'initial':'7000','manifest':r.manifest,'manifest_hash':digest(canonical(r.manifest))}]
 for record in await lab.records():
  assert record['state']!='CREATING','incomplete_shadow_provisioning_backup_stopped'
  scoped=await lab.repository(record['experiment_id'])
  records.append({'account_id':scoped.account_id,'database':scoped.scope.database_name,'initial':'500','manifest':scoped.scope.manifest,'manifest_hash':scoped.scope.identity_hash})
 assert len({x['database'] for x in records})==len(records)
 print(json.dumps(records));await lab.close();await v.close();await e.dispose()
asyncio.run(main())
'''
OWNER='''import sys,json,hashlib,psycopg
from sqlalchemy.engine import make_url
from autotrader.config import get_settings
u=make_url(get_settings().database_url)
with psycopg.connect(dbname=sys.argv[1],user=u.username,password=u.password,host=u.host,port=u.port or 5432) as c:
 c.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
 snapshot=c.execute('SELECT pg_export_snapshot()').fetchone()[0];seal={}
 for table in json.loads(sys.argv[2]):
  rows=[x[0] for x in c.execute('SELECT to_jsonb(t)::text FROM '+table+' t ORDER BY to_jsonb(t)::text')]
  seal[table]={'rows':len(rows),'sha256':hashlib.sha256(b''.join(r.encode()+b'\\n' for r in rows)).hexdigest()}
 print(json.dumps({'snapshot':snapshot,'financial_seal':seal,'database_size_bytes':c.execute('SELECT pg_database_size(current_database())').fetchone()[0]}),flush=True);sys.stdin.readline();c.rollback()
'''
VERIFY='''import asyncio,json,hashlib
from decimal import Decimal
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from autotrader.persistence.repository import PersistentTradingRepository
async def main():
 data=json.loads(Path('/backup-set.json').read_text());out=[]
 for r in data['databases']:
  e=create_async_engine('postgresql+asyncpg://autotrader@restore-postgres:5432/'+r['database'],connect_args={'server_settings':{'default_transaction_read_only':'on'}},isolation_level='REPEATABLE READ')
  try:
   async with e.connect() as c,c.begin():
    factory=async_sessionmaker(bind=c,expire_on_commit=False);repo=PersistentTradingRepository(factory);repo.account_id=r['account_id']
    async with factory() as db:assert await repo._verify(db,Decimal(r['initial']))==[]
    funding=(await c.execute(text("SELECT count(*),sum(cash_delta) FROM financial_journal WHERE event_type='INITIAL_FUNDING'"))).one();assert funding==(1,Decimal(r['initial']))
    assert list((await c.execute(text('SELECT account_id FROM accounts'))).scalars())==[r['account_id']]
    for table,expected in r['financial_seal'].items():
     rows=(await c.execute(text('SELECT to_jsonb(t)::text FROM '+table+' t ORDER BY to_jsonb(t)::text'))).scalars().all()
     assert {'rows':len(rows),'sha256':hashlib.sha256(b''.join(x.encode()+b'\\n' for x in rows)).hexdigest()}==expected
    if r['manifest']:
     marker=(await c.execute(text('SELECT manifest_json,manifest_hash FROM shadow_identity WHERE singleton=1'))).one()
     origin=r['manifest'].get('account_origin',r['manifest'])
     assert json.loads(marker[0])==origin and marker[1]==hashlib.sha256(json.dumps(origin,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    out.append({'account_id':r['account_id'],'funding_count':1,'initial_cash':r['initial'],'reconciliation':[],'financial_seals':'MATCH'})
  finally:await e.dispose()
 print(json.dumps({'status':'PASS','accounts':out,'read_only_restore_verification':True}))
asyncio.run(main())
'''

REHEARSE='''import asyncio,json
from sqlalchemy import select,func
from autotrader.config import get_settings
from autotrader.persistence.database import make_engine,make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.persistence.models import JournalEventModel,ShadowIdentityModel
from autotrader.personal_paper.service import PersonalPaperService
from autotrader.personal_paper.policy import VERSION
from autotrader.research.data import canonical,digest
async def main():
 s=get_settings();assert s.environment=='staging' and s.database_url.split('@')[1].startswith('restore-postgres:') and not s.live_trading_enabled
 e=make_engine(s);v=PersonalPaperService(PersistentTradingRepository(make_session_factory(e)),s)
 try:
  r=await v.repository();assert r
  before=await r.snapshot();orders=await r.list_orders();fills=await r.list_fills()
  assert before['control']=='PAUSED' and await r.verify_invariants(__import__('decimal').Decimal(7000))==[]
  async with r.session_factory() as db:origin=(await db.get(ShadowIdentityModel,1)).manifest_json
  r=await v.create_runtime_revision('Isolated restored Aruba account rehearsal for reviewed paper-only release')
  after=await r.snapshot()
  assert all(before[k]==after[k] for k in ['cash','available_cash','reserved_cash','realized_pnl','orders','positions'])
  assert await r.list_orders()==orders and await r.list_fills()==fills
  assert await r.verify_invariants(__import__('decimal').Decimal(7000))==[]
  async with r.session_factory() as db:
   assert (await db.get(ShadowIdentityModel,1)).manifest_json==origin
   funding=await db.scalar(select(func.count()).select_from(JournalEventModel).where(JournalEventModel.event_type=='INITIAL_FUNDING'));assert funding==1
  assert r.manifest['version']==VERSION and after['control']=='PAUSED'
  print(json.dumps({'status':'PASS','profile':VERSION,'cash':after['cash'],'funding_count':funding,'orders':len(orders),'fills':len(fills),'origin_preserved':True,'reconciliation':[]}))
 finally:await v.close();await e.dispose()
asyncio.run(main())
'''

def wait_restore_postgres(container):
 # The image's temporary init server accepts Unix sockets, then shuts down.
 # Only the final postmaster listens on TCP; a socket probe can race shutdown.
 for _ in range(60):
  if subprocess.run(['docker','exec',container,'pg_isready','-h','127.0.0.1','-U','autotrader','-d','postgres'],capture_output=True,check=False).returncode==0:return
  time.sleep(.25)
 raise RuntimeError('restore_clone_unavailable')


def restore_clone(directory,records,image,manifest,result,*,rehearse_profile=False):
 token='autotrader-aruba-restore-'+uuid4().hex[:8];network=token+'-net';container=token+'-pg';volume=token+'-data'
 (directory/'restore-attempt.json').write_text(json.dumps({'network':network,'container':container,'volume':volume,'memory_limit_bytes':512*1024**2,'storage':'ISOLATED_NAMED_VOLUME','failed_resources_retained_for_diagnostics':True},indent=2)+'\n')
 run(['docker','volume','create','--label','personal-plan.restore=aruba',volume])
 required=max(1024**3,2*sum(int(r['database_size_bytes']) for r in records)+sum(int(r['bytes']) for r in records))
 probe="import shutil;print(shutil.disk_usage('/restore-space').free)"
 available=int(run(['docker','run','--rm','--network','none','--read-only','--memory','64m','--user','0:0','-v',volume+':/restore-space:ro',image,'python','-c',probe]))
 if available<required:
  run(['docker','volume','rm',volume]);raise RuntimeError('isolated_restore_disk_capacity_insufficient')
 run(['docker','network','create','--internal','--label','personal-plan.restore=aruba',network])
 run(['docker','run','-d','--name',container,'--network',network,'--network-alias','restore-postgres','--label','personal-plan.restore=aruba','-v',volume+':/var/lib/postgresql/data','--memory','512m','-e','POSTGRES_USER=autotrader','-e','POSTGRES_DB=postgres','-e','POSTGRES_HOST_AUTH_METHOD=trust','postgres:16-alpine'])
 wait_restore_postgres(container)
 for r in records:
  data=(directory/r['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==r['sha256'];run(['docker','exec',container,'createdb','-U','autotrader',r['database']]);run(['docker','exec','-i',container,'pg_restore','--exit-on-error','--no-owner','-U','autotrader','-d',r['database']],data)
 verifier=directory/'verify.py';verifier.write_text(VERIFY)
 # root owns the private host backup. Inside the isolated verifier only these
 # two mounted read-only files are readable; the host env/secrets are absent.
 restored=json.loads(run(['docker','run','--rm','--user','0:0','--network',network,'--read-only','--tmpfs','/tmp','-e','PYTHONDONTWRITEBYTECODE=1','-v',str(verifier)+':/verify.py:ro','-v',str(manifest)+':/backup-set.json:ro',image,'python','/verify.py']))
 if restored.get('status')!='PASS' or len(restored.get('accounts',[]))!=len(records):raise ValueError('isolated_restore_verification_failed')
 result.update(restore_test=True,restore=restored,network_internal=True,source_databases_restored=False,restore_storage='ISOLATED_NAMED_VOLUME',restore_memory_limit_bytes=512*1024**2,disk_capacity={'available_bytes':available,'required_bytes':required})
 if rehearse_profile:
  rehearsal=run(['docker','run','--rm','--network',network,'--read-only','--tmpfs','/tmp','--memory','512m',
   '-e','ENVIRONMENT=staging','-e','DASHBOARD_PASSWORD=ISOLATED_CLONE_ONLY_NO_EXTERNAL_ACCESS',
   '-e','DATABASE_URL=postgresql+asyncpg://autotrader@restore-postgres:5432/autotrader_aruba_staging',
   '-e','PERSONAL_PAPER_ENABLED=true','-e','LIVE_TRADING_ENABLED=false','-e','SHADOW_ENABLED=true',image,'python','-c',REHEARSE])
  result['candidate_profile_rehearsal']=json.loads(rehearsal)
  if result['candidate_profile_rehearsal'].get('status')!='PASS':raise ValueError('isolated_profile_rehearsal_failed')
 run(['docker','rm','-f',container]);run(['docker','network','rm',network]);run(['docker','volume','rm',volume])
 result['isolated_restore_resources_removed']=True


def main():
 import fcntl
 lock_handle=(B/'ops/backup.lock').open('a')
 fcntl.flock(lock_handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
 parser=argparse.ArgumentParser();parser.add_argument('--restore-test',action='store_true');parser.add_argument('--candidate-image');parser.add_argument('--rehearse-profile',action='store_true');args=parser.parse_args()
 records=json.loads(dc('exec','-T','backend','python','-c',DISCOVER))
 assert len(records)>=2 and records[1]['database'].startswith('autotrader_paper_')
 stamp=datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8];directory=B/'backups'/stamp;directory.mkdir(mode=0o700)
 for r in records:
  p=subprocess.Popen([str(B/'ops/compose'),'exec','-T','backend','python','-c',OWNER,r['database'],json.dumps(TABLES)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  try:
   snap=json.loads(p.stdout.readline());data=dc('exec','-T','postgres','pg_dump','-U','autotrader','-Fc','--snapshot',snap['snapshot'],r['database']);dc('exec','-T','postgres','pg_restore','--list',data=data)
   path=directory/(r['database']+'.dump');path.write_bytes(data);path.chmod(0o600)
   r.update(file=path.name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),financial_seal=snap['financial_seal'],database_size_bytes=snap['database_size_bytes'])
  finally:p.communicate(input=b'release\n',timeout=15)
 container_id=dc('ps','-q','backend').decode().strip()
 image=args.candidate_image or run(['docker','inspect',container_id,'--format','{{.Image}}']).decode().strip()
 import re
 assert re.fullmatch('sha256:[a-f0-9]{64}',image)
 body={'schema':'aruba-staging-backup/1','application_commit':json.loads((R/'release-manifest.json').read_text())['commit'],'project':'autotrader-aruba-test','created_at':datetime.now(UTC).isoformat(),'method':'EXPORTED_REPEATABLE_READ_SNAPSHOT','worker_uninterrupted':True,'databases':records,'runtime_image_id':image}
 manifest=directory/'backup-set.json';manifest.write_text(json.dumps(body,indent=2)+'\n');manifest.chmod(0o600)
 result={'status':'PASS','manifest':str(manifest),'accounts':len(records),'dump_bytes':sum(r['bytes'] for r in records),'worker_uninterrupted':True,'restore_test':False}
 if args.restore_test:
  restore_clone(directory,records,image,manifest,result,rehearse_profile=args.rehearse_profile)
 (B/'evidence/backup-latest.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result,indent=2))

if __name__=='__main__':main()
