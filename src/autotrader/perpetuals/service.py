"""Durable cursor, queued simulated entries and atomic ledger updates."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from decimal import Decimal

import httpx
from sqlalchemy import inspect, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from autotrader.config import Settings
from autotrader.perpetuals.engine import (
    SIGNAL_MINUTES,
    SIGNAL_PERIOD,
    State,
    account_equity,
    advance,
    initial_state,
    liquidation_mark,
    reconcile,
    signal,
)
from autotrader.perpetuals.market import MINUTE, SYMBOL, PublicMarket, clock_ms
from autotrader.perpetuals.models import PaperPerpEvent, PaperPerpState

log = logging.getLogger(__name__)
MAX_BATCH = 180
FEED_MAX_AGE = 135_000
PUBLICATION_DELAY = 4_000


def flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"true", "1"}


def available(settings: Settings) -> bool:
    return (
        flag("PAPER_PERPETUALS_ENABLED") and settings.paper_trading_enabled
        and not settings.live_trading_enabled and not settings.market_data_replay_file
        and settings.environment in {"local", "staging"}
    )


def encode(state: State) -> str:
    return json.dumps(state, default=str, allow_nan=False, separators=(",", ":"))


class Perpetuals:
    def __init__(self, factory: async_sessionmaker[AsyncSession]):
        self.factory = factory

    @staticmethod
    async def _read(session: AsyncSession) -> tuple[int, State]:
        row = await session.get(PaperPerpState, 1)
        if row is None:
            raise RuntimeError("Perpetuals schema is not initialized")
        state = json.loads(row.payload) if row.payload else initial_state()
        reconcile(state)
        return row.generation, state

    async def load(self) -> tuple[int, State]:
        async with self.factory() as session:
            return await self._read(session)

    async def save(self, version: int, state: State, events: list[State]) -> bool:
        reconcile(state)
        async with self.factory() as session, session.begin():
            result = await session.execute(
                update(PaperPerpState).where(PaperPerpState.id == 1, PaperPerpState.generation == version)
                .values(payload=encode(state), generation=version + 1)
            )
            if result.rowcount != 1:
                return False
            session.add_all(PaperPerpEvent(payload=encode(event)) for event in events)
            return True

    @staticmethod
    async def _provisioned(session: AsyncSession) -> bool:
        connection = await session.connection()
        return await connection.run_sync(lambda conn: inspect(conn).has_table("paper_perp_state"))

    async def control(self, enabled: bool) -> bool:
        async with self.factory() as session:
            if not await self._provisioned(session):
                return False
        version, state = await self.load()
        if state["entries_enabled"] == enabled:
            return True
        if enabled and not fresh(state):
            return False
        state["entries_enabled"] = enabled
        state["pending"] = None
        return await self.save(version, state, [
            {"kind": "RESUME_ENTRIES" if enabled else "PAUSE_ENTRIES", "minute": clock_ms()},
        ])

    async def snapshot(self, *, enabled: bool) -> State:
        async with self.factory() as session:
            # One statement sees both the account snapshot and its committed audit events.
            recent = select(PaperPerpEvent.id, PaperPerpEvent.payload).order_by(
                PaperPerpEvent.id.desc()).limit(60).subquery()
            rows = (await session.execute(select(PaperPerpState.payload, recent.c.payload)
                    .select_from(PaperPerpState).outerjoin(recent, PaperPerpState.id == 1)
                    .where(PaperPerpState.id == 1).order_by(recent.c.id.desc()))).all() if await self._provisioned(session) else []
        state = json.loads(rows[0][0]) if rows and rows[0][0] else initial_state()
        reconcile(state)
        mark = Decimal(state["mark"]) if state["mark"] is not None else None
        accounts = []
        for account in state["accounts"]:
            position = account["position"]
            equity = account_equity(account, mark)
            accounts.append({
                **account, "equity": equity,
                "position": {**position, "notional": Decimal(position["qty"]) * mark,
                             "liquidation_mark": liquidation_mark(position)}
                if position and mark is not None else None,
            })
        return json.loads(encode({
            "available": enabled, "policy": state["policy"], "paper_only": True,
            "symbol": SYMBOL, "currency": "USDT", "source": "Bybit public market data",
            "entries_enabled": state["entries_enabled"], "data_fresh": enabled and fresh(state),
            "feed_status": "DISABLED" if not enabled else "DEGRADED" if state.get("feed_error")
            else "WAITING" if not state["cursor"] else "CURRENT" if fresh(state) else "STALE",
            "bar_closed_at": state["cursor"] + MINUTE if state["cursor"] is not None else None,
            "mark": state["mark"], "pending": state["pending"],
            "accounts": accounts, "events": [json.loads(row[1]) for row in rows if row[1]],
        }))

    async def cycle(self, market: PublicMarket) -> None:
        version, state = await self.load()
        now = clock_ms()
        newest = ((now - PUBLICATION_DELAY) // MINUTE - 1) * MINUTE
        cursor = state["cursor"]
        start = newest if cursor is None else cursor + MINUTE
        if start > newest:
            return
        end = min(newest, start + (MAX_BATCH - 1) * MINUTE)
        may_signal = (
            end == newest and (end + MINUTE) % SIGNAL_PERIOD == 0 and state["entries_enabled"]
            and any(not a["halted"] for a in state["accounts"])
        )
        trade_start = min(start, end - (SIGNAL_MINUTES - 1) * MINUTE) if may_signal else start
        try:
            trade, mark, rates, instrument = await asyncio.gather(
                market.bars(trade_start, end, mark=False),
                market.bars(start, end, mark=True),
                market.funding(start, end),
                market.instrument(),
            )
            minutes = range(start, end + 1, MINUTE)
            if any(t not in trade or t not in mark for t in minutes):
                raise ValueError("Perpetuals candle gap")
        except (ValueError, ArithmeticError, httpx.HTTPError, KeyError, TypeError, IndexError):
            if not state.get("feed_error"):
                state["feed_error"] = True
                await self.save(version, state, [])
                log.warning("Perpetuals data incomplete or unavailable; cursor retained and entries blocked")
            return

        events: list[State] = []
        now = clock_ms()
        # A queued order may only fill in the newest completed minute, even after downtime.
        fresh_minute = end == newest and now - (end + MINUTE) <= 45_000
        for t in minutes:
            pending = state["pending"]
            can_fill = t == end and fresh_minute and not state.get("feed_error")
            if pending and t == pending["fill_at"] and not can_fill:
                events.append({"kind": "ENTRY_EXPIRED", "minute": t, "signal_at": pending["signal_at"]})
            events.extend(advance(state, trade[t], mark[t], rates.get(t), instrument, can_fill=can_fill))
        state["feed_error"] = False

        if fresh_minute and may_signal and any(not a["position"] and not a["halted"] for a in state["accounts"]):
            idea = signal(trade, end + MINUTE)
            if idea is not None:
                side, distance, reference = idea
                # Commit the intent before its eligible bar starts. A previously missed
                # order cannot be filled at a later price or replayed as a new signal.
                state["pending"] = {
                    "side": side, "distance": distance, "reference": reference,
                    "signal_at": end + MINUTE, "fill_at": (now // MINUTE + 1) * MINUTE,
                }
                events.append({"kind": "SIGNAL", "minute": end, **state["pending"]})
        await self.save(version, state, events)

    async def run(self, stopping: asyncio.Event) -> None:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            market = PublicMarket(client)
            while not stopping.is_set():
                try:
                    await self.cycle(market)
                except Exception:
                    log.exception("Perpetuals simulation cycle failed; spot processing unaffected")
                try:
                    await asyncio.wait_for(stopping.wait(), timeout=10)
                except TimeoutError:
                    pass


def fresh(state: State) -> bool:
    cursor = state["cursor"]
    return (cursor is not None and not state.get("feed_error")
            and 0 <= clock_ms() - (cursor + MINUTE) <= FEED_MAX_AGE)
