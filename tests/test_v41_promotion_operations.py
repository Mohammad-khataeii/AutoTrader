from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest

from autotrader.api.main import create_app
from autotrader.config import Settings
from autotrader.domain import utc_now
from autotrader.persistence.operations import LeaseLostError
from autotrader.persistence.pilot import pilot_configuration
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.persistence.research_policy import promotion_error
from autotrader.research.artifacts import source_fingerprint
from autotrader.research.data import canonical, digest
from autotrader.research.strategies import VERSION, StrategyParameters
from test_v34_acceptance import buy


def research_fixture(root: Path, timeframe: str = '5m', passed: bool = True) -> dict:
    # Explicit test-only research artifact. Never used by a real paper deployment.
    parameters=StrategyParameters().payload()
    candidate={'strategy_id':'A_TREND_PULLBACK','strategy_version':VERSION,'frozen_parameters':parameters,
        'parameter_hash':digest(canonical(parameters)),'source_fingerprint':source_fingerprint()[0],
        'dataset_fingerprint':'unit-test-only','research_run_id':'fixture-research','research_timeframe':timeframe,
        'execution_assumptions_hash':digest(canonical({'fee_bps':'10','slippage_bps':'8','spread_bps':'10','volume_participation':'.01'})),
        'validation_status':'RESEARCH_PASSED' if passed else 'RESEARCH_REJECTED'}
    candidate['candidate_id']=digest(canonical(candidate))
    summary={'run_id':'fixture-research','source_fingerprint':candidate['source_fingerprint'],'verdict':'TEST FIXTURE',
        'passed_strategies':['A_TREND_PULLBACK'] if passed else [],
        'timeframes':{timeframe:{'strategies':{'A_TREND_PULLBACK':{'candidate':candidate,'out_of_sample':{'parameters':parameters},'gates':{'passed':passed}}}}}}
    root.mkdir(exist_ok=True)
    body=canonical(summary)
    (root/'summary.json').write_bytes(body)
    (root/'latest-run.json').write_bytes(canonical({'summary':'summary.json','summary_sha256':digest(body)}))
    return candidate


@pytest.mark.parametrize('timeframe', ['1d','4h','5m'])
async def test_explicit_approval_timeframe_restart_and_durable_suspension(pg_repo: PersistentTradingRepository,tmp_path: Path,timeframe: str) -> None:
    await pg_repo.initialize_portfolio(D(500))
    candidate=research_fixture(tmp_path,timeframe)
    await pg_repo.configure_research_policy(tmp_path,test_environment=False,approved=set())
    assert await pg_repo.frozen_runtime_parameters()=={}
    if timeframe!='5m':
        with pytest.raises(ValueError,match='current_runtime'):
            await pg_repo.decide_promotion(candidate['candidate_id'],approve=True,actor='unit-operator',reason='Explicit isolated approval test.')
        return
    await pg_repo.decide_promotion(candidate['candidate_id'],approve=True,actor='unit-operator',reason='Explicit isolated approval test.')
    reopened=PersistentTradingRepository(pg_repo.session_factory)
    await reopened.configure_research_policy(tmp_path,test_environment=False,approved=set())
    assert (await reopened.frozen_runtime_parameters())['A_TREND_PULLBACK']==StrategyParameters()
    member=(await reopened.promotion_candidates())[0]
    policy={'require_validation':True,'allowed_strategy_ids':['A_TREND_PULLBACK'],'members':{'A_TREND_PULLBACK':member}}
    evidence={'timeframe':'5m','strategy_version':VERSION,'parameters':StrategyParameters().payload()}
    assert promotion_error(policy,'A_TREND_PULLBACK',evidence,D(10),D(8)) is None
    assert promotion_error(policy,'A_TREND_PULLBACK',{**evidence,'parameters':{}},D(10),D(8))=='strategy_parameter_mismatch'
    assert promotion_error(policy,'A_TREND_PULLBACK',evidence,D(11),D(8))=='strategy_execution_assumptions_mismatch'
    member['source_fingerprint']='changed-source'
    assert promotion_error(policy,'A_TREND_PULLBACK',evidence,D(10),D(8))=='strategy_source_mismatch'
    await reopened.decide_promotion(candidate['candidate_id'],approve=False,actor='unit-operator',reason='Suspend this isolated research candidate.')
    await reopened.configure_research_policy(tmp_path,test_environment=False,approved={'A_TREND_PULLBACK'})
    assert await reopened.frozen_runtime_parameters()=={}
    assert (await reopened.promotion_candidates())[0]['state']=='PAPER_SUSPENDED'
    assert not (await buy(reopened,'blocked-after-suspension')).accepted
    assert await reopened.verify_invariants(D(500))==[]


