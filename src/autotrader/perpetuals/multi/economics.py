"""Size matched virtual cohorts; target/stop net scenarios, never fabricated EV."""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_UP
from typing import Any

from autotrader.perpetuals.micro.execution import estimate
from autotrader.perpetuals.micro.types import Book, Intent, Ticker
from autotrader.perpetuals.multi.contracts import Contract, liquidation
from autotrader.perpetuals.multi.policy import (
    D,FEE,RISK,INTENT_TTL,MAX_ASSET_NOTIONAL,MAX_TOTAL_NOTIONAL,MAX_TRADE_MARGIN,TARGET_TRADE_MARGIN,TARGET_ASSET_EQUITY,SLIP,
)
from autotrader.perpetuals.multi.strategies import Signal


def price_round(value, tick, up: bool):
    return (value/tick).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN)*tick


def plan(signal: Signal, leverage: int, equity, free, contract: Contract, book: Book, ticker: Ticker, now: int) -> dict[str,Any]:
    if signal.reasons:raise ValueError(';'.join(signal.reasons))
    if not signal.decision_at<=ticker.exchange_at<=ticker.received_at<=now or now-ticker.exchange_at>3000:
        raise ValueError('stale_or_predecision_mark')
    side=signal.side;mid=book.mid
    if ticker.next_funding_at<=now+signal.hold_minutes*60_000+INTENT_TTL:
        raise ValueError('holding_window_crosses_unknown_funding')
    if abs(ticker.mark/mid-1)>D('.0025'):raise ValueError('mark_price_divergence')
    stop=price_round(D(signal.stop),contract.price_tick,up=side==1)
    target=price_round(D(signal.target),contract.price_tick,up=side==-1)
    room=side*(target/mid-1)
    if not D('.005')<=room<=D('.01'):raise ValueError('remaining_target_outside_half_to_one_percent')
    stop_fraction=side*(mid-stop)/mid
    if stop_fraction<=max(book.spread*4,D(signal.evidence['atr_fraction'])):
        raise ValueError('stop_inside_noise_or_wrong_side')
    cap=min(equity*TARGET_ASSET_EQUITY,MAX_TOTAL_NOTIONAL,MAX_ASSET_NOTIONAL,free*TARGET_TRADE_MARGIN*leverage)
    quantity=(min(cap,equity*RISK/(stop_fraction+2*(FEE+D('.0005'))+book.spread))/(mid*(1+book.spread+SLIP))/contract.step).to_integral_value(rounding=ROUND_DOWN)*contract.step
    for _ in range(3):
        contract.validate_size(quantity,mid,leverage)
        quote=estimate(Intent(signal.id,signal.policy,side,quantity,signal.decision_at,signal.decision_at+INTENT_TTL),book,now)
        latency=D(now-signal.decision_at)/60_000*D(signal.evidence['atr_fraction'])
        exit_factor=quote.exit_now/mid
        def net(exit_mid):
            exit_price=exit_mid*exit_factor
            return quantity*(side*(exit_price-quote.entry)-FEE*(quote.entry+exit_price)-mid*latency)
        loss=max(D(0),-net(stop));notional=quantity*quote.entry;margin=notional/leverage
        if loss<=equity*RISK:break
        quantity=(quantity*equity*RISK/loss/contract.step).to_integral_value(rounding=ROUND_DOWN)*contract.step
    else:raise ValueError('risk_size_did_not_converge')
    contract.validate_size(quantity,quote.entry,leverage)
    gain=net(target)
    if loss<=0 or gain<=0 or gain/loss<D('1.1'):raise ValueError('net_target_or_reward_risk_insufficient')
    # Reprice/size is checked again after the durable reservation and new quote.
    if notional>cap or margin+notional*FEE>free or margin>free*MAX_TRADE_MARGIN:
        raise ValueError('trade_margin_or_notional_cap')
    p={'side':side,'quantity':quantity,'entry':quote.entry,'margin':margin,'funding':'0'}
    liq=liquidation(contract,p)
    if side*(stop-liq)/ticker.mark<max(D(signal.evidence['atr_fraction'])*2,book.spread*4):
        raise ValueError('inadequate_liquidation_buffer')
    # Reservation includes room for a bounded adverse reprice; unused collateral returns on fill.
    reserved=margin+notional*FEE+notional*D('.001')
    if reserved>free:raise ValueError('reservation_exceeds_free_collateral')
    return {'leverage':leverage,'quantity':quantity,'entry_estimate':quote.entry,'stop':stop,'target':target,
        'margin_estimate':margin,'reserved':reserved,'planned_loss':loss,'scenario_gain':gain,
        'round_trip_cost_pct':max(D(0),-net(mid))/notional*100,
        'break_even_move_pct':(((side+FEE)*quote.entry+mid*latency)/((side-FEE)*mid*exit_factor)-1)/side*100,
        'net_target_margin_roi_pct':gain/margin*100,'net_target_account_roi_pct':gain/equity*100,
        'expected_net_pnl_usdt':None,'win_probability':None,'notional':notional,
        'liquidation_mark':liq,'liquidation_buffer_pct':side*(ticker.mark-liq)/ticker.mark*100,
        'qualification':'EXPERIMENTAL_DETERMINISTIC_SCENARIO','quote_evidence_id':quote.evidence_id,
        'latency_stress_fraction':latency,'initial_account_equity':equity,'initial_spread':book.spread}
