"""Explicit Mac-only flat-account paper revision; no funding or parameter reset."""
import argparse
import asyncio
import json
import os

from sqlalchemy import func, select

from autotrader.config import get_settings
from autotrader.persistence.database import make_engine, make_session_factory
from autotrader.persistence.models import JournalEventModel, ShadowIdentityModel
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.personal_paper.policy import INITIAL
from autotrader.personal_paper.service import PersonalPaperService
from autotrader.research.data import canonical, digest


async def activate(expected_parent,reason):
    if os.environ.get('AUTOTRADER_MAC_REVISION')!='1':raise ValueError('explicit_mac_revision_invocation_required')
    settings=get_settings();engine=make_engine(settings)
    official=PersistentTradingRepository(make_session_factory(engine));service=PersonalPaperService(official,settings)
    try:
        old=await service.repository()
        if old is None or digest(canonical(old.manifest))!=expected_parent:raise ValueError('expected_parent_profile_mismatch')
        async with old.session_factory() as session:
            marker=await session.get(ShadowIdentityModel,1);origin=marker.manifest_json
            before_funding=await session.scalar(select(func.count()).select_from(JournalEventModel).where(JournalEventModel.event_type=='INITIAL_FUNDING'))
        before_orders=len(await old.list_orders());old_hash=digest(canonical(old.manifest))
        repo=await service.create_runtime_revision(reason)
        assert await repo.verify_invariants(INITIAL)==[]
        async with repo.session_factory() as session:
            marker=await session.get(ShadowIdentityModel,1);assert marker.manifest_json==origin
            after_funding=await session.scalar(select(func.count()).select_from(JournalEventModel).where(JournalEventModel.event_type=='INITIAL_FUNDING'))
        assert before_funding==after_funding==1 and len(await repo.list_orders())==before_orders
        await repo.set_control('resume')
        print(json.dumps({'status':'PASS','origin_preserved':True,'account_id':repo.account_id,'previous_profile_hash':old_hash,
            'active_profile_hash':digest(canonical(repo.manifest)),'active_profile':repo.manifest['version'],'frozen_at':repo.manifest['frozen_at'],
            'runtime_fingerprint':repo.manifest['runtime_fingerprint'],'funding_count':after_funding,'initial_funding_eur':'7000',
            'previous_orders_preserved':before_orders,'reconciliation':[],'control':'RUNNING','real_orders_authorized':False}))
    finally:await service.close();await engine.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--expected-parent-profile-hash',required=True);parser.add_argument('--reason',required=True);args=parser.parse_args()
    asyncio.run(activate(args.expected_parent_profile_hash,args.reason))
