from __future__ import annotations

from decimal import Decimal

from autotrader.backtest import Backtester
from autotrader.config import get_settings
from autotrader.decision import DecisionEngine
from autotrader.domain import Candle, TradingPair
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.portfolio import Portfolio
from autotrader.risk import RiskEngine, RiskLimits


def backtest_main() -> None:
    import argparse
    import json
    from datetime import datetime
    from pathlib import Path
    parser=argparse.ArgumentParser(description="Replay supplied historical candles; no generated performance data")
    parser.add_argument('--candles',required=True,type=Path)
    parser.add_argument('--entry-order-type',choices=['MARKET','LIMIT'],default='MARKET')
    args=parser.parse_args()
    raw=json.loads(args.candles.read_text(encoding='utf-8'))
    records=raw['candles'] if isinstance(raw,dict) else raw
    candles=[Candle(symbol=r['symbol'],timestamp=datetime.fromisoformat(r['timestamp']),
        open=Decimal(r['open']),high=Decimal(r['high']),low=Decimal(r['low']),close=Decimal(r['close']),
        volume=Decimal(r['volume']),timeframe=r.get('timeframe','5m'),source=r.get('source','user-supplied-historical')) for r in records]
    pair = TradingPair(candles[0].symbol,candles[0].symbol.split('-')[0], "EUR")
    portfolio = Portfolio(Decimal("500"))
    engine = DecisionEngine(RiskEngine(RiskLimits()))
    from autotrader.domain import OrderType
    report = Backtester(pair, portfolio, engine,entry_order_type=OrderType(args.entry_order_type)).run(candles)
    from dataclasses import asdict

    from autotrader.persistence.repository import _json
    print(_json(asdict(report)))


def reconcile_main() -> None:
    import asyncio

    async def _run() -> None:
        settings = get_settings()
        engine = make_engine(settings)
        try:
            await create_schema(engine)
            repository = PersistentTradingRepository(make_session_factory(engine))
            await repository.initialize_portfolio(settings.initial_cash_eur)
            problems = await repository.verify_invariants(settings.initial_cash_eur)
            if problems:
                print("reconciliation_failed", problems)
                raise SystemExit(1)
            print("reconciliation_ok")
        finally:
            await engine.dispose()

    asyncio.run(_run())
