"""Rank causal candidates, reserve shared capital, submit durable virtual orders."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from autotrader.domain import DecisionAction, TradingDecision, quantize_down, utc_now
from autotrader.execution_gateway import PaperExecutionGateway
from autotrader.indicators import calculate_features
from autotrader.market_data.revolut import MarketDataError
from autotrader.opportunity.engine import SuccessorOpportunityEngine, SuccessorParameters
from autotrader.opportunity.features import enrich
from autotrader.opportunity.runtime import restore_decision, restore_signal
from autotrader.persistence.models import (
    ExitPlanModel,
    StrategySignalModel,
    SystemStateModel,
    TradingDecisionModel,
)
from autotrader.persistence.repository import _json
from autotrader.personal_paper.policy import INITIAL, LIMITS, fingerprint
from autotrader.personal_paper.selection import ranking, reviewed_signal
from autotrader.personal_paper.service import PersonalPaperService
from autotrader.portfolio import Portfolio
from autotrader.position_manager import PositionManager
from autotrader.research.data import canonical, digest
from autotrader.risk import RiskEngine

D = Decimal


class PersonalPaperRuntime:
    def __init__(self, service: PersonalPaperService, market: Any, owner: str):
        self.service, self.market, self.owner = service, market, owner

    def gateway(self, repo: Any) -> PaperExecutionGateway:
        return PaperExecutionGateway(repo, market_data=self.market, risk_engine=RiskEngine(LIMITS),
            initial_cash=INITIAL, fee_bps=D(repo.manifest['fee_bps']), slippage_bps=D(repo.manifest['slippage_bps']))

    async def renew(self) -> None:
        repo = await self.service.repository()
        if repo:
            await repo.claim_coordinator(self.owner)

    async def monitor(self) -> None:
        repo = await self.service.repository()
        if not repo or not await repo.claim_coordinator(self.owner):
            return
        await repo.recover_pending_orders()
        await PositionManager(repository=repo, market_data=self.market, execution_gateway=self.gateway(repo)).monitor_once()
        await repo.snapshot()
        await repo.worker_heartbeat(key='position_monitor')

    async def scan(self, candidates: list[Any]) -> None:
        repo = await self.service.repository()
        if not repo or not await repo.claim_coordinator(self.owner):
            return
        if repo.manifest['runtime_fingerprint'] != fingerprint():
            await repo.operation_state('ENTRY_SUSPENDED', 'paper_frozen_runtime_changed_new_experiment_required')
            return
        from autotrader.market_data.synchronization import align_candidate, benchmark_features
        cycle = await self.market.evaluation_context(candidates)
        prepared, failures = [], []
        # A held coin can leave the scanner shortlist. Refresh its closed
        # candles in the scan task; five-second protective monitoring never
        # waits for historical downloads or other strategies.
        observed = {c.market.pair.symbol for c in candidates}
        for position in await repo.list_positions():
            if position.closed_at is None and position.quantity > 0 and position.symbol not in observed:
                try:
                    pair = await self.market.resolve_pair(position.symbol)
                    if pair is None:
                        continue
                    held = await self.market.get_validated_market(pair)
                    if held.candles and (repo.manifest['data_kind']=='SYNTHETIC_ACCEPTANCE' or
                            all(c.source.startswith('revolut-x') for c in held.candles)):
                        await repo.store_market_analysis(held.candles, calculate_features(held.candles), held.order_book)
                except MarketDataError as exc:
                    failures.append({'symbol': position.symbol, 'reason': 'held_context_unavailable:'+str(exc)})
        for candidate in {c.market.pair.symbol: c for c in candidates}.values():
            aligned = align_candidate(candidate,cycle)
            if aligned is None:
                failures.append({'symbol':candidate.market.pair.symbol,'reason':'cycle_closed_bar_or_quote_unavailable',
                                 'requested_as_of':cycle.as_of.isoformat()})
                continue
            candidate = aligned
            market = candidate.market
            if market.pair.quote_asset != 'EUR' or not market.usable_for_entry:
                failures.append({'symbol': market.pair.symbol, 'reason': 'invalid_or_unsupported_market'})
                continue
            if repo.manifest['data_kind'] != 'SYNTHETIC_ACCEPTANCE' and (
                not market.order_book.source.startswith('revolut-x') or any(not c.source.startswith('revolut-x') for c in market.candles)):
                raise ValueError('prospective_paper_rejects_synthetic_observations')
            try:
                f = enrich(candidate.features, market.candles, cycle.as_of)
            except ValueError as exc:
                failures.append({'symbol': market.pair.symbol, 'reason': str(exc)})
                continue
            f.metadata.update(best_bid=market.order_book.best_bid, best_ask=market.order_book.best_ask,
                last_price=market.metrics.mid, liquidity_quote=market.metrics.liquidity_quote,
                order_book_age_seconds=market.metrics.age_seconds)
            if int(f.timestamp.timestamp())+300 < int(utc_now().timestamp())//300*300:
                f.metadata['completed_context_delayed'] = True
            await repo.store_market_analysis(market.candles, f, market.order_book)
            prepared.append(replace(candidate, features=f))
        context = {c.features.symbol: c.features for c in prepared}
        context.update(benchmark_features(cycle))
        ranked = []
        blockers: Counter[str] = Counter()
        all_rows = []
        snapshot = await repo.snapshot()
        async with repo.session_factory() as session:
            plans = (await session.scalars(select(ExitPlanModel))).all()
        identities = {p.position_id:p.strategy_id for p in plans}
        committed: dict[str, Decimal] = defaultdict(lambda: D(0))
        for position in await repo.list_positions():
            if position.closed_at is None:
                committed[identities.get(position.position_id, 'UNATTRIBUTED')] += position.cost_basis

        from autotrader.personal_paper.admission import apply, completed_context
        for candidate in prepared:
            from autotrader.raoe.regime import assess as learning_regime
            learning_snapshot = learning_regime(candidate.market.candles, cycle.as_of, cycle.histories)
            learning_book = candidate.market.order_book
            learning_snapshot['near_liquidity'] = {
                'bid_quote': str(sum((v.price*v.quantity for v in learning_book.bids if learning_book.best_bid and v.price >= learning_book.best_bid*D('.9975')), D(0))),
                'ask_quote': str(sum((v.price*v.quantity for v in learning_book.asks if learning_book.best_ask and v.price <= learning_book.best_ask*D('1.0025')), D(0)))}
            admission_context = completed_context(candidate.market.candles, cycle.histories, cycle.as_of,
                genuine=repo.manifest['data_kind']!='SYNTHETIC_ACCEPTANCE')
            from autotrader.learning.regimes import assess as market_state
            from autotrader.learning.regimes import shadow_hypotheses
            observed_state = market_state(candidate.market.candles, cycle.histories, cycle.as_of,
                learning_book, genuine=repo.manifest['data_kind']!='SYNTHETIC_ACCEPTANCE')
            closed = [c for c in candidate.market.candles if c.timestamp.timestamp()+300 <= cycle.as_of.timestamp()]
            volumes = [c.volume for c in closed[-21:-1]]
            average_volume = sum(volumes, D(0))/len(volumes) if volumes else D(0)
            learning_context = {'version':'4.9.3-market-observation.1',
                'volume_ratio':str(closed[-1].volume/average_volume) if closed and average_volume>0 else None,
                'close':str(closed[-1].close) if closed else None,
                'cutoff':cycle.as_of.isoformat(),'regime':learning_snapshot,'market_state':observed_state,
                'data_hash':digest(canonical([[c.timestamp.isoformat(),str(c.open),str(c.high),str(c.low),str(c.close),str(c.volume)] for c in closed])),
                'volume_kind':'PUBLIC_MID_OHLCV_NOT_EXECUTED_DEMAND'}
            for identity, spec in repo.manifest['strategies'].items():
                from autotrader.raoe import IDENTITIES
                from autotrader.raoe.engine import RAOEEngine
                is_raoe = identity in IDENTITIES
                engine: Any = RAOEEngine(D(repo.manifest['fee_bps']), D(repo.manifest['slippage_bps'])) if is_raoe else SuccessorOpportunityEngine(SuccessorParameters.from_payload(spec['parameters']), D(repo.manifest['fee_bps']), D(repo.manifest['slippage_bps']))
                signal = engine.evaluate(identity, candidate.features, candidate.market.pair, candidate.market.order_book,
                    context.get('BTC-EUR'), context.get('ETH-EUR'), candidate.market.candles, quote_budget=LIMITS.max_position_size,
                    **({'benchmarks': cycle.histories} if is_raoe else {}),
                    sizing_scope='SHARED_7000_ACCOUNT', sizing_context={'cash': D(snapshot['available_cash']),
                        'exposure': D(snapshot['open_exposure'] or 0), 'limits': LIMITS})
                signal = signal if is_raoe else reviewed_signal(signal, candidate.features)
                signal = apply(signal, admission_context, cycle.as_of)
                signal.evidence['exit_policy']=spec.get('exit_policy')
                ranking(signal, D(committed[identity]))
                signal.evidence['paper_manifest'] = digest(canonical(repo.manifest))
                signal.evidence['execution_profile'] = repo.manifest['version']
                from autotrader.provenance import release_identity
                signal.evidence['backend_release'] = release_identity()
                signal.evidence['learning_context'] = {**learning_context,
                    'hypotheses':shadow_hypotheses({**signal.evidence,'strategy_id':identity},observed_state)}
                signal = replace(signal, signal_id='sig_'+digest((signal.signal_id+signal.evidence['paper_manifest']).encode())[:40])
                # Same signal hypothesis and frozen parameters; this financial
                # experiment has its own source, account and evidence identity.
                blockers.update(signal.evidence.get('reasons', []))
                row = {'strategy_id': identity, 'symbol': signal.symbol, 'score': str(signal.score),
                    'technical': signal.evidence['technical_eligible'], 'economic': signal.evidence['economic_eligible'],
                    'reasons': signal.evidence['reasons'], 'economics': signal.evidence.get('economics'),
                    'as_of': signal.timestamp.isoformat(), 'execution': 'NOT_ELIGIBLE',
                    'raoe_regime': signal.evidence.get('raoe_regime'), 'entry_plan': signal.evidence['entry_plan'],
                    'pipeline': signal.evidence['pipeline'], 'entry_eligible': signal.evidence['entry_eligible'],
                    'quality_policy': signal.evidence['quality_policy'], 'primary_admission': signal.evidence['primary_admission'],
                    'ranking_components': signal.evidence['ranking_components']}
                all_rows.append(row)
                ranked.append((candidate, signal, row))
        # Conditional economics and portfolio fit, never observed trade activity.
        ranked.sort(key=lambda v: ranking(v[1], D(committed[v[1].strategy_id])))
        outcomes = []
        selected_symbols: set[str] = set()
        for candidate, signal, row in ranked:
            market, f = candidate.market, candidate.features
            identity = 'paper_'+digest((signal.signal_id+digest(canonical(repo.manifest))).encode())[:48]
            key = 'paper_done:'+digest(identity.encode())[:40]
            async with repo.session_factory() as session:
                done = await session.get(SystemStateModel, key)
                stored = await session.get(TradingDecisionModel, identity)
                original = await session.get(StrategySignalModel, signal.signal_id) if stored else None
            if done:
                row['execution'] = 'ALREADY_EVALUATED'
                continue
            await repo.record_mark(market.order_book)
            current = await repo.snapshot()
            portfolio = Portfolio(D(current['available_cash']))
            portfolio.positions = {p.symbol: p for p in await repo.list_positions() if p.closed_at is None and p.quantity>0}
            plan = signal.evidence['entry_plan']
            quote = D(signal.evidence.get('sizing', {}).get('quote_budget_eur', '0'))
            stop = D(plan['stop'])
            ask = market.order_book.best_ask
            assert ask is not None
            risk = RiskEngine(LIMITS).evaluate_entry(portfolio, market.pair, quote, ask, stop, 0,
                D(current['daily_equity_change'] or 0), D(current['weekly_equity_change'] or 0))
            accepted = signal.evidence['entry_eligible'] and risk.accepted and signal.symbol not in selected_symbols
            reason = ','.join(signal.evidence['reasons'] or risk.reasons) if not accepted else None
            if signal.symbol in selected_symbols:
                reason = 'redundant_strategy_same_asset'
            decision = TradingDecision(identity, signal.symbol, utc_now(), DecisionAction.BUY if accepted else DecisionAction.WAIT,
                [signal.signal_id], None, quote, quantize_down(quote/(ask*D('1.005')), market.pair.quantity_step),
                ask, stop, (D(plan['targets'][0]), D(plan['targets'][1]), D(plan['targets'][2])) if len(plan['targets'])==3 else (), accepted, reason,
                'Shared capital rank; unvalidated paper hypothesis; '+(reason or 'eligible_for_locked_financial_admission'))
            if stored and original:
                decision, signal = restore_decision(stored.payload_json), restore_signal(original.payload_json)
            if is_raoe_signal := signal.strategy_id.startswith('RAOE_'):
                from autotrader.raoe.analytics import risk_stage
                risk_stage(signal.evidence['pipeline'], bool(signal.evidence['entry_eligible']), bool(accepted), reason)
            await repo.store_analysis([signal], None, decision)
            if is_raoe_signal:
                from autotrader.raoe.analytics import record_candidate
                await record_candidate(repo, signal, decision)
            if decision.accepted:
                result = await self.gateway(repo).execute_entry_decision(market.pair, decision, market.order_book, identity)
                row['execution'] = result.reason
                outcomes.append({'strategy_id': signal.strategy_id, 'symbol': signal.symbol,
                    'accepted': result.accepted, 'reason': result.reason, 'order_id': result.order.order_id if result.order else None})
                if result.accepted:
                    selected_symbols.add(signal.symbol)
                else:
                    blockers.update([result.reason])
            elif reason:
                row['execution'] = reason
            async with repo.session_factory() as session, session.begin():
                await repo._lock_account(session)
                if not await session.get(SystemStateModel, key):
                    session.add(SystemStateModel(key=key, state='COMPLETED', reason='decision_and_gateway_durable', payload_json=_json({'decision_id': identity})))
        payload = {'observed_at': utc_now().isoformat(), 'markets': [c.features.symbol for c in prepared],
            'strategies_evaluated': len(ranked), 'rows': all_rows, 'blockers': dict(blockers.most_common()),
            'data_failures': failures, 'execution_outcomes': outcomes,
            'benchmark_sync':cycle.diagnostics,'evaluation_as_of':cycle.as_of.isoformat(),
            'research_action': 'Compare costs, regimes and chronological holdouts; retain losses; active parameters remain frozen.'}
        async with repo.session_factory() as session, session.begin():
            await repo._lock_account(session)
            state = await session.get(SystemStateModel, 'paper_scan')
            if state:
                state.payload_json, state.updated_at = _json(payload), utc_now()
            else:
                session.add(SystemStateModel(key='paper_scan', state='PAPER_EXPERIMENTAL_ACTIVE', reason='shared_strategy_coordinator', payload_json=_json(payload)))
        from autotrader.raoe.analytics import assess_due
        await assess_due(repo)
        from autotrader.personal_paper.review import review_once
        await review_once(repo)
        await repo.worker_heartbeat()
        await repo.reconcile_runtime_health(INITIAL)
