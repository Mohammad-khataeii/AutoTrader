"""Explicit Mac profile revision, deliberately leaving entries paused for health checks."""
import argparse
import asyncio
import json
import os

from sqlalchemy import func, select

from autotrader.config import get_settings
from autotrader.persistence.database import make_engine, make_session_factory
from autotrader.persistence.models import JournalEventModel, ShadowIdentityModel
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.personal_paper.policy import INITIAL, VERSION, fingerprint
from autotrader.personal_paper.service import PersonalPaperService
from autotrader.research.data import canonical, digest


async def main(parent,reason):
    if os.environ.get('AUTOTRADER_MAC_REVISION')!='1':raise ValueError('explicit_mac_revision_required')
    settings=get_settings()
    if settings.live_trading_enabled or not settings.personal_paper_enabled:raise ValueError('virtual_experimental_authority_required')
    engine=make_engine(settings);service=PersonalPaperService(PersistentTradingRepository(make_session_factory(engine)),settings)
    try:
        old=await service.repository()
        assert old and digest(canonical(old.manifest))==parent
        before=await old.snapshot()
        assert before['control']=='PAUSED' and await old.verify_invariants(INITIAL)==[]
        orders=await old.list_orders();fills=await old.list_fills()
        async with old.session_factory() as session:
            origin=(await session.get(ShadowIdentityModel,1)).manifest_json
        repo=await service.create_runtime_revision(reason)
        after=await repo.snapshot()
        assert repo.manifest['version']==VERSION and repo.manifest['runtime_fingerprint']==fingerprint()
        assert all(before[k]==after[k] for k in ['cash','available_cash','reserved_cash','realized_pnl','orders','positions'])
        assert orders==await repo.list_orders() and fills==await repo.list_fills()
        assert await repo.verify_invariants(INITIAL)==[] and after['control']=='PAUSED'
        async with repo.session_factory() as session:
            assert (await session.get(ShadowIdentityModel,1)).manifest_json==origin
            funding=await session.scalar(select(func.count()).select_from(JournalEventModel).where(JournalEventModel.event_type=='INITIAL_FUNDING'))
            assert funding==1
        print(json.dumps({'status':'PASS','origin_preserved':True,'funding_count':funding,
            'parent_profile_hash':parent,'profile_hash':digest(canonical(repo.manifest)),
            'runtime_fingerprint':fingerprint(),'profile':VERSION,'cash_eur':after['cash'],
            'realized_pnl_eur':after['realized_pnl'],'control':'PAUSED','orders_preserved':len(orders),
            'fills_preserved':len(fills),'reconciliation':[],'live_authorized':False}))
    finally:await service.close();await engine.dispose()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--expected-parent',required=True);parser.add_argument('--reason',required=True);args=parser.parse_args()
    asyncio.run(main(args.expected_parent,args.reason))
