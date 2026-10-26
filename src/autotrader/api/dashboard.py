"""Read-only dashboard cash flows, holdings and recorded market candles."""
from __future__ import annotations

import itertools
import re
from datetime import timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import case, func, select, text

from autotrader.domain import utc_now
from autotrader.persistence.accounting import aware
from autotrader.persistence.models import (
    FillModel,
    JournalEventModel,
    MarketCandle,
    MarketMarkModel,
    PositionModel,
)

D = Decimal


async def account_assets(repo: Any) -> dict[str, Any]:
    async with repo.session_factory() as session:
        if session.bind.dialect.name == 'postgresql':
            await session.execute(text('SET TRANSACTION READ ONLY'))
        totals = (await session.execute(select(
            func.coalesce(func.sum(case((FillModel.side == 'BUY', -JournalEventModel.cash_delta), else_=0)), 0),
            func.coalesce(func.sum(case((FillModel.side == 'SELL', JournalEventModel.cash_delta), else_=0)), 0),
            func.coalesce(func.sum(case((JournalEventModel.event_type == 'FEE', -JournalEventModel.cash_delta), else_=0)), 0),
        ).join(FillModel, FillModel.fill_id == JournalEventModel.fill_id).where(
            JournalEventModel.account_id == repo.account_id,
            JournalEventModel.event_type.in_(['BUY_FILL', 'SELL_FILL', 'FEE'])))).one()
        positions = (await session.scalars(select(PositionModel).where(PositionModel.state == 'OPEN', PositionModel.quantity > 0))).all()
        marks = (await session.scalars(select(MarketMarkModel).order_by(MarketMarkModel.symbol))).all()
    market_rows = []
    holdings = []
    for mark in marks:
        age = (utc_now() - aware(mark.timestamp)).total_seconds()
        current = -5 <= age <= 90
        market_rows.append({'symbol': mark.symbol, 'last_observed_price': str(mark.price),
            'observed_at': aware(mark.timestamp).isoformat(), 'fresh': current, 'source': mark.source})
    by_symbol = {m.symbol: m for m in marks}
    for symbol in sorted({p.symbol for p in positions}):
        sample = [p for p in positions if p.symbol == symbol]
        quantity = sum((p.quantity for p in sample), D(0))
        cost = sum((p.cost_basis for p in sample), D(0))
        mark = by_symbol.get(symbol)
        fresh = mark is not None and -5 <= (utc_now() - aware(mark.timestamp)).total_seconds() <= 90
        value = quantity * mark.price if mark and fresh else None
        holdings.append({'symbol': symbol, 'quantity': str(quantity), 'cost_basis_eur': str(cost),
            'market_value_eur': str(value) if value is not None else None,
            'unrealized_pnl_eur': str(value-cost) if value is not None else None,
            'mark_fresh': fresh, 'mark_kind': 'OBSERVED_MIDPOINT'})
    return {'cash_flow': {'spent_on_buys_eur': str(totals[0]), 'sale_proceeds_eur': str(totals[1]),
        'fees_total_eur': str(totals[2]), 'scope': 'ALL_PERSISTED_FILL_JOURNAL_POSTINGS_BUYS_INCLUDE_FEES_SELLS_NET_OF_FEES'},
        'holdings': holdings, 'markets': market_rows}


async def chart_data(service: Any, symbol: str, window: str) -> dict[str, Any]:
    now = utc_now()
    repo = await service.repository()
    rows: list[Any] = []
    hours = {'1h': 1, '6h': 6, '24h': 24}[window]
    if repo is not None:
        async with repo.session_factory() as session:
            if session.bind.dialect.name == 'postgresql':
                await session.execute(text('SET TRANSACTION READ ONLY'))
            filters = [MarketCandle.symbol == symbol, MarketCandle.timeframe == '5m',
                MarketCandle.timestamp >= now - timedelta(hours=hours),
                MarketCandle.timestamp <= now - timedelta(minutes=5)]
            if repo.manifest['data_kind'] != 'SYNTHETIC_ACCEPTANCE':
                filters.append(MarketCandle.source.like('revolut-x%'))
            latest = select(func.max(MarketCandle.id)).where(*filters).group_by(
                MarketCandle.timestamp).order_by(MarketCandle.timestamp.desc()).limit(hours * 12)
            rows = list((await session.scalars(select(MarketCandle).where(
                MarketCandle.id.in_(latest)).order_by(MarketCandle.timestamp))).all())
    missing = sum(max(0, int((aware(b.timestamp)-aware(a.timestamp)).total_seconds()/300)-1)
        for a, b in itertools.pairwise(rows))
    return {'symbol': symbol, 'range': window, 'timeframe': '5m', 'observed_at': now.isoformat(),
        'evidence_category': repo.manifest['data_kind'] if repo else None,
        'latest_candle_at': aware(rows[-1].timestamp).isoformat() if rows else None,
        'missing_intervals': missing, 'expected_bars': hours * 12,
        'candles': [{'timestamp': aware(r.timestamp).isoformat(), 'open': str(r.open),
            'high': str(r.high), 'low': str(r.low), 'close': str(r.close),
            'volume': str(r.volume), 'source': r.source} for r in rows]}


def install(app: FastAPI, service: Any, require_user: Any) -> None:
    @app.get('/api/personal-paper/markets/{symbol}/chart', dependencies=[Depends(require_user)])
    async def chart(symbol: str, range: Literal['1h', '6h', '24h'] = '6h') -> dict[str, Any]:
        if not re.fullmatch(r'[A-Z0-9]{1,20}-EUR', symbol):
            raise HTTPException(422, 'A supported EUR coin symbol is required')
        return await chart_data(service, symbol, range)
