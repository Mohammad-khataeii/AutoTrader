"""Account-locked paid-call quotas; uncertain provider outcomes retain reservations."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any

from sqlalchemy import func, or_, select

from autotrader.domain import new_id, utc_now
from autotrader.persistence.accounting import aware
from autotrader.persistence.models import (
    AIBudgetModel,
    AIUsageModel,
    SystemIncidentModel,
    SystemStateModel,
)


def dollars(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.00000001'), rounding=ROUND_CEILING)


async def quota_now(session: Any) -> datetime:
    # A single database clock avoids quota disagreement across worker machines.
    if session.bind.dialect.name == 'postgresql':
        return aware(await session.scalar(select(func.clock_timestamp())))
    return utc_now()  # Unpaid integration-only SQLite operation.


class AIBudgetRepositoryMixin:
    session_factory: Any

    async def _lock_account(self, session: Any) -> Any:
        raise NotImplementedError

    async def _quota_counts(self, session: Any, now: datetime, exclude: str | None = None) -> tuple[int, int]:
        query=select(AIUsageModel.quota_timestamp).where(AIUsageModel.provider=='openai',
            AIUsageModel.status!='FAILED_CONFIRMED_NO_CHARGE',
            AIUsageModel.quota_timestamp>=min(now.replace(hour=0,minute=0,second=0,microsecond=0),now-timedelta(hours=1)))
        if exclude:
            query=query.where(AIUsageModel.request_id!=exclude)
        times=[aware(t) for t in (await session.scalars(query)).all()]
        midnight=now.replace(hour=0,minute=0,second=0,microsecond=0)
        return sum(t>=midnight for t in times),sum(t>now-timedelta(hours=1) for t in times)

    @staticmethod
    def _quota_rejection(session: Any, reason: str) -> None:
        session.add(SystemIncidentModel(incident_id=new_id('aiquota'),severity='INFO',status='AI_QUOTA_REJECTED',
            message=reason,payload_json='{}'))

    async def reserve_ai_budget(self, amount: Decimal, model: str, symbol: str,
                                prices: dict[str, str], limit: Decimal = Decimal('10'), *,
                                max_per_day: int = 30, max_per_hour: int = 6,
                                event_fingerprint: str | None = None, category: str = 'qualified_candidate',
                                estimated_input_tokens: int = 0, reserved_output_tokens: int = 0,
                                portfolio_reserve_daily: int = 0, portfolio_reserve_hourly: int = 0) -> str | None:
        if (not amount.is_finite() or amount<=0 or not limit.is_finite() or not 0<=limit<=10 or
            not 0<=max_per_day<=30 or not 0<=max_per_hour<=6 or min(estimated_input_tokens,reserved_output_tokens)<0):
            raise ValueError('Invalid AI budget policy.')
        async with self.session_factory() as session,session.begin():
            if session.bind.dialect.name!='postgresql':
                raise ValueError('Paid AI quota requires PostgreSQL.')
            await self._lock_account(session)
            now=await quota_now(session)
            review=await session.get(SystemStateModel,'ai_billing_review')
            if review and review.state=='REQUIRED':
                self._quota_rejection(session,'billing_review_required')
                return None
            if event_fingerprint:
                duplicate=await session.scalar(select(AIUsageModel.request_id).where(
                    AIUsageModel.event_fingerprint==event_fingerprint,
                    AIUsageModel.status!='FAILED_CONFIRMED_NO_CHARGE',
                    or_(AIUsageModel.quota_timestamp>now-timedelta(minutes=15),
                        AIUsageModel.status.in_(['RESERVED','SENT','OUTCOME_UNKNOWN','UNKNOWN']))).limit(1))
                if duplicate:
                    self._quota_rejection(session,'duplicate_ai_event')
                    return None
            daily,hourly=await self._quota_counts(session,now)
            if daily>=max_per_day or hourly>=max_per_hour:
                self._quota_rejection(session,'daily_quota_exhausted' if daily>=max_per_day else 'rolling_hour_quota_exhausted')
                return None
            if category!='portfolio_risk' and (daily>=max(0,max_per_day-portfolio_reserve_daily) or hourly>=max(0,max_per_hour-portfolio_reserve_hourly)):
                self._quota_rejection(session,'capacity_reserved_for_portfolio_risk')
                return None
            month=now.strftime('%Y-%m')
            budget=await session.get(AIBudgetModel,month,with_for_update=True)
            if budget is None:
                budget=AIBudgetModel(month=month,spent=Decimal(0),reserved=Decimal(0))
                session.add(budget)
                await session.flush()
            if budget.spent+budget.reserved+dollars(amount)>limit:
                self._quota_rejection(session,'monthly_budget_exhausted')
                return None
            budget.reserved+=dollars(amount)
            request_id=new_id('req')
            session.add(AIUsageModel(request_id=request_id,month=month,model=model,status='RESERVED',
                reserved_cost=dollars(amount),input_tokens=0,output_tokens=0,cached_input_tokens=0,cache_write_tokens=0,
                candidate_symbol=symbol,provider='openai',pricing_json=json.dumps(prices),created_at=now,
                quota_timestamp=now,event_fingerprint=event_fingerprint,request_category=category,
                estimated_input_tokens=estimated_input_tokens,reserved_output_tokens=reserved_output_tokens,cache_status='MISS'))
            return request_id

    async def ai_request_sent(self, request_id: str, *, max_per_day: int = 30, max_per_hour: int = 6) -> None:
        async with self.session_factory() as session,session.begin():
            await self._lock_account(session)
            usage=await session.get(AIUsageModel,request_id,with_for_update=True)
            if usage is None or usage.status!='RESERVED':
                raise ValueError('Request is not reserved; automatic retry forbidden.')
            now=await quota_now(session)
            daily,hourly=await self._quota_counts(session,now,exclude=request_id)
            if now.strftime('%Y-%m')!=usage.month or daily>=min(max_per_day,30) or hourly>=min(max_per_hour,6):
                raise ValueError('Quota changed before submission; no provider call allowed.')
            usage.quota_timestamp=now
            usage.status='SENT'

    async def finish_ai_request(self, request_id: str, *, input_tokens: int = 0,
                                output_tokens: int = 0, cached_tokens: int = 0,
                                cache_write_tokens: int = 0, cost: Decimal | None = None,
                                error: str | None = None, provider_response_id: str | None = None) -> None:
        async with self.session_factory() as session,session.begin():
            await self._lock_account(session)
            usage=await session.get(AIUsageModel,request_id,with_for_update=True)
            if usage is None:
                raise ValueError('Unknown AI request.')
            if usage.status in {'COMPLETED','FAILED_CHARGED','RECONCILED','FAILED_CONFIRMED_NO_CHARGE'}:
                return
            usage.error=error
            usage.provider_response_id=provider_response_id or usage.provider_response_id
            if cost is None:
                usage.status='OUTCOME_UNKNOWN'
                return
            if cost<0 or not cost.is_finite() or min(input_tokens,output_tokens,cached_tokens,cache_write_tokens)<0 or cached_tokens+cache_write_tokens>input_tokens:
                raise ValueError('Invalid provider usage.')
            budget=await session.get(AIBudgetModel,usage.month,with_for_update=True)
            budget.reserved-=usage.reserved_cost
            budget.spent+=dollars(cost)
            usage.actual_cost=dollars(cost)  # Token-derived estimate, explicitly not an invoice.
            usage.input_tokens,usage.output_tokens,usage.cached_input_tokens=input_tokens,output_tokens,cached_tokens
            usage.cache_write_tokens=cache_write_tokens
            usage.status='COMPLETED'
            if cost>usage.reserved_cost:
                usage.error='Configured price/token bound violated; paid requests require operator review.'
                review=await session.get(SystemStateModel,'ai_billing_review')
                if review:
                    review.state='REQUIRED'
                else:
                    session.add(SystemStateModel(key='ai_billing_review',state='REQUIRED',reason='reservation_bound_exceeded',payload_json='{}'))

    async def reconcile_ai_request(self, request_id: str, *, reported_cost: Decimal, actor: str, evidence: str) -> None:
        if not reported_cost.is_finite() or reported_cost<0 or not actor or len(evidence)<20:
            raise ValueError('Audited billing evidence and nonnegative cost are required.')
        async with self.session_factory() as session,session.begin():
            await self._lock_account(session)
            usage=await session.get(AIUsageModel,request_id,with_for_update=True)
            if usage is None:
                raise ValueError('Unknown AI request.')
            if usage.status in {'RECONCILED','FAILED_CONFIRMED_NO_CHARGE'}:
                if usage.actual_reported_cost!=dollars(reported_cost):
                    raise ValueError('Already reconciled to different billing evidence.')
                return
            budget=await session.get(AIBudgetModel,usage.month,with_for_update=True)
            if usage.actual_cost is None:
                budget.reserved-=usage.reserved_cost
            else:
                budget.spent-=usage.actual_cost
            budget.spent+=dollars(reported_cost)
            usage.actual_cost=usage.actual_reported_cost=dollars(reported_cost)
            usage.status='FAILED_CONFIRMED_NO_CHARGE' if reported_cost==0 else 'RECONCILED'
            session.add(SystemIncidentModel(incident_id=new_id('billing'),severity='INFO',status='AI_BILLING_RECONCILED',
                message='audited_provider_billing',payload_json=json.dumps({'request_id':request_id,'actor':actor,'evidence':evidence,'cost':str(reported_cost)})))
            # An over-bound discrepancy requires a separate operator pricing review.

    async def ai_budget_status(self, limit: Decimal = Decimal('10'), *, max_per_day: int = 30, max_per_hour: int = 6) -> dict[str, Any]:
        async with self.session_factory() as session:
            now=await quota_now(session)
            month=now.strftime('%Y-%m')
            budget=await session.get(AIBudgetModel,month)
            rows=(await session.scalars(select(AIUsageModel).where(AIUsageModel.month==month))).all()
            daily,hourly=await self._quota_counts(session,now)
            spent,reserved=(budget.spent,budget.reserved) if budget else (Decimal(0),Decimal(0))
            next_month=(now.replace(day=28)+timedelta(days=4)).replace(day=1,hour=0,minute=0,second=0,microsecond=0)
            # Rolling windows may straddle the month boundary.
            oldest=await session.scalar(select(func.min(AIUsageModel.quota_timestamp)).where(
                AIUsageModel.quota_timestamp>now-timedelta(hours=1),AIUsageModel.status!='FAILED_CONFIRMED_NO_CHARGE'))
            rejects=await session.scalar(select(func.count()).select_from(SystemIncidentModel).where(
                SystemIncidentModel.status=='AI_QUOTA_REJECTED',SystemIncidentModel.created_at>=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)))
            metrics=await session.get(SystemStateModel,'ai_cache_metrics')
            success=max((aware(r.created_at).isoformat() for r in rows if r.status in {'COMPLETED','RECONCILED'}),default=None)
            review=await session.get(SystemStateModel,'ai_billing_review')
            return {'month':month,'spent_usd':str(spent),'estimated_spend_usd':str(spent),'reserved_usd':str(reserved),
                'confirmed_spend_usd':str(sum((r.actual_reported_cost or Decimal(0) for r in rows),Decimal(0))),
                'remaining_usd':str(max(min(limit,Decimal(10))-spent-reserved,Decimal(0))),'requests':len(rows),
                'daily_used':daily,'daily_limit':max_per_day,'daily_remaining':max(0,max_per_day-daily),
                'rolling_hour_used':hourly,'hourly_limit':max_per_hour,'hourly_remaining':max(0,max_per_hour-hourly),
                'daily_reset_at':(now.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)).isoformat(),
                'next_hourly_release_at':(aware(oldest)+timedelta(hours=1)).isoformat() if oldest else None,
                'monthly_reset_at':next_month.isoformat(),'clock':'PostgreSQL UTC clock' if session.bind.dialect.name=='postgresql' else 'integration clock',
                'input_tokens':sum(r.input_tokens for r in rows),'output_tokens':sum(r.output_tokens for r in rows),
                'cached_input_tokens':sum(r.cached_input_tokens for r in rows),'cache_write_tokens':sum(r.cache_write_tokens for r in rows),
                'cache_hits':json.loads(metrics.payload_json).get('hits',0) if metrics else 0,
                'rejected_requests':int(rejects or 0),'last_successful_analysis':success,
                'billing_review_required':bool(review and review.state=='REQUIRED'),
                'errors':[{'request_id':r.request_id,'status':r.status,'error':r.error} for r in rows if r.error or r.status in {'UNKNOWN','OUTCOME_UNKNOWN'}]}