async def test_failed_research_never_approves(pg_repo: PersistentTradingRepository,tmp_path: Path) -> None:
    await pg_repo.initialize_portfolio(D(500))
    candidate=research_fixture(tmp_path,passed=False)
    await pg_repo.configure_research_policy(tmp_path,test_environment=False,approved={'A_TREND_PULLBACK'})
    with pytest.raises(ValueError,match='current_runtime'):
        await pg_repo.decide_promotion(candidate['candidate_id'],approve=True,actor='operator',reason='Cannot force failed research into approval.')
    assert (await pg_repo.promotion_candidates())[0]['state']=='RESEARCH_REJECTED'


async def test_single_coordinator_and_old_owner_financial_fence(pg_repo: PersistentTradingRepository,monkeypatch: pytest.MonkeyPatch) -> None:
    await pg_repo.initialize_portfolio(D(500))
    now=[utc_now()]
    async def clock(session: object):
        return now[0]
    monkeypatch.setattr('autotrader.persistence.operations.quota_now',clock)
    peers=[PersistentTradingRepository(pg_repo.session_factory) for _ in range(8)]
    claimed=await asyncio.gather(*(peer.claim_coordinator(str(i)) for i,peer in enumerate(peers)))
    assert sum(claimed)==1
    owner=peers[claimed.index(True)]
    now[0]+=timedelta(seconds=16)
    assert await pg_repo.claim_coordinator('replacement')
    with pytest.raises(LeaseLostError):
        await buy(owner,'stale-owner-must-not-post')
    assert (await pg_repo.snapshot())['equity']=='500.000000000000'
    assert await pg_repo.verify_invariants(D(500))==[]


async def test_shared_login_cooldown_across_two_api_instances(pg_repo: PersistentTradingRepository,monkeypatch: pytest.MonkeyPatch) -> None:
    await pg_repo.initialize_portfolio(D(500))
    monkeypatch.setenv('ENVIRONMENT','test')
    monkeypatch.setenv('DATABASE_URL',pg_repo.test_database_url)
    app1,app2=create_app(),create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app1),base_url='http://test') as one, httpx.AsyncClient(transport=httpx.ASGITransport(app=app2),base_url='http://test') as two:
        assert [(await one.get('/api/settings',auth=('admin','wrong'))).status_code for _ in range(3)]==[401]*3
        assert [(await two.get('/api/settings',auth=('admin','wrong'))).status_code for _ in range(2)]==[401]*2
        assert (await one.get('/api/settings',auth=('admin','change-me'))).status_code==429
    await app1.state.engine.dispose()
    await app2.state.engine.dispose()


async def test_pilot_freezes_configuration_reports_actual_cash_and_separates_synthetic(pg_repo: PersistentTradingRepository,tmp_path: Path) -> None:
    from autotrader.clock import at
    await pg_repo.initialize_portfolio(D(500))
    config=pilot_configuration(Settings(environment='test',research_root=str(tmp_path)))
    pilot=await pg_repo.start_pilot('engineering-test-only',config,test_environment=True)
    assert pilot['mode']=='SYNTHETIC_ACCEPTANCE'
    assert (await pg_repo.start_pilot('engineering-test-only',config,test_environment=True))['pilot_id']==pilot['pilot_id']
    with at(utc_now()+timedelta(minutes=1)):
        await pg_repo.capture_pilot_snapshot(test_environment=True,current_config=config)
        report=await pg_repo.pilot_report(pilot['pilot_id'])
        assert report['net_portfolio_pnl']=='0E-12' or D(report['net_portfolio_pnl'])==0
        assert report['fills']==0 and report['fees']=='0' and not report['thirty_days_elapsed']
        assert report['benchmarks']['BTC-EUR']['status']=='INSUFFICIENT_PROSPECTIVE_OBSERVATIONS'
        assert report['mode']=='SYNTHETIC_ACCEPTANCE'
        reopened=PersistentTradingRepository(pg_repo.session_factory)
        assert len(await reopened.pilots())==1
        await reopened.capture_pilot_snapshot(test_environment=True,current_config={**config,'costs':{'fee_bps':'99'}})
        assert (await reopened.pilots())[0]['state']=='INTERRUPTED'
    assert await pg_repo.verify_invariants(D(500))==[]
