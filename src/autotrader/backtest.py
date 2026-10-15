"""Historical replay through the SAME scanner, gateway, manager and accounting.

Signals use completed bars. Entries execute at the next observed bar open.
Intrabar stop/target collisions use the stop first; gap stops use the worse open.
No model training or profitability assertion is implied by a replay report.
"""
from __future__ import annotations

import asyncio
import itertools
import math
import tempfile
from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from autotrader.ai import OffAIProvider
from autotrader.clock import at
from autotrader.decision import DecisionEngine
from autotrader.domain import Candle, OrderBook, OrderBookLevel, OrderType, TradingPair, utc_now
from autotrader.execution_gateway import PaperExecutionGateway
from autotrader.market_data.service import MarketDataService
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.portfolio import Portfolio
from autotrader.position_manager import PositionManager
from autotrader.scanner import MarketScanner
from autotrader.strategies import BreakoutStrategyEngine
from autotrader.worker.runner import execute_ranked_candidates

ZERO=Decimal(0)


@dataclass(frozen=True)
class BacktestReport:
    net_profit: Decimal
    total_return: Decimal
    max_drawdown: Decimal
    profit_factor: Decimal | None
    win_rate: Decimal
    expectancy: Decimal
    sharpe_ratio: Decimal
    exposure: Decimal
    turnover: Decimal
    trades: int
    average_gain: Decimal
    average_loss: Decimal
    sortino_ratio: Decimal
    strategy_contribution: dict[str, Decimal]
    performance_by_regime: dict[str, Decimal]
    assumptions: dict[str, Any]
    verdict: str


class HistoricalBoundary:
    """External data boundary; internal trading components remain real."""
    def __init__(self,candles:list[Candle],pairs:list[TradingPair],interval:int,spread_bps:Decimal,
                 liquidity_fraction:Decimal) -> None:
        self.candles=candles
        self.pairs=pairs
        self.interval=interval
        self.spread_bps=spread_bps
        self.liquidity_fraction=liquidity_fraction
        self.books:dict[str,OrderBook]={}

    async def get_pairs(self)->list[TradingPair]:
        return self.pairs

    async def get_order_book(self,symbol:str,limit:int=50)->OrderBook:
        from autotrader.market_data.revolut import MarketDataError
        if symbol not in self.books:
            raise MarketDataError("No historical quote for symbol")
        return self.books[symbol]

    async def get_candles(self,symbol:str,interval_minutes:int,since_ms:int,until_ms:int)->list[Candle]:
        return [c for c in self.candles if c.symbol==symbol and c.timeframe==f"{interval_minutes}m"
                and c.timestamp+timedelta(minutes=interval_minutes)<=utc_now()][-240:]

    def observe(self,candle:Candle,price:Decimal)->None:
        half=price*self.spread_bps/20000
        qty=max(candle.volume*self.liquidity_fraction,ZERO)
        self.books[candle.symbol]=OrderBook(candle.symbol,utc_now(),
            (OrderBookLevel(price-half,qty),),(OrderBookLevel(price+half,qty),),"historical-assumed-book")

    async def close(self)->None:
        pass


