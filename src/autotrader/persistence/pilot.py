"""Prospective observations reference the existing paper ledger; they never fund it."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

from sqlalchemy import select

from autotrader.domain import new_id, utc_now
from autotrader.persistence.accounting import aware
from autotrader.persistence.models import (
    AIUsageModel,
    FillModel,
    JournalEventModel,
    MarketCandle,
    OrderModel,
    PositionModel,
    SystemIncidentModel,
    SystemStateModel,
    TradingDecisionModel,
)
from autotrader.research.artifacts import source_fingerprint
from autotrader.research.data import canonical, digest


def pilot_configuration(settings: Any) -> dict[str, Any]:
    catalog=Path(settings.research_root)/'catalog.json'
    datasets=json.loads(catalog.read_bytes()).get('manifests',[]) if catalog.exists() else []
    return {'application_version':'4.1.0','source_fingerprint':source_fingerprint()[0],
        'market_data_source':'revolut-x-public','signal_timeframe':'5m','initial_cash_eur':'500',
        'historical_datasets':sorted(m['dataset_version'] for m in datasets),
        'ai_provider':settings.ai_provider.value,'ai_model':settings.ai_model,
        'scan_seconds':settings.worker_scan_interval_seconds,'position_seconds':settings.worker_position_interval_seconds,
        'costs':{'fee_bps':str(settings.default_fee_bps),'slippage_bps':str(settings.default_slippage_bps),'spread_bps':'10'},
        'risk_limits':{key:str(getattr(settings,key)) for key in ('max_position_size_eur','max_total_open_exposure_eur',
            'min_uncommitted_reserve_eur','max_planned_loss_per_trade_eur','daily_loss_threshold_eur','weekly_loss_threshold_eur',
            'max_simultaneous_positions','max_new_entries_per_day')}}


class PilotMixin:
    session_factory: Any
    _lock_account: Any
    _valuation: Any
    account_id: str

    async def start_pilot(self, request_id: str, config: dict[str, Any], *, test_environment: bool) -> dict[str, Any]:
        identity='pilot_'+digest(request_id.encode())[:32]
        async with self.session_factory() as session,session.begin():
            await self._lock_account(session)
            existing=await session.get(SystemStateModel,'pilot:'+identity)
            if existing:
                payload=json.loads(existing.payload_json)
                if payload['config_fingerprint']!=digest(canonical(config)):
                    raise ValueError('Pilot request identity already has another frozen configuration.')
                return dict(payload)
            active=await session.scalar(select(SystemStateModel.key).where(SystemStateModel.key.like('pilot:%'),SystemStateModel.state=='ACTIVE').limit(1))
            if active:
                raise ValueError('An active pilot already exists; preserve its observation period.')
            policy=await session.get(SystemStateModel,'research_entry_policy')
            entry=json.loads(policy.payload_json) if policy else {}
            mode='SYNTHETIC_ACCEPTANCE' if test_environment else 'PAPER_FORWARD' if entry.get('allowed_strategy_ids') else 'RESEARCH_ONLY'
            if config.get('source_fingerprint')!=source_fingerprint()[0]:
                raise ValueError('Pilot configuration source mismatch.')
            now=utc_now()
            payload={'pilot_id':identity,'mode':mode,'started_at':now.isoformat(),
                'planned_end_at':(now+timedelta(days=30)).isoformat(),'config':config,'config_fingerprint':digest(canonical(config)),
                'strategy_members':entry.get('members',{}),'starting_snapshot':await self._valuation(session),
                'performance_label':'ENGINEERING SIMULATION — EXCLUDE FROM FORWARD PERFORMANCE' if test_environment else 'PROSPECTIVE REAL-MARKET PAPER OBSERVATION',
                'interruptions':[]}
            session.add(SystemStateModel(key='pilot:'+identity,state='ACTIVE',reason='explicit_start_pilot',payload_json=json.dumps(payload)))
            session.add(SystemIncidentModel(incident_id=new_id('pilotstart'),severity='INFO',status='PILOT_STARTED',message=identity,payload_json=json.dumps({'config_fingerprint':payload['config_fingerprint'],'mode':mode})))
            return payload

    async def pilots(self) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            rows=(await session.scalars(select(SystemStateModel).where(SystemStateModel.key.like('pilot:%')))).all()
            return [{**json.loads(r.payload_json),'state':r.state,'reason':r.reason} for r in rows]

    async def capture_pilot_snapshot(self, *, test_environment: bool = False, current_config: dict[str, Any] | None = None) -> None:
        current_source=source_fingerprint()[0]
        async with self.session_factory() as session,session.begin():
            await self._lock_account(session)
            pilots=(await session.scalars(select(SystemStateModel).where(SystemStateModel.key.like('pilot:%'),SystemStateModel.state=='ACTIVE'))).all()
            policy=await session.get(SystemStateModel,'research_entry_policy')
            members=json.loads(policy.payload_json).get('members',{}) if policy else {}
            for row in pilots:
                pilot=json.loads(row.payload_json)
                now=utc_now()
                mismatch=(pilot['config']['source_fingerprint']!=current_source or pilot['strategy_members']!=members or
                    (current_config is not None and digest(canonical(current_config))!=pilot['config_fingerprint']) or
                    (pilot['mode']=='SYNTHETIC_ACCEPTANCE')!=test_environment)
                if mismatch:
                    row.state,row.reason='INTERRUPTED','material_configuration_changed'
                    pilot['interruptions'].append({'timestamp':now.isoformat(),'reason':row.reason})
                    row.payload_json=json.dumps(pilot)
                    continue
                if now>=datetime.fromisoformat(pilot['planned_end_at']):
                    row.state,row.reason='COMPLETED','thirty_day_window_elapsed'
                snapshot=await self._valuation(session)
                operation=await session.get(SystemStateModel,'operation')
                session.add(SystemStateModel(key='pilotobs:'+pilot['pilot_id'][6:22]+':'+new_id('snap'),state=pilot['mode'],reason='prospective_observation',
                    payload_json=json.dumps({'pilot_id':pilot['pilot_id'],'timestamp':now.isoformat(),'snapshot':snapshot,
                        'config_fingerprint':pilot['config_fingerprint'],'operation':operation.state if operation else 'INITIALIZING'})))
        # Generate all missed UTC daily summaries after a restart, without inventing
        # missing observations. Reports can explicitly have unavailable equity.
        for pilot in await self.pilots():
            day=datetime.fromisoformat(pilot['started_at']).date()
            last=min(utc_now().date()-timedelta(days=1),datetime.fromisoformat(pilot['planned_end_at']).date())
            while day<=last:
                key='pilotreport:'+pilot['pilot_id'][6:22]+':'+day.isoformat()
                async with self.session_factory() as session:
                    exists=await session.get(SystemStateModel,key)
                if exists is None:
                    report=await self.pilot_report(pilot['pilot_id'],day)
                    async with self.session_factory() as session,session.begin():
                        await self._lock_account(session)
                        if await session.get(SystemStateModel,key) is None:
                            session.add(SystemStateModel(key=key,state='GENERATED',reason='utc_daily_report',payload_json=json.dumps(report)))
                day+=timedelta(days=1)

    async def pilot_report(self, pilot_id: str, day: date | None = None) -> dict[str, Any]:
        async with self.session_factory() as session:
            row=await session.get(SystemStateModel,'pilot:'+pilot_id)
            if row is None:
                raise ValueError('Unknown pilot.')
            pilot=json.loads(row.payload_json)
            started=datetime.fromisoformat(pilot['started_at'])
            planned_end=datetime.fromisoformat(pilot['planned_end_at'])
            end=min(utc_now(),planned_end)
            start=started
            if day:
                start=max(started,datetime.combine(day,datetime.min.time(),tzinfo=UTC))
                end=min(end,datetime.combine(day+timedelta(days=1),datetime.min.time(),tzinfo=UTC))
            if end<=start:
                raise ValueError('Report interval is outside the prospective pilot window.')
            rows=(await session.scalars(select(SystemStateModel).where(SystemStateModel.key.like('pilotobs:'+pilot_id[6:22]+':%')))).all()
            observations=sorted([json.loads(r.payload_json) for r in rows],key=lambda r:r['timestamp'])
            selected=[r for r in observations if start<=datetime.fromisoformat(r['timestamp'])<=end]
            previous=[r for r in observations if datetime.fromisoformat(r['timestamp'])<=start]
            opening=previous[-1]['snapshot'] if previous else pilot['starting_snapshot'] if start==started else None
            ending=selected[-1]['snapshot'] if selected else None
            valid=[Decimal(r['snapshot']['equity']) for r in selected if r['snapshot'].get('equity') and r['snapshot'].get('valuation_degraded')!='true']
            peak=Decimal(opening['equity']) if opening and opening.get('equity') else (valid[0] if valid else Decimal(0))
            drawdown=Decimal(0)
            for value in valid:
                peak=max(peak,value)
                drawdown=max(drawdown,(peak-value)/peak if peak else Decimal(0))
            fills=(await session.scalars(select(FillModel).where(FillModel.account_id==self.account_id,FillModel.created_at>=start,FillModel.created_at<end))).all()
            events=(await session.scalars(select(JournalEventModel).where(JournalEventModel.account_id==self.account_id,JournalEventModel.created_at>=start,JournalEventModel.created_at<end))).all()
            decisions=(await session.scalars(select(TradingDecisionModel).where(TradingDecisionModel.created_at>=start,TradingDecisionModel.created_at<end))).all()
            incidents=(await session.scalars(select(SystemIncidentModel).where(SystemIncidentModel.created_at>=start,SystemIncidentModel.created_at<end))).all()
            usage=(await session.scalars(select(AIUsageModel).where(AIUsageModel.quota_timestamp>=start,AIUsageModel.quota_timestamp<end))).all()
            orders=(await session.scalars(select(OrderModel).where(OrderModel.account_id==self.account_id,OrderModel.created_at>=start,OrderModel.created_at<end))).all()
            closed=(await session.scalars(select(PositionModel).where(PositionModel.account_id==self.account_id,
                PositionModel.closed_at>=start,PositionModel.closed_at<end))).all()
            executions={o.order_id:json.loads(o.execution_json) for o in orders}
            slippage=Decimal(0)
            spread=Decimal(0)
            for fill in fills:
                execution=executions.get(fill.order_id,{})
                bps=Decimal(execution.get('slippage_bps','0'))
                signed=bps if fill.side=='BUY' else -bps
                raw_price=fill.price/(1+signed/10000)
                slippage+=abs(fill.price-raw_price)*fill.quantity
                quality=execution.get('execution_quality',{})
                if quality.get('best_ask') and quality.get('best_bid'):
                    spread+=(Decimal(quality['best_ask'])-Decimal(quality['best_bid']))/2*fill.quantity
            times=[start]+[datetime.fromisoformat(o['timestamp']) for o in selected]+[end]
            gaps=[{'start':a.isoformat(),'end':b.isoformat(),'seconds':(b-a).total_seconds()} for a,b in pairwise(times) if (b-a).total_seconds()>120]
            realized=[e.realized_pnl_delta for e in events if e.realized_pnl_delta]
            by_strategy: dict[str, str]={}
            for order in orders:
                strategy=json.loads(order.execution_json).get('strategy_id','UNAVAILABLE')
                pnl=sum((e.realized_pnl_delta for e in events if e.order_id==order.order_id),Decimal(0))
                by_strategy[strategy]=str(Decimal(by_strategy.get(strategy,'0'))+pnl)
            benchmarks: dict[str, Any]={'CASH':{'capital_eur':'500','net_pnl':'0'}}
            for symbol in ('BTC-EUR','ETH-EUR'):
                candles=(await session.scalars(select(MarketCandle).where(MarketCandle.symbol==symbol,MarketCandle.timeframe=='5m',MarketCandle.timestamp>=start,MarketCandle.timestamp+timedelta(minutes=5)<=end).order_by(MarketCandle.timestamp))).all()
                if len(candles)<2:
                    benchmarks[symbol]={'status':'INSUFFICIENT_PROSPECTIVE_OBSERVATIONS'}
                    continue
                costs=pilot['config'].get('costs',{})
                fee=Decimal(costs.get('fee_bps','10'))/10000
                slip=Decimal(costs.get('slippage_bps','8'))/10000
                spread=Decimal(costs.get('spread_bps','10'))/20000
                value=Decimal(500)*(candles[-1].close*(1-spread)*(1-slip)*(1-fee))/(candles[0].close*(1+spread)*(1+slip)*(1+fee))
                benchmarks[symbol]={'capital_eur':'500','net_pnl':str(value-500),'first_completed_start':aware(candles[0].timestamp).isoformat(),'last_completed_start':aware(candles[-1].timestamp).isoformat(),'source':candles[0].source,'assumption':'Separate EUR500 buy-and-hold reference at observed completed closes, modeled fees/spread/slippage; different exposure from bot.'}
            pnl=str(Decimal(ending['equity'])-Decimal(opening['equity'])) if opening and ending and opening.get('equity') and ending.get('equity') else None
            return {'pilot_id':pilot_id,'mode':pilot['mode'],'performance_label':pilot['performance_label'],'state':row.state,
                'start':start.isoformat(),'end_exclusive':end.isoformat(),'generated_at':utc_now().isoformat(),
                'config_fingerprint':pilot['config_fingerprint'],'elapsed_days':(end-started).total_seconds()/86400,
                'thirty_days_elapsed':utc_now()>=planned_end,'interruptions':pilot['interruptions'],
                'starting_snapshot':opening,'ending_snapshot':ending,'net_portfolio_pnl':pnl,
                'observed_max_drawdown':str(drawdown) if valid else None,'observations':len(selected),
                'fees':str(sum((f.fee for f in fills),Decimal(0))),'fills':len(fills),'buy_fills':sum(f.side=='BUY' for f in fills),
                'closed_trades':len(closed),'closed_trade_win_rate':sum(p.realized_pnl>0 for p in closed)/len(closed) if closed else None,
                'modeled_slippage_cost':str(slippage),'observed_spread_cost':str(spread),
                'worker_downtime':'See observation gaps and incident timestamps; unobserved periods are not asserted to be exact downtime.',
                'research_policy_status':'RESEARCH_ONLY' if not pilot['strategy_members'] else 'FROZEN_APPROVED_MEMBERS',
                'realized_pnl':str(sum(realized,Decimal(0))),'largest_realized_exit_loss':str(min(realized)) if realized else None,
                'profitable_exit_postings':sum(p>0 for p in realized),'losing_exit_postings':sum(p<0 for p in realized),
                'win_loss_unit':'Realized exit postings including partial fills; not independent completed trades.',
                'strategy_realized_pnl':by_strategy,'rejected_opportunities':sum(not d.accepted for d in decisions),
                'observation_gaps':gaps,'unobserved_seconds':sum(g['seconds'] for g in gaps),
                'incidents':[{'timestamp':aware(i.created_at).isoformat(),'state':i.status,'message':i.message} for i in incidents],
                'ai_requests':len(usage),'ai_estimated_cost':str(sum((u.actual_cost or u.reserved_cost for u in usage),Decimal(0))),
                'ai_confirmed_cost':str(sum((u.actual_reported_cost or Decimal(0) for u in usage),Decimal(0))),
                'benchmarks':benchmarks,'limitations':'Observed drawdown only; gaps are not reconstructed. No claim of statistical significance or completed 30-day pilot. Synthetic acceptance requires a separate database and is excluded by mode.'}
