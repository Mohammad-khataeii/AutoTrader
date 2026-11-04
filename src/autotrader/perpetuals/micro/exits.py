"""Pure exit proposals for future micro experiments. Never applies to V4.9.6 positions. Untested and unvalidated."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from autotrader.perpetuals.engine import FEE, liquidation_mark
from autotrader.perpetuals.market import MINUTE, Bar
from autotrader.perpetuals.micro.execution import BOOK_MAX_AGE_MS, SLIPPAGE_FLOOR, vwap
from autotrader.perpetuals.micro.types import Book, Features, POLICIES, Side, Ticker

D = Decimal


@dataclass(frozen=True)
class ResearchPosition:
    policy: str
    side: Side
    quantity: Decimal
    entry: Decimal
    margin: Decimal
    funding: Decimal
    entry_fee: Decimal
    opened_at: int
    initial_stop: Decimal
    stop: Decimal
    target: Decimal
    max_holding_minutes: int
    entry_spread_fraction: Decimal
    break_even_fraction: Decimal
    structure_level: Decimal | None


@dataclass(frozen=True)
class ExitProposal:
    reason: str
    reduce_only: bool
    suggested_stop: Decimal
    observed_at: int
    pricing: str = 'FRESH_POST_INTENT_DEPTH_REQUIRED_NO_FILL_RECORDED'


def propose(p: ResearchPosition, f: Features, ticker: Ticker, book: Book, now: int,
            completed_mark: Bar | None = None) -> ExitProposal:
    if p.policy not in POLICIES or p.side not in {-1, 1} or p.quantity <= 0:
        raise ValueError('micro_exit_requires_its_own_versioned_position_contract')
    values = (p.quantity, p.entry, p.margin, p.entry_fee, p.initial_stop, p.stop, p.target, p.break_even_fraction)
    if (any(not value.is_finite() for value in values) or min(p.entry, p.margin, p.stop, p.target) <= 0
            or p.break_even_fraction < 0 or p.side * (p.entry - p.initial_stop) <= 0
            or p.side * (p.stop - p.initial_stop) < 0
            or p.side * (p.target / p.entry - 1) <= p.break_even_fraction):
        raise ValueError('micro_exit_geometry_or_cost_floor_invalid')
    if not f.cutoff <= f.known_at <= now:
        raise ValueError('future_exit_features')
    liquidation = liquidation_mark({'side': p.side, 'qty': p.quantity, 'entry': p.entry,
                                    'margin': p.margin, 'funding': p.funding})
    # Liquidation remains independent of discretionary rules. A candle may
    # trigger a risk proposal only if its full interval follows the entry.
    if (completed_mark is not None and (completed_mark.start < p.opened_at
            or completed_mark.start + MINUTE > now)):
        raise ValueError('partial_entry_or_future_candle_cannot_determine_exit')
    adverse = (completed_mark.low if p.side == 1 else completed_mark.high) if completed_mark else ticker.mark
    if p.side * (adverse - liquidation) <= 0:
        return ExitProposal('LIQUIDATION_RISK_NOT_A_NORMAL_STOP', True, p.stop, now)
    if (not ticker.exchange_at <= ticker.received_at <= now or now - ticker.exchange_at > 2000
            or not book.exchange_at <= book.received_at <= now or now - book.exchange_at > BOOK_MAX_AGE_MS):
        return ExitProposal('STALE_DATA_RISK_REQUIRES_FRESH_PROTECTION', True, p.stop, now)
    if not book.bids or not book.asks or book.spread < 0:
        return ExitProposal('UNPRICEABLE_LIQUIDITY_RISK', True, p.stop, now)
    if p.side * (ticker.mark - liquidation) / ticker.mark <= max(2 * f.atr_fraction, 4 * book.spread):
        return ExitProposal('LIQUIDATION_BUFFER_RISK', True, p.stop, now)
    if p.side * (adverse - p.stop) <= 0:
        return ExitProposal('PROTECTIVE_STOP', True, p.stop, now)
    try:
        exit_price = vwap(book.bids if p.side == 1 else book.asks, p.quantity) * (1 - p.side * SLIPPAGE_FLOOR)
    except ValueError:
        return ExitProposal('UNPRICEABLE_LIQUIDITY_RISK', True, p.stop, now)
    if p.side * (book.mid - exit_price) / book.mid > max(2 * f.atr_fraction, 4 * book.spread):
        return ExitProposal('LIQUIDITY_IMPACT_RISK', True, p.stop, now)
    if ticker.next_funding_at <= now + MINUTE:
        return ExitProposal('UNKNOWN_SETTLEMENT_NEAR_FUNDING', True, p.stop, now)
    if (book.spread > max(p.entry_spread_fraction * 2, f.atr_fraction)
            or abs(ticker.mark / book.mid - 1) > D('.0025')):
        return ExitProposal('SPREAD_OR_MARK_DEVIATION_RISK', True, p.stop, now)
    fees = p.entry_fee + exit_price * p.quantity * FEE
    net_now = p.side * p.quantity * (exit_price - p.entry) + p.funding - fees
    # A target needs a marketable price and positive net estimate. No partial
    # or patient-limit fill is fabricated from an OHLC high/low touch.
    if p.side * (exit_price - p.target) >= 0 and net_now > 0:
        return ExitProposal('COST_COVERED_TARGET_PROPOSAL', True, p.stop, now)
    if now >= p.opened_at + p.max_holding_minutes * MINUTE:
        return ExitProposal('TIME_BUDGET_EXIT', True, p.stop, now)
    recent = f.one[-2:]
    post_entry = len(recent) == 2 and all(row.start >= p.opened_at for row in recent)
    if post_entry and p.structure_level is not None and all(p.side * (row.close - p.structure_level) < 0 for row in recent):
        return ExitProposal('STRUCTURE_FAILED_TWO_COMPLETED_CLOSES', True, p.stop, now)
    if post_entry and all(p.side * (row.close - row.open) < 0 for row in recent) and p.side * f.momentum_3m < 0:
        return ExitProposal('MOMENTUM_DETERIORATION', True, p.stop, now)
    # Trail only after costs and a noise buffer have been cleared. A proposal
    # is strictly monotone and applies only to subsequent observations.
    noise = max(f.atr_fraction * D('1.5'), book.spread * 4)
    signed_gain = p.side * (ticker.mark / p.entry - 1)
    stop = p.stop
    if signed_gain > p.break_even_fraction + 2 * noise:
        break_even = p.entry * (1 + p.side * p.break_even_fraction)
        trail = ticker.mark * (1 - p.side * noise)
        if p.side == 1:
            stop = max(p.stop, min(trail, ticker.mark * (1 - book.spread)), break_even)
        else:
            stop = min(p.stop, max(trail, ticker.mark * (1 + book.spread)), break_even)
    return ExitProposal('HOLD_WITH_MONOTONE_PROTECTION_PROPOSAL', False, stop, now)
