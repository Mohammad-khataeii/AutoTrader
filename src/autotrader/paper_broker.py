"""Synchronous compatibility facade over the authoritative paper repository.

The autonomous worker uses PaperExecutionGateway. This facade keeps existing
local simulation callers working without a second financial execution engine.
"""
from __future__ import annotations

import asyncio
import tempfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from autotrader.domain import Fill, Order, OrderBook, OrderType, Side, TradingPair, new_id
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.models import FillModel, TradingDecisionModel
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.portfolio import Portfolio


class PaperBroker:
    def __init__(self,portfolio:Portfolio,fee_bps:Decimal=Decimal(10),slippage_bps:Decimal=Decimal(8))->None:
        self.portfolio,self.fee_bps,self.slippage_bps=portfolio,fee_bps,slippage_bps
        self.orders:dict[str,Order]={}
        self.fills:dict[str,Fill]={}
        self._directory=tempfile.TemporaryDirectory(prefix='paper-broker-')
        self._url=f"sqlite+aiosqlite:///{Path(self._directory.name)/'paper.db'}"
        asyncio.run(self._initialize())

    async def _initialize(self)->None:
        engine=make_engine(SimpleNamespace(database_url=self._url))  # type: ignore[arg-type]
        try:
            await create_schema(engine)
            await PersistentTradingRepository(make_session_factory(engine)).initialize_portfolio(self.portfolio.cash)
        finally:
            await engine.dispose()

    def submit_order(self,pair:TradingPair,side:Side,order_type:OrderType,quantity:Decimal,
                     quote_amount:Decimal,order_book:OrderBook,limit_price:Decimal|None=None,
                     decision_id:str|None=None,*,stop_loss:Decimal|None=None)->Order:
        return asyncio.run(self._submit(pair,side,order_type,quantity,quote_amount,order_book,
            limit_price,decision_id,stop_loss))

    async def _submit(self,pair:TradingPair,side:Side,order_type:OrderType,quantity:Decimal,
                      quote:Decimal,book:OrderBook,limit:Decimal|None,decision_id:str|None,stop:Decimal|None)->Order:
        engine=make_engine(SimpleNamespace(database_url=self._url))  # type: ignore[arg-type]
        repo=PersistentTradingRepository(make_session_factory(engine))
        try:
            if decision_id:
                async with repo.session_factory() as s,s.begin():
                    if await s.get(TradingDecisionModel,decision_id) is None:
                        s.add(TradingDecisionModel(decision_id=decision_id,symbol=pair.symbol,action=side.value,
                            accepted=True,payload_json='{"origin":"manual local simulation proposal; repository risk required"}'))
            protective=stop if stop is not None else (book.best_ask*Decimal('.98') if book.best_ask else None)
            order=await repo.submit_order(pair,side,order_type,quantity,quote,book,new_id('compat'),
                decision_id=decision_id,limit_price=limit,fee_bps=self.fee_bps,slippage_bps=self.slippage_bps,
                stop_loss=protective)
            self.orders[order.order_id]=order
            snapshot=await repo.snapshot()
            balance=self.portfolio.balances[self.portfolio.quote_asset]
            balance.available,balance.reserved=Decimal(snapshot['available_cash']),Decimal(snapshot['reserved_cash'])
            for p in await repo.list_positions():
                self.portfolio.positions[p.symbol]=p
            async with repo.session_factory() as s:
                for f in (await s.scalars(select(FillModel))).all():
                    self.fills[f.fill_id]=Fill(f.fill_id,f.order_id,f.symbol,Side(f.side),f.quantity,f.price,f.fee,f.created_at,True)
            self.portfolio.processed_fill_ids.update(self.fills)
            return order
        finally:
            await engine.dispose()

    def cancel(self,order_id:str)->Order:
        # Orders are immediate-or-cancel; no unbacked mutable in-memory reservation.
        return self.orders[order_id]
