from __future__ import annotations

from decimal import Decimal

from autotrader.backtest import Backtester
from autotrader.config import get_settings
from autotrader.decision import DecisionEngine
from autotrader.domain import Candle, TradingPair, utc_now
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.portfolio import Portfolio
from autotrader.risk import RiskEngine, RiskLimits


def backtest_main() -> None:
    pair = TradingPair("BTC-EUR", "BTC", "EUR")
    portfolio = Portfolio(Decimal("500"))
    engine = DecisionEngine(RiskEngine(RiskLimits()))
    candles = [
        Candle(pair.symbol, utc_now(), Decimal("100") + Decimal(i), Decimal("103") + Decimal(i), Decimal("98") + Decimal(i), Decimal("101") + Decimal(i), Decimal("10"))
        for i in range(180)
    ]
    report = Backtester(pair, portfolio, engine).run(candles)
    print(report)


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
