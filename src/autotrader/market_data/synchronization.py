"""One completed-bar reference per cycle; observation time is not candle time."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from autotrader.domain import Candle, utc_now
from autotrader.indicators import calculate_features
from autotrader.market_data.revolut import MarketDataError

PEERS = ('BTC-EUR', 'ETH-EUR')


def cutoff(stamp: datetime) -> datetime:
    return datetime.fromtimestamp(int(stamp.timestamp())//300*300, tz=stamp.tzinfo)


def alignment(bars: list[Candle], as_of: datetime, observed_at: str | None = None) -> dict[str, Any]:
    target = as_of-timedelta(minutes=5)
    closed = [b for b in bars if b.timeframe=='5m' and b.timestamp+timedelta(minutes=5)<=as_of]
    latest = max((b.timestamp for b in closed),default=None)
    expected = {target-timedelta(minutes=5*i) for i in range(21)}
    available = {b.timestamp for b in closed}
    duplicate = len(available)!=len(closed)
    missing = len(expected-available)
    invalid=any(not all(v.is_finite() for v in (c.open,c.high,c.low,c.close,c.volume))
                or min(c.open,c.high,c.low,c.close)<=0 or c.volume<0
                or not c.low<=c.open<=c.high or not c.low<=c.close<=c.high for c in closed[-240:])
    mixed=len({c.symbol for c in closed})>1
    reason = ('INVALID_PEER_OHLCV' if invalid else 'MIXED_PEER_ASSETS' if mixed else 'NO_PEER_DATA' if not closed else 'DUPLICATE_PEER_BARS' if duplicate
              else 'MISSING_REQUESTED_CLOSED_BAR' if target not in available
              else 'INSUFFICIENT_OR_GAPPED_PEER_HISTORY' if missing else None)
    return {'requested_candle_at':target.isoformat(),
            'available_candle_at':latest.isoformat() if latest else None,
            'last_successful_observation':observed_at,'alignment_status':'ALIGNED' if reason is None else 'UNKNOWN',
            'missing_bar_count':missing,'required_bars':21,'available_bars':len(available),
            'source':sorted({b.source for b in closed}),
            'staleness_seconds':max(0,(as_of-latest-timedelta(minutes=5)).total_seconds()) if latest else None,
            'ignored_future_or_forming_bars':len(bars)-len(closed),'unknown_reason':reason,
            'as_of':as_of.isoformat()}


@dataclass(frozen=True)
class EvaluationCycle:
    as_of: datetime
    histories: dict[str, list[Candle]]
    diagnostics: dict[str, dict[str, Any]]
    observed_at: datetime


async def load_cycle(market: Any, candidates: list[Any], as_of: datetime | None = None) -> EvaluationCycle:
    reference = cutoff(as_of or utc_now())
    supplied = {c.market.pair.symbol:c for c in candidates}
    histories: dict[str,list[Candle]] = {}
    diagnostics = {}
    for symbol in PEERS:
        candidate = supplied.get(symbol)
        bars = list(candidate.market.candles) if candidate else []
        observed = getattr(market,'_candle_observed_at',{}).get(symbol)
        acquisition_error = None
        if alignment(bars,reference)['alignment_status']!='ALIGNED':
            try:
                pair = candidate.market.pair if candidate else await market.resolve_pair(symbol)
                if pair is None:
                    acquisition_error = 'BENCHMARK_INSTRUMENT_UNAVAILABLE'
                else:
                    bars = await market.completed_candles(pair)
                    observed = getattr(market,'_candle_observed_at',{}).get(symbol) or utc_now().isoformat()
            except (MarketDataError, AttributeError) as exc:
                acquisition_error = 'BENCHMARK_ACQUISITION_UNAVAILABLE:'+type(exc).__name__
        diagnostic = alignment(bars,reference,observed)
        diagnostic['acquisition_error'] = acquisition_error
        # Missing future context is never replaced by a previously seen label.
        histories[symbol] = sorted([b for b in bars if b.timestamp+timedelta(minutes=5)<=reference],key=lambda b:b.timestamp)
        diagnostics[symbol] = diagnostic
    cycle = EvaluationCycle(reference,histories,diagnostics,utc_now())
    store = getattr(market,'state_store',None)
    if store:
        await store.record_benchmark_cycle(reference,diagnostics,cycle.observed_at)
    return cycle


def align_candidate(candidate: Any, cycle: EvaluationCycle) -> Any | None:
    from autotrader.market_data.service import MarketDataService
    market = candidate.market
    raw = cycle.histories.get(market.pair.symbol,market.candles)
    bars = sorted([b for b in raw if b.timestamp+timedelta(minutes=5)<=cycle.as_of],key=lambda b:b.timestamp)
    # A book predating the completed signal cannot be its execution quote.
    # A new cycle retries it; protective book monitoring is independent.
    if (not bars or bars[-1].timestamp!=cycle.as_of-timedelta(minutes=5)
            or market.order_book.timestamp<cycle.as_of
            or MarketDataService(None).validate_candles(bars[-240:],5)):  # type: ignore[arg-type]
        return None
    f = calculate_features(bars[-240:],market.metrics.imbalance,market.metrics.spread_bps)
    f.metadata.update(evaluation_as_of=cycle.as_of.isoformat(),benchmark_sync=cycle.diagnostics,
                      context_observed_at=cycle.observed_at.isoformat())
    return replace(candidate,market=replace(market,candles=bars),features=f)


def benchmark_features(cycle: EvaluationCycle) -> dict[str,Any]:
    from autotrader.opportunity.features import enrich
    result={}
    for symbol,bars in cycle.histories.items():
        if cycle.diagnostics[symbol]['alignment_status']=='ALIGNED':
            result[symbol]=enrich(calculate_features(bars[-240:]),bars,cycle.as_of)
    return result
