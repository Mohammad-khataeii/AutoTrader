"""Compact history must preserve episode semantics and historical evidence."""
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from autotrader.api.episode_history import project_episode_events
from autotrader.persistence.models import SystemStateModel
from autotrader.raoe.analytics import episodes


async def seed(repo, bodies):
    async with repo.session_factory() as session,session.begin():
        for i,body in enumerate(bodies):
            session.add(SystemStateModel(key='raoe_event:projection-'+str(i),state='RECORDED',reason='synthetic_metadata_projection',
                created_at=datetime.fromisoformat(body['observed_at']),payload_json=json.dumps(body)))


async def test_compact_projection_preserves_real_episode_rules_and_full_saved_evidence(pg_repo):
    repo=pg_repo;stamp=datetime(2026,10,29,8,tzinfo=UTC)
    bodies=[]
    for i,(minutes,symbol,horizon,eligible,reason) in enumerate([
        (0,'AAA-EUR',21600,False,None),(5,'AAA-EUR',21600,True,'existing_position'),
        (90,'BBB-EUR',3600,True,None),(100,'BBB-EUR',3600,False,'exposure_cap'),
        (180,'BBB-EUR',3600,False,None),(360,'AAA-EUR',21600,False,None)]):
        bodies.append({'event_id':str(i),'symbol':symbol,'strategy_id':'RAOE_EARLY_RECOVERY',
            'observed_at':(stamp+timedelta(minutes=minutes)).isoformat(),'horizon_seconds':horizon,'rejection':reason,
            'evidence':{'entry_eligible':eligible,'depth_and_indicators_opaque_to_episode_rules':'x'*262144}})
    await seed(repo,bodies)
    async with repo.session_factory() as session:
        compact=await project_episode_events(session,stamp)
        original=(await session.scalars(select(SystemStateModel.payload_json).where(SystemStateModel.key.like('raoe_event:%')).order_by(SystemStateModel.created_at,SystemStateModel.key))).all()
    assert episodes(compact)==episodes(bodies)
    assert len(json.dumps(compact))<4000 and 'opaque' not in json.dumps(compact)
    assert [json.loads(row) for row in original]==bodies


async def test_projection_applies_cutoff_before_limit_and_does_not_include_other_states(pg_repo):
    repo=pg_repo;stamp=datetime(2026,10,29,8,tzinfo=UTC)
    bodies=[{'event_id':str(i),'symbol':'AAA-EUR','strategy_id':'RAOE_TREND_PULLBACK',
        'observed_at':(stamp+timedelta(minutes=i)).isoformat(),'horizon_seconds':21600,'evidence':{'entry_eligible':False}}
        for i in range(5)]
    await seed(repo,bodies)
    async with repo.session_factory() as session,session.begin():
        session.add(SystemStateModel(key='unrelated-to-episode-window',state='OBSERVING',reason='not_event',payload_json='not JSON'))
    async with repo.session_factory() as session:
        compact=await project_episode_events(session,stamp+timedelta(minutes=2),limit=2)
    assert [r['event_id'] for r in compact]==['2','3']
    assert episodes(compact)==episodes(bodies[2:4])


async def test_legacy_optional_fields_keep_default_horizon_and_eligibility_semantics(pg_repo):
    repo=pg_repo;stamp=datetime(2026,10,29,8,tzinfo=UTC)
    bodies=[{'symbol':'AAA-EUR','observed_at':stamp.isoformat()},
            {'event_id':'later','symbol':'AAA-EUR','strategy_id':'LEGACY','observed_at':(stamp+timedelta(hours=2)).isoformat(),
             'evidence':{'entry_eligible':None}},
            {'event_id':'other','symbol':'BBB-EUR','strategy_id':'LEGACY','observed_at':(stamp+timedelta(hours=3)).isoformat(),
             'horizon_seconds':'3600','rejection':'existing_position','evidence':{'entry_eligible':True}},
            {'event_id':'numeric','symbol':'CCC-EUR','strategy_id':'LEGACY','observed_at':(stamp+timedelta(hours=4)).isoformat(),
             'horizon_seconds':8000.5,'evidence':{'entry_eligible':0}}]
    await seed(repo,bodies)
    async with repo.session_factory() as session:compact=await project_episode_events(session,stamp)
    assert episodes(compact)==episodes(bodies)


@pytest.mark.parametrize('limit',[0,10001])
async def test_invalid_episode_window_is_rejected_before_query(pg_repo,limit):
    repo=pg_repo
    async with repo.session_factory() as session:
        with pytest.raises(ValueError,match='bounded_aware'):await project_episode_events(session,datetime.now(UTC),limit)
        with pytest.raises(ValueError,match='bounded_aware'):await project_episode_events(session,datetime(2026,10,29))
