"""Research observation only. Does not create accounts, allocations or orders."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import replace
from decimal import Decimal
from typing import Any

from autotrader.domain import utc_now
from autotrader.indicators import calculate_features
from autotrader.market_data.revolut import MarketDataError, RateLimitDeferred, RevolutXPublicClient
from autotrader.opportunity.discovery import rank_markets
from autotrader.opportunity.engine import SUCCESSOR_REGISTRY, SuccessorOpportunityEngine
from autotrader.opportunity.features import enrich
from autotrader.persistence.models import SystemStateModel
from autotrader.persistence.repository import _json
from autotrader.scanner import ScanCandidate

log = logging.getLogger(__name__)


class OpportunityObserver:
    def __init__(self, repository: Any, market_data: Any, *, extra_pairs: int = 3,
                 fee_bps: Decimal = Decimal(10), slippage_bps: Decimal = Decimal(8)):
        self.repo, self.market = repository, market_data
        self.extra_pairs = max(0, min(extra_pairs, 6))
        self.engine = SuccessorOpportunityEngine(fee_bps=fee_bps, slippage_bps=slippage_bps)

    async def observe(self, base: list[ScanCandidate]) -> list[ScanCandidate]:
        bucket = int(utc_now().timestamp()) // 300
        started = time.perf_counter()
        async with self.repo.session_factory() as session:
            prior = await session.get(SystemStateModel, 'opportunity_snapshot')
            metrics_before = await session.get(SystemStateModel, 'market_metrics')
            before = json.loads(metrics_before.payload_json) if metrics_before else None
        if prior and json.loads(prior.payload_json).get('cycle_bucket') == bucket and prior.state != 'ERROR':
            return []
        extras: list[ScanCandidate] = []
        discovery: dict[str, Any] = {'mode': 'base_shared_observations', 'extra_detail_budget': self.extra_pairs}
        errors: list[dict[str, Any]] = []
        if isinstance(self.market.client, RevolutXPublicClient) and self.extra_pairs:
            try:
                async with asyncio.timeout(12):
                    pairs = await self.market.client.get_pairs()
                    ranked, counts = rank_markets(pairs, await self.market.client.get_tickers(),
                        excluded={c.market.pair.symbol for c in base}, limit=self.extra_pairs)
                    discovery.update(mode='cached_ticker_then_bounded_details', counts=counts, ranking=[r.payload() for r in ranked],
                        planned_initial_endpoint_calls=2 + 2 * len(ranked), interval_seconds=300, detail_time_budget_seconds=12)
                    by_symbol = {p.symbol: p for p in pairs}
                    for row in ranked:
                        try:
                            market = await self.market.get_validated_market(by_symbol[row.symbol])
                            if not market.usable_for_entry:
                                errors.append({'symbol': row.symbol, 'stage': 'DATA_VALIDATION', 'reasons': market.rejected_reasons})
                                continue
                            features = calculate_features(market.candles[-240:], market.metrics.imbalance, market.metrics.spread_bps)
                            features.metadata.update(liquidity_quote=market.metrics.liquidity_quote,
                                order_book_age_seconds=market.metrics.age_seconds, successor_discovery_only=True)
                            extras.append(ScanCandidate(market, features, [], None, None, row.score))  # type: ignore[arg-type]
                        except MarketDataError as exc:
                            errors.append({'symbol': row.symbol, 'stage': 'MARKET_DATA', 'reason': type(exc).__name__})
                            if isinstance(exc, RateLimitDeferred):
                                break
            except TimeoutError:
                errors.append({'stage': 'DISCOVERY', 'reason': 'detail_time_budget_exceeded'})
            except MarketDataError as exc:
                errors.append({'stage': 'DISCOVERY', 'reason': type(exc).__name__})
        prepared = []
        for candidate in [*base, *extras]:
            try:
                prepared.append(replace(candidate, features=enrich(candidate.features, candidate.market.candles, candidate.market.order_book.timestamp)))
            except ValueError as exc:
                errors.append({'symbol': candidate.market.pair.symbol, 'stage': 'DATA_VALIDATION', 'reason': str(exc)})
        context = {c.features.symbol: c.features for c in prepared}
        rows = []
        for candidate in prepared:
            for spec in SUCCESSOR_REGISTRY:
                s = self.engine.evaluate(spec.strategy_id, candidate.features, candidate.market.pair, candidate.market.order_book,
                    context.get('BTC-EUR'), context.get('ETH-EUR'), candidate.market.candles)
                rows.append({'symbol': s.symbol, 'strategy_id': s.strategy_id, 'as_of': s.timestamp.isoformat(),
                    'score': str(s.score), 'explanation': s.explanation, **s.evidence})
        payload = {'schema': 'opportunity-snapshot/4.6', 'cycle_bucket': bucket, 'updated_at': utc_now().isoformat(),
            'discovery': discovery, 'rows': rows, 'data_failures': errors, 'paper_observation_only': True,
            'financial_actions': False, 'evaluated_markets': len(prepared),
            'technical_candidates': sum(r['technical_eligible'] for r in rows) if rows else None,
            'economically_viable_candidates': sum(r['economic_eligible'] for r in rows) if rows else None,
            'calibrated_positive_expected_value_candidates': None}
        async with self.repo.session_factory() as session, session.begin():
            metrics_after = await session.get(SystemStateModel, 'market_metrics')
            after = json.loads(metrics_after.payload_json) if metrics_after else None
            payload['measurement'] = {'duration_seconds': time.perf_counter()-started,
                'shared_counter_deltas': {k: after.get(k, 0)-before.get(k, 0) if before is not None and after is not None else None for k in ('request_success', 'request_429', 'request_failure')},
                'counter_scope': 'Shared provider window may include concurrent protective requests; not exclusively discovery traffic.',
                'false_positive_rate': None, 'false_positive_limit': 'Unknown until independent subsequent outcome evidence exists.'}
            row = await session.get(SystemStateModel, 'opportunity_snapshot')
            if row is None:
                session.add(SystemStateModel(key='opportunity_snapshot', state='DEGRADED' if errors else 'OBSERVED', reason='research_only_opportunity_observation', payload_json=_json(payload)))
            else:
                row.state, row.payload_json, row.updated_at = 'DEGRADED' if errors else 'OBSERVED', _json(payload), utc_now()
        return extras

    async def failure(self, exc: Exception) -> None:
        log.exception('opportunity_observation_failed')
        async with self.repo.session_factory() as session, session.begin():
            row = await session.get(SystemStateModel, 'opportunity_snapshot')
            if row is None:
                session.add(SystemStateModel(key='opportunity_snapshot', state='ERROR', reason=type(exc).__name__, payload_json='{}'))
            else:
                row.state, row.reason, row.updated_at = 'ERROR', type(exc).__name__, utc_now()
