"""Read-only metrics for unchanged V4.9.6 balances, contracts and event history."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from autotrader.perpetuals.engine import FEE, INITIAL, POLICY, SLIP, liquidation_mark

D = Decimal


def strategy_summary(pending: dict[str, Any] | None) -> dict[str, Any]:
    return {
        'identity': POLICY, 'timeframe': '15m signal / 1m candle protection',
        'qualification': 'UNVALIDATED_BASELINE', 'market_regime': None,
        'signal_direction': ('LONG' if pending['side'] == 1 else 'SHORT') if pending else None,
        'execution_classification': 'LEGACY_HYPOTHETICAL_CANDLE_OPEN_PROXY',
        'cost_basis': 'Fixed model; funding additional, observed spread and future depth unavailable',
        'fee_per_side_pct': FEE * 100, 'slippage_per_side_pct': SLIP * 100,
        'approximate_round_trip_cost_pct': 2 * (FEE + SLIP) * 100,
        'break_even_underlying_move_long_pct': ((1 + SLIP) * (1 + FEE) / ((1 - SLIP) * (1 - FEE)) - 1) * 100,
        'break_even_underlying_move_short_pct': (1 - (1 - SLIP) * (1 - FEE) / ((1 + SLIP) * (1 + FEE))) * 100,
        'expected_net_target': None,
        'limitation': 'Retrospective candle prices cannot establish executable micro-move fills',
    }


def account_metrics(account: dict[str, Any], equity: Decimal, mark: Decimal | None,
                    *, fresh: bool) -> dict[str, Any]:
    p = account['position']
    result: dict[str, Any] = {
        'account_net_pnl_usdt': equity - INITIAL,
        'account_roi_pct': (equity / INITIAL - 1) * 100,
        'account_roi_denominator_usdt': INITIAL,
        'account_valuation_basis': 'Unchanged legacy mark equity and close-fee convention; no extra closing slippage reserve',
        'closed_realized_net_pnl_usdt': D(account['realized']),
        'valuation_fresh': fresh, 'position_metrics': None,
    }
    if p is None or mark is None:
        return result
    qty, entry, margin = D(p['qty']), D(p['entry']), D(p['margin'])
    side, entry_fee, funding = p['side'], D(p['entry_fee']), D(p['funding'])
    gross = side * qty * (mark - entry)
    estimated_exit_price = mark * (1 - side * SLIP)
    estimated_exit_fee = qty * estimated_exit_price * FEE
    estimated_exit_slippage = qty * mark * SLIP
    net = side * qty * (estimated_exit_price - entry) + funding - entry_fee - estimated_exit_fee
    entry_equity = D(account['cash']) + margin + entry_fee
    liq = liquidation_mark(p)
    result['position_metrics'] = {
        'underlying_price_change_pct': (mark / entry - 1) * 100,
        'direction_adjusted_price_change_pct': side * (mark / entry - 1) * 100,
        'gross_unrealized_pnl_usdt': gross,
        'estimated_net_unrealized_pnl_usdt': net,
        'funding_net_usdt': funding, 'entry_fee_paid_usdt': entry_fee,
        'estimated_exit_fee_usdt': estimated_exit_fee,
        'estimated_exit_slippage_usdt': estimated_exit_slippage,
        'estimated_exit_price': estimated_exit_price,
        'underlying_change_basis': 'Current mark versus recorded entry; legacy entry-mid was not stored',
        'gross_margin_roi_pct': gross / margin * 100 if margin else None,
        'estimated_net_margin_roi_pct': net / margin * 100 if margin else None,
        'margin_roi_denominator_usdt': margin,
        'estimated_position_account_roi_pct': net / entry_equity * 100 if entry_equity else None,
        'entry_account_equity_denominator_usdt': entry_equity,
        'margin_utilization_pct': margin / equity * 100 if equity > 0 else None,
        'entry_notional_usdt': qty * entry, 'mark_notional_usdt': qty * mark,
        'liquidation_distance_pct': side * (mark - liq) / mark * 100,
        'estimated_net_at_existing_target_usdt': qty * (
            side * (D(p['target']) * (1 - side * SLIP) - entry)
            - D(p['target']) * (1 - side * SLIP) * FEE) + funding - entry_fee,
        'basis': 'Current mark and fixed closing cost model; future funding/depth unknown. '
                 'Uncapped estimate before the legacy isolated settlement adjustment.',
    }
    return result
