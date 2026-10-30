"""Disposable network-isolated restored-ledger rehearsal; never connects to the VPS."""
import asyncio
import hashlib
import json
from decimal import Decimal as D
from pathlib import Path

from sqlalchemy import text

from autotrader.config import get_settings
from autotrader.persistence.database import make_engine, make_session_factory
from autotrader.persistence.models import ShadowIdentityModel
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.personal_paper.policy import VERSION, fingerprint
from autotrader.personal_paper.service import PersonalPaperService
from autotrader.research.artifacts import source_fingerprint
from autotrader.shadow.lab import ShadowLab
from autotrader.shadow.versions import (
 compatibility,
 execution_fingerprint,
 verify_boundary,
 verify_legacy,
 verify_v44,
)

TABLES=['balances','financial_journal','orders','fills','positions','capital_reservations','exit_intents','exit_targets','exit_plans','ai_budgets','ai_usage','order_transitions']
async def seal(repo):
 body={}
 async with repo.session_factory() as db:
  await db.execute(text('SET TRANSACTION READ ONLY'))
  for table in TABLES:
   rows=(await db.execute(text('SELECT to_jsonb(t)::text FROM '+table+' t ORDER BY to_jsonb(t)::text'))).scalars().all()
   body[table]={'rows':len(rows),'sha256':hashlib.sha256(b''.join(v.encode()+b'\n' for v in rows)).hexdigest()}
 return body
async def main():
 s=get_settings();assert s.environment=='staging' and 'restore-postgres:5432/autotrader_aruba_staging' in s.database_url and not s.live_trading_enabled
 verify_legacy();verify_v44();verify_boundary()
 e=make_engine(s);official=PersistentTradingRepository(make_session_factory(e));service=PersonalPaperService(official,s);lab=ShadowLab(official,s)
 try:
  primary=await service.repository();assert primary
  records=await lab.records();assert len(records)==15
  active=[r for r in records if not r.get('archived_at')];assert len(active)==7
  accounts=[official,primary,*[await lab.repository(r['experiment_id']) for r in records]]
  before={r.account_id:await seal(r) for r in accounts}
  manifests={r['experiment_id']:r['manifest'] for r in records}
  for repo in accounts:assert await repo.verify_invariants(D(7000) if repo is primary else D(500))==[]
  async with primary.session_factory() as db:
   origin=(await db.get(ShadowIdentityModel,1)).manifest_json
   assert (await db.execute(text("SELECT count(*),sum(cash_delta) FROM financial_journal WHERE event_type='INITIAL_FUNDING'"))).one()==(1,D(7000))
  parent=primary.manifest;start=await primary.snapshot()
  assert before[primary.account_id]['fills']['rows']>=18 and D(start['cash'])>0
  assert all(D(start[k])==0 for k in ['positions','pending_orders','reserved_cash'])
  await primary.set_control('pause')
  primary=await service.create_runtime_revision('V4.9.3 isolated restored ledger causal learning and unchanged primary admission rehearsal')
  assert primary.manifest['version']==VERSION=='4.9.3-paper.1'
  assert primary.manifest['account_origin']==parent['account_origin']
  async with primary.session_factory() as db:assert (await db.get(ShadowIdentityModel,1)).manifest_json==origin
  after_records=await lab.records();assert {r['experiment_id']:r['manifest'] for r in after_records}==manifests
  assert all(compatibility(r['manifest'])['compatible'] for r in active)
  assert len([r for r in after_records if r.get('archived_at')])==8
  for repo in accounts:
   assert await seal(repo)==before[repo.account_id]
   assert await repo.verify_invariants(D(7000) if repo.account_id==primary.account_id else D(500))==[]
  after=await primary.snapshot()
  for key in ['cash','realized_pnl','orders','positions','reserved_cash']:assert after[key]==start[key]
  out={'status':'PASS','source_fingerprint':source_fingerprint()[0],
   'evidence_category':'LOCAL_ISOLATED_RESTORED_REAL_LEDGER_ENGINEERING','restored_accounts':17,
   'retained_financial_tables':TABLES,'original_financial_seals':'ALL_MATCH_BEFORE_AFTER',
   'initial_primary_funding_events':1,'primary_cash':after['cash'],'primary_fills':before[primary.account_id]['fills']['rows'],
   'origin_identity_unchanged':True,'new_profile':VERSION,'primary_runtime_fingerprint':fingerprint(),
   'retained_original_controls':7,'retained_archived_controls':8,'new_accounts':0,'deleted_accounts':0,
   'all_shadow_manifests_unchanged':True,'original_controls_runtime_compatible':True,
   'execution_fingerprint':execution_fingerprint(),'network_isolation':True,'host_ports':[],
   'source_database_exports':'Fresh Stage A read-only Aruba pg_dump streams; per-database cutoffs differ',
   'financial_seals':before,'prospective_performance_claim':False,'remote_writes':False,
   'limitations':['Local snapshot proof does not replace a fresh Stage B backup and isolated restore before activation.',
    'An open shadow position is preserved in the clone; actual deployment must wait for all original ledgers to become flat under their existing protection.']}
  Path('/output/financial-restore.json').write_text(json.dumps(out,indent=2)+'\n')
  print(json.dumps({k:v for k,v in out.items() if k!='financial_seals'}))
 finally:await lab.close();await service.close();await e.dispose()
asyncio.run(main())
