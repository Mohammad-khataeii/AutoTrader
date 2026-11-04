"""Cost, risk and competing-outcome arithmetic. No model is fitted or loaded here. Untested and unvalidated."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal, ROUND_DOWN
from typing import Any

from autotrader.perpetuals.engine import DRAWDOWN_LIMIT, FEE, RISK, liquidation_mark
from autotrader.perpetuals.market import MINUTE, Instrument
from autotrader.perpetuals.micro.execution import INTENT_TTL_MS, estimate
from autotrader.perpetuals.micro.types import (
    FEATURE_SCHEMA, OUTCOME_SCHEMA, Book, Candidate, DepthEstimate, Features,
    Intent, OutcomeEvidence, Ticker,
)

D = Decimal
COST_FINGERPRINT = hashlib.sha256(
    b'micro-cost/1;fee=.0006;residual-slip=.0005;exit=same-depth-stress;latency=atr-per-minute;funding=unknown-if-crossed'
).hexdigest()


def qualified(e: OutcomeEvidence | None, c: Candidate, f: Features, quote: DepthEstimate) -> bool:
    if e is None:
        return False
    numbers = (e.probability_target, e.probability_stop, e.probability_time,
               e.time_exit_signed_move, e.expected_holding_minutes, e.expected_mae_fraction)
    if any(not value.is_finite() for value in numbers):
        return False
    return (
        e.reviewed and bool(e.model_id) and e.independent_labels >= 300
        and e.policy == c.policy and e.regime == f.regime and e.cost_fingerprint == COST_FINGERPRINT
        and e.feature_schema == FEATURE_SCHEMA and e.outcome_schema == OUTCOME_SCHEMA
        and e.source_feature_hash == f.source_hash
        and e.trained_through < e.calibrated_through < e.evaluated_through < c.decision_at
        <= e.predicted_at <= quote.quoted_at < e.valid_until
        and all(0 <= value <= 1 for value in (e.probability_target, e.probability_stop, e.probability_time))
        and abs(e.probability_target + e.probability_stop + e.probability_time - 1) <= D('1e-12')
        and -c.stop_fraction <= e.time_exit_signed_move <= c.target_fraction
        and 0 < e.expected_holding_minutes <= c.max_holding_minutes and e.expected_mae_fraction >= 0
    )


def score(c: Candidate, f: Features, account: dict[str, Any], book: Book, ticker: Ticker,
          instrument: Instrument, now: int, evidence: OutcomeEvidence | None = None) -> dict[str, Any]:
    """Scenario gains are distinct from expected gains; absent outcome evidence abstains."""
    reasons = list(c.rejection_reasons)
    base: dict[str, Any] = {
        'policy': c.policy, 'direction': 'LONG' if c.side == 1 else 'SHORT',
        'leverage': account['leverage'], 'regime': f.regime, 'feature_schema': FEATURE_SCHEMA,
        'feature_hash': f.source_hash, 'decision_at': c.decision_at, 'cutoff': c.cutoff,
        'candidate_move_pct': c.target_fraction * 100, 'stop_distance_pct': c.stop_fraction * 100,
        'planned_max_holding_minutes': c.max_holding_minutes,
        'expected_underlying_move_pct': None, 'expected_net_move_pct': None,
        'estimated_round_trip_cost_pct': None, 'minimum_viable_move_pct': None,
        'expected_holding_minutes': None, 'estimated_win_probability': None,
        'probability_source': 'UNAVAILABLE_NO_QUALIFIED_MICRO_OUTCOME_MODEL',
        'probability_next_candle_up': None,
        'win_probability_definition': 'Target reached before stop or time; time outcomes are modeled separately',
        'expected_net_pnl_usdt': None,
        'expected_margin_roi_pct': None, 'expected_account_roi_pct': None,
        'potential_loss_usdt': None, 'liquidation_buffer_pct': None,
        'decision_confidence': 'UNQUALIFIED', 'qualification': 'UNQUALIFIED',
        'cost_fingerprint': COST_FINGERPRINT, 'execution_authorized': False,
        'execution_classification': 'HYPOTHETICAL_RESEARCH_NO_FILL',
        'signal_reasons': c.signal_reasons, 'assumptions_status': 'UNTESTED_UNVALIDATED',
        'indicative_funding_rate': ticker.indicative_funding_rate,
        'funding_cost_source': 'NO_EVENT_WITHIN_PLANNED_HORIZON_OR_UNKNOWN',
    }
    if (not c.target_fraction.is_finite() or not c.stop_fraction.is_finite()
            or not D('.002') <= c.target_fraction <= D('.01') or c.stop_fraction <= 0):
        reasons.append('geometry_outside_micro_research_scope')
    leverage = account['leverage']
    cash, equity = D(account['cash']), D(account['equity'])
    if leverage not in (1, 3, 10) or cash <= 0 or equity <= 0:
        reasons.append('invalid_or_depleted_account')
    if account.get('position') or account.get('halted'):
        reasons.append('existing_position_or_risk_halt')
    peak = D(account.get('peak', equity))
    if peak <= 0 or 1 - equity / peak >= DRAWDOWN_LIMIT:
        reasons.append('account_drawdown_limit')
    if (not c.decision_at <= ticker.exchange_at <= ticker.received_at <= now
            or now - ticker.exchange_at > 2000):
        reasons.append('stale_or_predecision_mark')
    if reasons and any(reason in reasons for reason in (
        'invalid_or_depleted_account', 'geometry_outside_micro_research_scope',
    )):
        return {**base, 'eligible_for_future_experiment': False, 'rejection_reasons': tuple(dict.fromkeys(reasons))}

    # No funding credit is assumed. If a funding event can occur, the cost is
    # unknown until a separately reviewed stress bound is supplied in a new policy.
    funding = D(0) if ticker.next_funding_at > c.decision_at + c.max_holding_minutes * MINUTE + INTENT_TTL_MS else None
    if funding is None:
        reasons.append('funding_exposure_cost_unknown')
    cap = min(cash * D('.25') * leverage, equity * 2, D(2000))
    risk_budget = equity * RISK
    budget = min(cap, risk_budget / (c.stop_fraction + 2 * (FEE + D('.0005')) + book.spread))
    quantity = (budget / book.mid / instrument.step).to_integral_value(rounding=ROUND_DOWN) * instrument.step
    key = hashlib.sha256(f'{c.policy}:{c.decision_at}:{c.side}:{leverage}:{f.source_hash}'.encode()).hexdigest()
    intent = Intent(key, c.policy, c.side, quantity, c.decision_at, c.decision_at + INTENT_TTL_MS)
    target = c.reference * (1 + c.side * c.target_fraction)
    stop = c.reference * (1 - c.side * c.stop_fraction)
    try:
        quote = estimate(intent, book, now)
        latency_fraction = f.atr_fraction * D(quote.quoted_at - c.decision_at) / MINUTE
        exit_factor = quote.exit_now / quote.mid

        def pnl_at(price: Decimal, q: DepthEstimate) -> Decimal:
            exit_price = price * exit_factor
            # Entry and exit prices already include depth, spread and one slippage floor.
            return q.quantity * (c.side * (exit_price - q.entry) - FEE * (q.entry + exit_price)
                                 - quote.mid * (latency_fraction + (funding or D(0))))

        planned_loss = max(D(0), -pnl_at(stop, quote))
        if planned_loss > risk_budget:
            smaller = (quantity * risk_budget / planned_loss / instrument.step).to_integral_value(rounding=ROUND_DOWN) * instrument.step
            quote = estimate(replace(intent, quantity=smaller), book, now)
            quantity = smaller
            # Recompute exit depth for the smaller size. No quote is promoted to a fill.
            exit_factor = quote.exit_now / quote.mid
            planned_loss = max(D(0), -pnl_at(stop, quote))
        notional, margin = quantity * quote.entry, quantity * quote.entry / leverage
        if quantity < instrument.min_qty or notional < instrument.min_notional:
            reasons.append('instrument_minimum_not_met')
        if planned_loss <= 0 or planned_loss > risk_budget:
            reasons.append('planned_loss_budget_exceeded_or_invalid')
        if notional > cap or margin + notional * FEE > cash or margin > cash * D('.25'):
            reasons.append('notional_or_margin_cap')
        if abs(ticker.mark / quote.mid - 1) > D('.0025'):
            reasons.append('mark_trade_deviation')
        if c.side * (target - quote.entry) <= 0 or c.side * (quote.entry - stop) <= 0:
            reasons.append('signal_geometry_consumed_before_quote')
        if c.stop_fraction < max(book.spread * 4, f.atr_fraction):
            reasons.append('stop_inside_spread_or_volatility_noise')
        if abs(quote.entry / c.reference - 1) > min(c.target_fraction / 3, f.atr_fraction):
            reasons.append('signal_move_already_consumed')
        prospective = {'side': c.side, 'qty': quantity, 'entry': quote.entry,
                       'margin': margin, 'funding': -notional * (funding or D(0))}
        liq = liquidation_mark(prospective)
        liquidation_buffer = c.side * (ticker.mark - liq) / ticker.mark
        stop_buffer = c.side * (stop - liq) / ticker.mark
        if liquidation_buffer <= 0 or stop_buffer < max(2 * f.atr_fraction, 2 * book.spread):
            reasons.append('insufficient_stop_to_liquidation_buffer')
        net_target, net_stop = pnl_at(target, quote), pnl_at(stop, quote)
        flat_cost = max(D(0), -pnl_at(quote.mid, quote)) / notional
        # Solve zero net P&L for a signed move from the current mid, including
        # exact long/short fee denominators and the modeled exit liquidity factor.
        minimum_move = (((c.side + FEE) * quote.entry + quote.mid * (latency_fraction + (funding or D(0))))
                        / ((c.side - FEE) * quote.mid * exit_factor) - 1) / c.side
        if net_target <= 0 or c.side * (target / quote.mid - 1) <= minimum_move:
            reasons.append('target_does_not_cover_modeled_costs')
        base.update(
            quantity=quantity, notional_usdt=notional, isolated_margin_usdt=margin,
            margin_utilization_pct=margin / equity * 100,
            estimated_entry=quote.entry, stop=stop, target=target,
            estimated_round_trip_cost_pct=flat_cost * 100 if funding is not None else None,
            minimum_viable_move_pct=max(D(0), minimum_move) * 100 if funding is not None else None,
            known_nonfunding_cost_pct=flat_cost * 100,
            cost_components={'entry_fee_pct': FEE * 100, 'exit_fee_rate_pct': FEE * 100,
                'entry_spread_depth_slippage_pct': quote.entry_cost_fraction * 100,
                'exit_spread_depth_slippage_pct': quote.exit_cost_fraction * 100,
                'observed_full_spread_pct': book.spread * 100,
                'latency_stress_pct': latency_fraction * 100,
                'funding_cost_pct': funding * 100 if funding is not None else None,
                'exit_liquidity_assumption': 'Current opposite-side depth held constant; future depth unknown'},
            potential_loss_usdt=planned_loss if funding is not None else None,
            stop_scenario_net_pnl_usdt=net_stop if funding is not None else None,
            target_scenario_net_pnl_usdt=net_target if funding is not None else None,
            target_scenario_margin_roi_pct=net_target / margin * 100 if funding is not None else None,
            target_scenario_account_roi_pct=net_target / equity * 100 if funding is not None else None,
            isolated_margin_at_risk_usdt=margin + notional * FEE,
            liquidation_buffer_pct=liquidation_buffer * 100,
            liquidation_mark=liq,
            liquidation_buffer_basis='At quoted entry, before unknown future funding',
            quote_evidence_id=quote.evidence_id,
            quote_at=quote.quoted_at, execution_classification=quote.classification,
            break_even_win_probability_two_barrier_only=(-net_stop / (net_target - net_stop)
                if net_target > 0 > net_stop and funding is not None else None),
        )
        if not qualified(evidence, c, f, quote):
            reasons.append('qualified_policy_specific_outcome_evidence_unavailable')
        elif evidence is not None and funding is not None:
            time_price = quote.mid * (1 + c.side * evidence.time_exit_signed_move)
            if not c.side * (time_price - stop) >= 0 or not c.side * (target - time_price) >= 0:
                raise ValueError('time_outcome_outside_repriced_barriers')
            ev = (evidence.probability_target * net_target + evidence.probability_stop * net_stop
                  + evidence.probability_time * pnl_at(time_price, quote))
            expected_move = (evidence.probability_target * c.side * (target / quote.mid - 1)
                             + evidence.probability_stop * c.side * (stop / quote.mid - 1)
                             + evidence.probability_time * evidence.time_exit_signed_move)
            base.update(qualification='QUALIFIED_RESEARCH_ONLY', decision_confidence='REVIEWED_RESEARCH_ESTIMATE',
                estimated_win_probability=evidence.probability_target, probability_source=evidence.model_id,
                expected_underlying_move_pct=expected_move * 100, expected_net_move_pct=ev / notional * 100,
                expected_holding_minutes=evidence.expected_holding_minutes, expected_net_pnl_usdt=ev,
                expected_margin_roi_pct=ev / margin * 100, expected_account_roi_pct=ev / equity * 100,
                expected_adverse_excursion_pct=evidence.expected_mae_fraction * 100)
            if evidence.expected_mae_fraction >= c.stop_fraction:
                reasons.append('predicted_adverse_excursion_exceeds_stop')
            if ev <= 0:
                reasons.append('nonpositive_expected_net_value')
    except (ValueError, ArithmeticError) as error:
        reasons.append(str(error))
    return {**base, 'eligible_for_future_experiment': not reasons,
            'rejection_reasons': tuple(dict.fromkeys(reasons))}
