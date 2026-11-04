"""Opt-in, read-only research preview. No experiments, fills, training or funding. Untested and unvalidated."""
from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any

import httpx

from autotrader.perpetuals.market import MINUTE, Bar, Instrument, clock_ms
from autotrader.perpetuals.micro.market import ResearchMarket
from autotrader.perpetuals.micro.scoring import score
from autotrader.perpetuals.micro.signals import LOOKBACK, candidates, features
from autotrader.perpetuals.micro.types import FEATURE_SCHEMA, OUTCOME_SCHEMA, POLICIES, public
from autotrader.perpetuals.service import Perpetuals

VERSION = 'perpetuals-micro-research/4.9.7.1'


def catalog(enabled: bool) -> dict[str, Any]:
    return {
        'version': VERSION, 'enabled': enabled, 'status': 'WAITING' if enabled else 'DISABLED',
        'model_state': 'UNQUALIFIED', 'strategy_activation_enabled': False,
        'execution_authorized': False, 'feature_schema': FEATURE_SCHEMA,
        'outcome_schema': OUTCOME_SCHEMA, 'strategies': list(POLICIES),
        'timeframes': ['1m', '3m', '5m'], 'candidate_rows': [],
        'qualification_reason': 'No reviewed perpetuals micro-outcome model is installed',
        'assumptions_status': 'UNTESTED_UNVALIDATED',
    }


class ResearchPreview:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self._response: tuple[float, dict[str, Any]] | None = None
        self._bars: tuple[int, dict[int, Bar]] | None = None
        self._instrument: tuple[float, Instrument] | None = None

    async def _metadata(self, market: ResearchMarket) -> Instrument:
        if self._instrument is None or monotonic() - self._instrument[0] > 60:
            self._instrument = (monotonic(), await market.instrument())
        return self._instrument[1]

    async def _candles(self, market: ResearchMarket, cutoff: int) -> dict[int, Bar]:
        if self._bars is None or self._bars[0] != cutoff:
            rows = await market.bars(cutoff - LOOKBACK * MINUTE, cutoff - MINUTE, mark=False, include_volume=True)
            self._bars = (cutoff, rows)
        return self._bars[1]

    async def snapshot(self, lab: Perpetuals, *, enabled: bool) -> dict[str, Any]:
        if not enabled:
            return catalog(False)
        async with self.lock:
            if self._response is not None and monotonic() - self._response[0] < 1:
                # Reused only as an annotated preview, never as executable intent.
                return self._response[1]
            try:
                async with asyncio.timeout(12), httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
                    market = ResearchMarket(client)
                    cutoff = ((clock_ms() - 4000) // MINUTE) * MINUTE
                    bars, instrument, account_snapshot = await asyncio.gather(
                        self._candles(market, cutoff), self._metadata(market), lab.snapshot(enabled=True),
                    )
                    decision_at = clock_ms()
                    f = features(bars, cutoff, decision_at)
                    ideas = candidates(f)
                    # Never request a book first and retroactively call it a
                    # post-decision execution. Decision availability is pinned here.
                    book, ticker = await asyncio.gather(market.book(), market.ticker())
                    now = clock_ms()
                    rows = []
                    for idea in ideas:
                        for account in account_snapshot['accounts']:
                            row = score(idea, f, account, book, ticker, instrument, now)
                            if not account_snapshot['data_fresh']:
                                row['rejection_reasons'] = (*row['rejection_reasons'], 'legacy_account_valuation_stale')
                                row['eligible_for_future_experiment'] = False
                            # Even a future qualified challenger cannot trade the
                            # original accounts from this read-only serving path.
                            row['experiment_activation_required'] = True
                            rows.append(row)
                    response = public({**catalog(True), 'status': 'RESEARCH_PREVIEW',
                        'observed_at': now, 'decision_at': decision_at,
                        'quote_expires_at': decision_at + 3000,
                        'market': {'regime': f.regime, 'reference': f.reference, 'mark': ticker.mark,
                            'spread_pct': book.spread * 100, 'book_exchange_at': book.exchange_at,
                            'book_received_at': book.received_at, 'cutoff': cutoff},
                        'features': {'schema': FEATURE_SCHEMA, 'source_hash': f.source_hash,
                            'directional_efficiency': f.efficiency, 'persistence': f.persistence,
                            'momentum_1m_pct': f.momentum_1m * 100, 'momentum_3m_pct': f.momentum_3m * 100,
                            'momentum_5m_pct': f.momentum_5m * 100, 'acceleration_pct': f.acceleration * 100,
                            'atr_pct': f.atr_fraction * 100, 'volatility_expansion': f.expansion,
                            'relative_volume': f.volume_ratio, 'aggressor_buy_sell_pressure': None},
                        'candidate_rows': rows})
                    self._response = (monotonic(), response)
                    return response
            except (ValueError, ArithmeticError, httpx.HTTPError, KeyError, TypeError, IndexError, TimeoutError):
                # Failed observations cannot retain a prior positive-looking quote.
                self._response = self._bars = self._instrument = None
                return {**catalog(True), 'status': 'UNAVAILABLE',
                        'rejection_reasons': ['public_data_missing_stale_or_incomplete'], 'observed_at': clock_ms()}