class Backtester:
    def __init__(self,pair:TradingPair,portfolio:Portfolio,decision_engine:DecisionEngine,*,
                 spread_bps:Decimal=Decimal(10),fee_bps:Decimal=Decimal(10),slippage_bps:Decimal=Decimal(8),
                 liquidity_fraction:Decimal=Decimal("0.1"),entry_order_type:OrderType=OrderType.MARKET) -> None:
        self.pair=pair
        self.portfolio=portfolio
        self.decision_engine=decision_engine
        self.spread_bps,self.fee_bps,self.slippage_bps=spread_bps,fee_bps,slippage_bps
        self.liquidity_fraction=liquidity_fraction
        self.entry_order_type=entry_order_type

    def run(self,candles:list[Candle])->BacktestReport:
        return asyncio.run(self.run_async(candles))

    async def run_async(self,candles:list[Candle],*,trade_start:Any=None)->BacktestReport:
        if not candles:
            raise ValueError("Historical candles are required; no generated profitability data.")
        if self.portfolio.cash!=500 or self.portfolio.positions:
            raise ValueError("Replay requires a fresh EUR 500 paper portfolio.")
        ordered=sorted(candles,key=lambda c:(c.timestamp,c.symbol,c.timeframe))
        keys=[(c.symbol,c.timeframe,c.timestamp) for c in ordered]
        if len(set(keys))!=len(keys):
            raise ValueError("Duplicate historical observations.")
        if any(c.timestamp.tzinfo is None or min(c.open,c.high,c.low,c.close)<=0 or c.volume<0 or not(c.low<=c.open<=c.high and c.low<=c.close<=c.high) for c in ordered):
            raise ValueError("Invalid historical OHLCV.")
        intervals=sorted({int(c.timeframe.removesuffix('m')) for c in ordered})
        interval=intervals[0]
        symbols=sorted({c.symbol for c in ordered})
        pairs=[self.pair if symbol==self.pair.symbol else TradingPair(symbol,symbol.split('-')[0],'EUR',min_order_quote=Decimal(1)) for symbol in symbols]
        if any(not symbol.endswith('-EUR') for symbol in symbols):
            raise ValueError("Only EUR historical markets are supported.")
        primary=[c for c in ordered if c.timeframe==f'{interval}m']
        boundary=HistoricalBoundary(ordered,pairs,interval,self.spread_bps,self.liquidity_fraction)
        service=MarketDataService(boundary,candle_interval_minutes=interval)  # type: ignore[arg-type]
        curve=[Decimal(500)]
        exposures=[]
        realized:list[Decimal]=[]
        regime_pnl:dict[str,Decimal]={}
        entry_regimes:dict[str,str]={}
        with tempfile.TemporaryDirectory(prefix='autotrader-backtest-') as directory:
            engine=make_engine(SimpleNamespace(database_url=f"sqlite+aiosqlite:///{Path(directory)/'replay.db'}"))  # type: ignore[arg-type]
            await create_schema(engine)
            repo=PersistentTradingRepository(make_session_factory(engine))
            try:
                with at(primary[0].timestamp):
                    await repo.initialize_portfolio(Decimal(500))
                gateway=PaperExecutionGateway(repo,market_data=service,risk_engine=self.decision_engine.risk_engine,
                    initial_cash=Decimal(500),fee_bps=self.fee_bps,slippage_bps=self.slippage_bps,entry_order_type=self.entry_order_type)
                scanner=MarketScanner(market_data=service,repository=repo,strategy_engine=BreakoutStrategyEngine(),
                    decision_engine=self.decision_engine,ai_provider=OffAIProvider(),initial_cash=Decimal(500))
                manager=PositionManager(repository=repo,market_data=service,execution_gateway=gateway)
                for timestamp, group in itertools.groupby(primary,key=lambda c:c.timestamp):
                    frame=list(group)
                    if trade_start is not None and timestamp<trade_start:
                        continue
                    with at(timestamp):
                        for candle in frame:
                            boundary.observe(candle,candle.open)
                            await repo.record_mark(boundary.books[candle.symbol])
                        await manager.monitor_once(pairs)
                        result=await scanner.scan_once(len(pairs))
                        await execute_ranked_candidates(result.candidates,gateway,3)
                        candidate_regimes={c.market.pair.symbol:next((str(s.evidence['regime']) for s in c.signals if s.strategy_id=='F_MARKET_REGIME_RISK_OFF'),'UNCLASSIFIED') for c in result.candidates}
                        for p in await repo.list_positions():
                            if p.position_id not in entry_regimes:
                                entry_regimes[p.position_id]=candidate_regimes.get(p.symbol,'UNCLASSIFIED')
                    with at(timestamp+timedelta(minutes=interval)):
                        # The historical path is unknown: choose protective stop first.
                        open_positions_by_symbol={p.symbol:p for p in await repo.list_positions() if p.closed_at is None}
                        for candle in frame:
                            position=open_positions_by_symbol.get(candle.symbol)
                            price=candle.close
                            bid_factor = 1 - self.spread_bps / 20000
                            if position and position.protective_stop and candle.low*bid_factor<=position.protective_stop:
                                price=min(candle.open,position.protective_stop/bid_factor)
                            # A candle high alone does not prove an executable target
                            # fill. Target IOC orders require the completed close quote.
                            boundary.observe(candle,price)
                        await manager.monitor_once(pairs)
                        for candle in frame:
                            boundary.observe(candle,candle.close)
                            await repo.record_mark(boundary.books[candle.symbol])
                        snapshot=await repo.snapshot()
                        if snapshot['equity']:
                            curve.append(Decimal(snapshot['equity']))
                            exposures.append(Decimal(snapshot['open_exposure']))
                positions=await repo.list_positions()
                realized=[p.realized_pnl for p in positions if p.closed_at is not None]
                fills=await repo.list_fills()
                orders=await repo.list_orders()
                order_counts={status:sum(o['status']==status for o in orders) for status in sorted({o['status'] for o in orders})}
                from sqlalchemy import select

                from autotrader.persistence.models import ExitPlanModel
                async with repo.session_factory() as session:
                    plans=(await session.scalars(select(ExitPlanModel))).all()
                strategy_contribution:dict[str,Decimal]={}
                plan_strategies={plan.position_id:plan.strategy_id for plan in plans}
                for position in positions:
                    strategy=plan_strategies.get(position.position_id,'ensemble-v3.4')
                    strategy_contribution[strategy]=strategy_contribution.get(strategy,ZERO)+position.realized_pnl
                turnover=sum((Decimal(f['quantity'])*Decimal(f['price']) for f in fills),ZERO)/Decimal(500)
                problems=await repo.verify_invariants(Decimal(500))
                if problems:
                    raise ValueError('Replay reconciliation failed: '+','.join(problems))
                for p in positions:
                    label=entry_regimes.get(p.position_id,'UNCLASSIFIED')
                    regime_pnl[label]=regime_pnl.get(label,ZERO)+p.realized_pnl
            finally:
                await engine.dispose()
        return _report(curve,realized,exposures,turnover,interval,regime_pnl,strategy_contribution,
            {'source':sorted({c.source for c in ordered}),'symbols':symbols,'input_timeframes':[f'{i}m' for i in intervals],
             'execution_timeframe':f'{interval}m','higher_timeframes':f'completed {interval*4}m groups confirm primary signals; no future bars',
             'strategy_attribution':'dominant entry-plan strategy; overlapping signals are not a causal attribution',
             'entry_order_type':self.entry_order_type.value,'time_in_force':'IOC; no resting limit book is assumed',
             'order_status_counts':order_counts,'confirmed_fills':len(fills),
             'spread_bps':str(self.spread_bps),'fee_bps':str(self.fee_bps),'slippage_bps':str(self.slippage_bps),
             'liquidity_fraction':str(self.liquidity_fraction),'latency':'next observed bar open after signal close',
             'collision_policy':'bid stop first; adverse open for stop gaps; target requires close quote',
             'historical_liquidity':'OHLCV participation assumption, not reconstructed L2; zero volume supplies zero depth',
             'open_positions_at_end':sum(p.closed_at is None for p in positions)})

    async def walk_forward(self,candles:list[Candle],train_bars:int=100,test_bars:int=50)->list[dict[str,Any]]:
        if train_bars<50 or test_bars<1:
            raise ValueError('Walk-forward requires at least 50 training bars and positive test windows.')
        times=sorted({c.timestamp for c in candles})
        results=[]
        for start in range(train_bars,len(times),test_bars):
            end=min(start+test_bars,len(times))
            subset=[c for c in candles if times[max(0,start-train_bars)]<=c.timestamp<=times[end-1]]
            report=await self.run_async(subset,trade_start=times[start])
            results.append({'train_start':times[max(0,start-train_bars)].isoformat(),'test_start':times[start].isoformat(),
                'test_end':times[end-1].isoformat(),'optimization':'none; fixed strategy parameters', 'out_of_sample':asdict(report)})
        return results


def _report(curve:list[Decimal],realized:list[Decimal],exposures:list[Decimal],turnover:Decimal,
            interval:int,regimes:dict[str,Decimal],strategies:dict[str,Decimal],assumptions:dict[str,Any])->BacktestReport:
    winners=[p for p in realized if p>0]
    losers=[-p for p in realized if p<0]
    gains,losses=sum(winners,ZERO),sum(losers,ZERO)
    peak=curve[0]
    drawdown=ZERO
    returns=[]
    for previous,current in itertools.pairwise(curve):
        peak=max(peak,current)
        drawdown=max(drawdown,(peak-current)/peak if peak else ZERO)
        if previous>0:
            returns.append(float((current-previous)/previous))
    mean=sum(returns)/len(returns) if returns else 0
    variance=sum((r-mean)**2 for r in returns)/len(returns) if returns else 0
    downside=sum(min(r,0)**2 for r in returns)/len(returns) if returns else 0
    annual=math.sqrt(365*24*60/interval)
    sharpe=Decimal(str(mean/math.sqrt(variance)*annual if variance else 0))
    sortino=Decimal(str(mean/math.sqrt(downside)*annual if downside else 0))
    profit=curve[-1]-curve[0]
    return BacktestReport(net_profit=profit,total_return=profit/curve[0],max_drawdown=drawdown,
        profit_factor=gains/losses if losses else None,win_rate=Decimal(len(winners))/len(realized) if realized else ZERO,
        expectancy=sum(realized,ZERO)/len(realized) if realized else ZERO,sharpe_ratio=sharpe,
        exposure=sum(exposures,ZERO)/len(exposures)/Decimal(500) if exposures else ZERO,turnover=turnover,trades=len(realized),
        average_gain=gains/len(winners) if winners else ZERO,average_loss=losses/len(losers) if losers else ZERO,
        sortino_ratio=sortino,strategy_contribution=strategies,performance_by_regime=regimes,
        assumptions=assumptions,verdict='UNDERPERFORMED_INITIAL_CASH' if profit<0 else 'NO_POSITIVE_RETURN' if profit==0 else 'POSITIVE_ON_SUPPLIED_REPLAY_ONLY')
