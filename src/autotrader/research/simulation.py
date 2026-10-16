"""Historical event loop using production signals, risk, IOC pricing and postings.

Durability/concurrency are verified by the PostgreSQL runtime suite, not simulated
here. OHLCV supplies explicit conservative liquidity assumptions, never real L2.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any

from autotrader.allocation import allocation_advice
from autotrader.clock import at
from autotrader.domain import (
    DataQuality,
    OrderBook,
    OrderBookLevel,
    Position,
    Side,
    TradingPair,
    quantize_down,
)
from autotrader.execution.postings import closing_posting
from autotrader.execution.pricing import quote_execution, target_gross_floor
from autotrader.execution.protection import trailing_update
from autotrader.execution.quality import ExecutionQualityEngine
from autotrader.portfolio import Portfolio
from autotrader.research.data import TIMEFRAMES, HistoricalBar, canonical, digest
from autotrader.research.panel import build_panel
from autotrader.research.strategies import REGISTRY, StrategyParameters, V4StrategyEngine
from autotrader.risk import RiskEngine, RiskLimits

D = Decimal
ZERO = D(0)


@dataclass(frozen=True)
class Costs:
    spread_bps: Decimal = Decimal(10)
    fee_bps: Decimal = Decimal(10)
    slippage_bps: Decimal = Decimal(8)
    liquidity_fraction: Decimal = Decimal(".01")


@dataclass
class SimPosition:
    position: Position
    strategy: str
    regime: str
    target: list[Decimal]
    target_remaining: list[Decimal]
    expiry: datetime
    atr_distance: Decimal
    mfe: Decimal = ZERO
    mae: Decimal = ZERO
    tp1_complete: bool = False


class ResearchSimulation:
    def __init__(self, bars: list[HistoricalBar]) -> None:
        if not bars or len({b.timeframe for b in bars}) != 1:
            raise ValueError("one_nonempty_research_timeframe_required")
        self.timeframe = bars[0].timeframe
        self.seconds = TIMEFRAMES[self.timeframe]
        self.frames, self.features, self.feature_manifest = build_panel(bars)
        self.times = sorted(self.frames)
        self._signal_cache: dict[str, dict[tuple[datetime, str], tuple[list[tuple[Decimal, str]], bool, str]]] = {}

    def run(self, *, start: datetime, end: datetime, strategy_ids: set[str],
            parameters: StrategyParameters | None = None, costs: Costs | None = None,
            member_parameters: dict[str, StrategyParameters] | None = None,
            legacy: bool = False, ai_mode: str = "RULE_ONLY") -> dict[str, Any]:
        params, model = parameters or StrategyParameters(), costs or Costs()
        if member_parameters is not None and set(member_parameters) != strategy_ids:
            raise ValueError("exact_frozen_parameters_required_for_every_member")
        members = member_parameters if member_parameters is not None else {s: params for s in strategy_ids}
        member_hashes = {s: digest(canonical(p.payload())) for s, p in members.items()}
        engines = {digest(canonical(p.payload())): V4StrategyEngine(p) for p in members.values()}
        legacy_engine: Any = None
        if legacy:
            from autotrader.strategies import LegacyStrategyEngine
            legacy_engine = LegacyStrategyEngine()
        if ai_mode not in {"RULE_ONLY", "RULE_PLUS_AI_MOCK"}:
            raise ValueError("historical_paid_ai_not_authorized_or_point_in_time_verified")
        cash = D(500)
        opened: dict[str, SimPosition] = {}
        closed: list[SimPosition] = []
        fills: list[dict[str, Any]] = []
        curve: list[dict[str, Any]] = []
        rejections: Counter[str] = Counter()
        marks: dict[str, Decimal] = {}
        mark_times: dict[str, datetime] = {}
        cooldowns: dict[str, datetime] = {}
        strategy_cooldowns: dict[str, datetime] = {}
        day_start, week_start = D(500), D(500)
        prior_day: Any = None
        prior_week: Any = None
        daily_entries = 0
        halted = False
        total_fees, turnover, exposure_sum = ZERO, ZERO, ZERO
        observation_count = 0
        total_spread, total_slippage = ZERO, ZERO
        asset_cashflows: dict[str, Decimal] = defaultdict(lambda: ZERO)
        regime_cashflows: dict[str, Decimal] = defaultdict(lambda: ZERO)
        observed_assets: set[str] = set()
        regime_observations: Counter[str] = Counter()
        risk = RiskEngine(RiskLimits())
        quality = ExecutionQualityEngine()
        specs = {s.strategy_id: s for s in REGISTRY}

        def equity() -> Decimal:
            return cash + sum((p.position.quantity * marks.get(symbol, p.position.average_entry_price)
                               for symbol, p in opened.items()), ZERO)

        for timestamp in self.times:
            if not start <= timestamp < end:
                continue
            frame = {c.symbol: c for c in self.frames[timestamp]}
            observed_assets.update(frame)
            context = self.features.get(timestamp, {})  # only bars completed BEFORE this open
            used: dict[str, Decimal] = defaultdict(lambda: ZERO)
            previous_equity = equity()
            for symbol, candle in frame.items():
                marks[symbol], mark_times[symbol] = candle.open, timestamp
            current_equity = equity()
            day = timestamp.date()
            week = timestamp.date() - timedelta(days=timestamp.weekday())
            if day != prior_day:
                day_start, prior_day, daily_entries = previous_equity, day, 0
            if week != prior_week:
                week_start, prior_week = previous_equity, week
            if current_equity - day_start <= -15 or current_equity - week_start <= -35:
                halted = True

            def book(symbol: str, price: Decimal, when: datetime,
                     _context: Any = context, _used: Any = used) -> OrderBook | None:
                # Current-bar volume is future information at its open. Only the
                # previous completed candle may define the modeled depth budget.
                known = _context.get(symbol)
                volume = D(str(known.metadata.get("last_volume", 0))) if known else ZERO
                available = max(volume * model.liquidity_fraction - _used[symbol], ZERO)
                if available <= 0:
                    return None
                half = price * model.spread_bps / 20000
                return OrderBook(symbol, when, (OrderBookLevel(price - half, available),),
                    (OrderBookLevel(price + half, available),), "historical-explicit-assumed-liquidity")

            def sell(symbol: str, price: Decimal, reason: str, when: datetime, target_number: int | None = None,
                     _used: Any = used) -> None:
                nonlocal cash, total_fees, turnover, total_spread, total_slippage
                p = opened[symbol]
                observation = book(symbol, price, when)
                if observation is None:
                    rejections["exit_no_assumed_liquidity"] += 1
                    return
                amount = p.target_remaining[target_number] if target_number is not None else p.position.quantity
                limit = target_gross_floor(p.target[target_number], model.fee_bps) if target_number is not None else None
                with at(when):
                    quote = quote_execution(observation, Side.SELL, min(amount, p.position.quantity),
                        fee_bps=model.fee_bps, slippage_bps=model.slippage_bps, limit_price=limit)
                if quote.fillable_quantity <= 0:
                    rejections["exit_limit_not_executable"] += 1
                    return
                posting = closing_posting(p.position.quantity, p.position.cost_basis,
                    quote.fillable_quantity, quote.gross_notional, quote.fee)
                cash += posting.cash_credit
                asset_cashflows[symbol] += posting.cash_credit
                regime_cashflows[p.regime] += posting.cash_credit
                p.position.quantity = posting.remaining_quantity
                p.position.cost_basis = posting.remaining_basis
                p.position.realized_pnl += posting.realized_pnl
                p.mfe = max(p.mfe, quote.vwap / p.position.average_entry_price - 1)
                p.mae = min(p.mae, quote.vwap / p.position.average_entry_price - 1)
                _used[symbol] += quote.fillable_quantity
                total_fees += quote.fee
                turnover += quote.gross_notional
                total_spread += quote.fillable_quantity * price * model.spread_bps / 20000
                total_slippage += quote.fillable_quantity * price * (1 - model.spread_bps / 20000) * model.slippage_bps / 10000
                if target_number is not None:
                    p.target_remaining[target_number] -= quote.fillable_quantity
                    if target_number == 0 and p.target_remaining[0] == 0:
                        p.tp1_complete = True
                fills.append({"position_id": p.position.position_id, "symbol": symbol, "timestamp": when.isoformat(),
                    "side": "SELL", "quantity": str(quote.fillable_quantity), "price": str(quote.vwap),
                    "fee": str(quote.fee), "realized_pnl": str(posting.realized_pnl), "reason": reason,
                    "target_number": target_number + 1 if target_number is not None else None,
                    "spread_cost":str(quote.fillable_quantity*price*model.spread_bps/20000),
                    "slippage_cost":str(quote.fillable_quantity*price*(1-model.spread_bps/20000)*model.slippage_bps/10000),
                    "strategy": p.strategy, "regime": p.regime, "mfe": str(p.mfe), "mae": str(p.mae)})
                if p.position.quantity == 0:
                    p.position.closed_at = when
                    closed.append(p)
                    del opened[symbol]
                    cooldowns[symbol] = when + timedelta(minutes=30)
                    strategy_cooldowns[p.strategy] = when + timedelta(minutes=5)

            with at(timestamp):
                for symbol in list(opened):
                    if symbol not in frame:
                        rejections["missing_position_market_data"] += 1
                        continue
                    p = opened[symbol]
                    bid = frame[symbol].open * (1 - model.spread_bps / 20000)
                    p.position.highest_price = max(p.position.highest_price or bid, bid)
                    if p.tp1_complete:
                        latest = context.get(symbol)
                        update = trailing_update(previous_stop=p.position.protective_stop or ZERO,
                            highest_bid=p.position.highest_price, basis=p.position.cost_basis,
                            quantity=p.position.quantity, distance=p.atr_distance,
                            atr=latest.atr if latest else None, fee_bps=model.fee_bps, slippage_bps=model.slippage_bps)
                        p.position.protective_stop, p.atr_distance = update.stop, update.distance
                    if p.position.protective_stop and bid <= p.position.protective_stop:
                        sell(symbol, frame[symbol].open, "STOP_GAP", timestamp)
                    elif timestamp >= p.expiry:
                        sell(symbol, frame[symbol].open, "TIME_EXIT", timestamp)
                    elif symbol in context:
                        from autotrader.research.regimes import Regime, classify
                        state = classify(context[symbol], context.get("BTC-EUR"), context.get("ETH-EUR"))
                        if state.regime in {Regime.BEAR, Regime.LIQUIDITY_STRESS}:
                            sell(symbol, frame[symbol].open, "REGIME_EXIT", timestamp)
                        else:
                            features = context[symbol]
                            high, close, resistance = features.metadata.get("last_high"), features.metadata.get("last_close"), features.resistance
                            if high and close and resistance and D(high) > resistance*D("1.001") and D(close) < resistance:
                                sell(symbol, frame[symbol].open, "FAILED_BREAKOUT", timestamp)

                candidates = []
                for symbol, f in context.items():
                    if symbol not in frame:
                        continue
                    if f.data_quality is not DataQuality.GOOD or not f.metadata.get("history_contiguous", True):
                        rejections["data_quality_or_history"] += 1
                        continue
                    eligible: list[tuple[Decimal, str]] = []
                    veto = False
                    if legacy:
                        signals = legacy_engine.generate(f, context.get("BTC-EUR"), context.get("ETH-EUR"))
                        eligible = [(s.score, s.strategy_id) for s in signals if s.score > 0]
                        veto = any(s.evidence.get("veto") for s in signals)
                        regime = "LEGACY"
                    else:
                        regime = "UNCERTAIN"
                        for identity, engine in engines.items():
                            cached = self._signal_cache.setdefault(identity, {})
                            key = (timestamp, symbol)
                            if key not in cached:
                                signals = engine.generate(f, context.get("BTC-EUR"), context.get("ETH-EUR"))
                                cached[key] = ([(s.score, s.strategy_id) for s in signals if s.evidence["entry_eligible"]],
                                    any(s.evidence.get("veto") for s in signals), str(f.metadata["regime_assessment"]["regime"]))
                            entries, blocked, regime = cached[key]
                            eligible.extend((score, s) for score, s in entries
                                if member_hashes.get(s) == identity)
                            veto |= blocked
                    regime_observations[regime] += 1
                    if veto or not eligible or (legacy and sum(score for score, _ in eligible) < D("1.2")):
                        rejections["regime_or_signal_ineligible"] += 1
                        continue
                    # Mock has no independent news or predictive evidence; identical
                    # qualified proposals give a matched integration comparison only.
                    primary = max(eligible) if legacy else min(eligible, key=lambda row: row[1])
                    candidates.append((sum(score for score, _ in eligible), symbol, primary[1], f, regime))
                for _, symbol, strategy, f, regime in sorted(candidates, key=lambda row: (-row[0], row[1])):
                    if halted:
                        rejections["persistent_equity_risk_halt"] += 1
                        continue
                    if symbol in opened or cooldowns.get(symbol, start) > timestamp or strategy_cooldowns.get(strategy, start) > timestamp:
                        rejections["position_or_cooldown"] += 1
                        continue
                    advice = allocation_advice(f.metadata, [context[s].metadata if s in context else {} for s in opened])
                    if not advice.accepted:
                        rejections.update(advice.reasons)
                        continue
                    if any(s not in frame or (timestamp - mark_times.get(s, start)).total_seconds() > self.seconds for s in opened):
                        rejections["stale_open_position_valuation"] += 1
                        continue
                    price = frame[symbol].open
                    selected_params = members.get(strategy, params)
                    atr = f.atr or price * D(".02")
                    stop = price - atr * selected_params.stop_atr
                    targets = [price + atr * selected_params.target_atr * i for i in (1, 2, 3)]
                    quote_amount = min(D(75), max(cash - 150, ZERO), D(5) / (atr * selected_params.stop_atr / price + D(".01")))
                    pair = TradingPair(symbol, symbol.split("-")[0], "EUR", min_order_quote=D(5))
                    quantity = quantize_down(quote_amount / (price * D("1.005")), pair.quantity_step)
                    portfolio = Portfolio(cash)
                    portfolio.positions = {s: replace(p.position, average_entry_price=marks.get(s, p.position.average_entry_price)) for s, p in opened.items()}
                    check = risk.evaluate_entry(portfolio, pair, quote_amount, price, stop, daily_entries,
                        equity() - day_start, equity() - week_start)
                    if not check.accepted:
                        rejections.update(check.reasons)
                        continue
                    observation = book(symbol, price, timestamp)
                    if observation is None:
                        rejections["entry_no_assumed_liquidity"] += 1
                        continue
                    feasibility = quality.evaluate(pair, observation, quantity, quote_amount,
                        model.fee_bps, model.slippage_bps, targets)
                    if feasibility.rejection_reasons:
                        rejections.update(feasibility.rejection_reasons)
                        continue
                    quote = feasibility.entry
                    cash += quote.net_cash_change
                    asset_cashflows[symbol] += quote.net_cash_change
                    regime_cashflows[regime] += quote.net_cash_change
                    used[symbol] += quote.fillable_quantity
                    total_fees += quote.fee
                    turnover += quote.gross_notional
                    total_spread += quote.fillable_quantity * price * model.spread_bps / 20000
                    total_slippage += quote.fillable_quantity * price * (1 + model.spread_bps / 20000) * model.slippage_bps / 10000
                    daily_entries += 1
                    position_id = f"research-{symbol}-{timestamp.isoformat()}"
                    position = Position(position_id, symbol, quote.fillable_quantity, quote.vwap, timestamp,
                        protective_stop=stop, cost_basis=-quote.net_cash_change, highest_price=observation.best_bid)
                    quantities = [quantize_down(quote.fillable_quantity * D(fraction), pair.quantity_step) for fraction in (".3", ".4")]
                    quantities.append(quote.fillable_quantity - sum(quantities))
                    holding = specs[strategy].holding_bars if strategy in specs else 12
                    opened[symbol] = SimPosition(position, strategy, regime, targets, quantities,
                        timestamp + timedelta(seconds=self.seconds * holding), atr * selected_params.stop_atr)
                    fills.append({"position_id": position_id, "symbol": symbol, "timestamp": timestamp.isoformat(),
                        "side": "BUY", "quantity": str(quote.fillable_quantity), "price": str(quote.vwap), "fee": str(quote.fee),
                        "strategy": strategy, "regime": regime, "source_feature_start": f.timestamp.isoformat(),
                        "feature_available_at": f.metadata["available_at"], "parameters": selected_params.payload(),
                        "parameter_hash": digest(canonical(selected_params.payload())), "strategy_version": specs[strategy].version if strategy in specs else "3.4.0", "ai_mode": ai_mode})
                    fills[-1].update(spread_cost=str(quote.fillable_quantity*price*model.spread_bps/20000),
                        slippage_cost=str(quote.fillable_quantity*price*(1+model.spread_bps/20000)*model.slippage_bps/10000))

            close_time = timestamp + timedelta(seconds=self.seconds)
            for symbol in list(opened):
                if symbol not in frame:
                    continue
                candle, p = frame[symbol], opened[symbol]
                factor = 1 - model.spread_bps / 20000
                if p.position.protective_stop and candle.low * factor <= p.position.protective_stop:
                    # Intrabar ordering is unknown: do not attribute later highs
                    # or lows to a position that may already have stopped out.
                    p.mfe = max(p.mfe, candle.open / p.position.average_entry_price - 1)
                    sell(symbol, min(candle.open, p.position.protective_stop / factor), "STOP_INTRABAR_CONSERVATIVE", close_time)
                else:
                    p.mfe = max(p.mfe, candle.high / p.position.average_entry_price - 1)
                    p.mae = min(p.mae, candle.low / p.position.average_entry_price - 1)
                    target_index = next((i for i, q in enumerate(p.target_remaining) if q > 0), None)
                    if target_index is not None and candle.close * factor >= p.target[target_index]:
                        sell(symbol, candle.close, "TAKE_PROFIT_CLOSE_IOC", close_time, target_index)
                    if symbol in opened and p.tp1_complete:
                        bid = candle.close * factor
                        p.position.highest_price = max(p.position.highest_price or bid, bid)
                        # Today's completed close may inform tomorrow's stop. The
                        # low test above always uses the previously active stop.
                        latest = self.features.get(close_time, {}).get(symbol)
                        update = trailing_update(previous_stop=p.position.protective_stop or ZERO,
                            highest_bid=p.position.highest_price, basis=p.position.cost_basis,
                            quantity=p.position.quantity, distance=p.atr_distance,
                            atr=latest.atr if latest else None, fee_bps=model.fee_bps, slippage_bps=model.slippage_bps)
                        p.position.protective_stop, p.atr_distance = update.stop, update.distance
            for symbol, candle in frame.items():
                marks[symbol], mark_times[symbol] = candle.close, close_time
            current_equity = equity()
            if current_equity - day_start <= -15 or current_equity - week_start <= -35:
                halted = True
            exposure_sum += sum((p.position.quantity * marks[s] for s, p in opened.items()), ZERO)
            observation_count += 1
            curve.append({"timestamp": close_time.isoformat(), "equity": str(current_equity), "cash": str(cash),
                "open_positions": len(opened), "risk_halted": halted,
                "asset_pnl_contributions":{s:str(asset_cashflows[s]+(opened[s].position.quantity*marks[s] if s in opened else ZERO)) for s in sorted(observed_assets)},
                "regime_pnl_contributions":{r:str(regime_cashflows[r]+sum((p.position.quantity*marks[s] for s,p in opened.items() if p.regime==r),ZERO)) for r in sorted(regime_cashflows)}})
            if cash < 0 or len(opened) > 3:
                raise AssertionError("research_hard_risk_invariant_breached")
        result = summarize(curve, closed, fills, total_fees, turnover, self.seconds,
            exposure_sum / observation_count if observation_count else ZERO)
        result.update({"parameters": params.payload(), "costs": {k: str(v) for k, v in asdict(model).items()},
            "member_parameters": {s: p.payload() for s, p in sorted(members.items())},
            "spread_cost": str(total_spread), "slippage_cost": str(total_slippage),
            "start": start.isoformat(), "end_exclusive": end.isoformat(), "timeframe": self.timeframe,
            "strategy_ids": sorted(strategy_ids), "legacy_signal_baseline": legacy, "ai_mode": ai_mode,
            "rejections": dict(rejections), "regime_observations": dict(regime_observations),
            "open_positions_at_end": [{"symbol": s, "quantity": str(p.position.quantity), "cost_basis": str(p.position.cost_basis)} for s, p in opened.items()],
            "curve": curve, "fills": fills, "feature_manifest": self.feature_manifest,
            "closed_positions": [{"position_id": p.position.position_id, "symbol": p.position.symbol,
                "strategy": p.strategy, "regime": p.regime, "opened_at": p.position.opened_at.isoformat(),
                "closed_at": p.position.closed_at.isoformat() if p.position.closed_at else None,
                "realized_pnl": str(p.position.realized_pnl), "mfe": str(p.mfe), "mae": str(p.mae)} for p in closed],
            "assumptions": {"historical_l2": False, "execution": "next observed open after completed signal; targets close-only IOC; stop-first adverse gap; shared per-bar volume participation",
                "durability": "in-memory historical event simulation; PostgreSQL durability tested separately",
                "valuation": "remaining open positions marked at last observed close, not forcibly liquidated",
                "ai": "mock integration only; no paid AI edge conclusion", "legacy": "V3.4 signals evaluated on common V4 execution/cost/risk assumptions"}})
        return result


def summarize(curve: list[dict[str, Any]], closed: list[SimPosition], fills: list[dict[str, Any]],
              fees: Decimal, turnover: Decimal, seconds: int, exposure: Decimal) -> dict[str, Any]:
    values = [500.0] + [float(row["equity"]) for row in curve]
    peak, dd, dd_curve = 500.0, 0.0, []
    for row in curve:
        value = float(row["equity"])
        peak = max(peak, value)
        drawdown = (peak - value) / peak
        dd = max(dd, drawdown)
        dd_curve.append({"timestamp": row["timestamp"], "drawdown": drawdown})
    returns = [right / left - 1 for left, right in pairwise(values) if left > 0]
    mean = sum(returns) / len(returns) if returns else 0
    std = math.sqrt(sum((r - mean) ** 2 for r in returns) / len(returns)) if returns else 0
    downside = math.sqrt(sum(min(r, 0) ** 2 for r in returns) / len(returns)) if returns else 0
    pnl = [float(p.position.realized_pnl) for p in closed]
    wins, losses = [p for p in pnl if p > 0], [-p for p in pnl if p < 0]
    expectancy = sum(pnl) / len(pnl) if pnl else 0
    variance = sum((p - expectancy) ** 2 for p in pnl) / len(pnl) if pnl else 0
    streak = longest = 0
    for p in pnl:
        streak = streak + 1 if p < 0 else 0
        longest = max(longest, streak)
    contribution: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_regime: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for fill in fills:
        if fill["side"] == "SELL":
            contribution[fill["strategy"]] += D(fill["realized_pnl"])
            by_regime[fill["regime"]] += D(fill["realized_pnl"])
    grouped: dict[str, dict[str, Any]] = {}
    for dimension in ("asset", "regime"):
        groups: dict[str, list[float]] = defaultdict(list)
        for position in closed:
            key = position.position.symbol if dimension == "asset" else position.regime
            groups[key].append(float(position.position.realized_pnl))
        for row in curve:
            for key in row.get(dimension+'_pnl_contributions',{}):
                groups.setdefault(key,[])
        grouped[dimension] = {key: {"closed_positions": len(rows), "net_realized_pnl": sum(rows),
            "win_rate": sum(p > 0 for p in rows) / len(rows) if rows else 0,
            "profit_factor": sum(max(p, 0) for p in rows) / -sum(min(p, 0) for p in rows) if any(p < 0 for p in rows) else None,
            "expectancy": sum(rows) / len(rows) if rows else 0} for key, rows in groups.items()}
        for key, metric in grouped[dimension].items():
            contributions=[float(row.get(dimension+'_pnl_contributions',{}).get(key,0)) for row in curve]
            peak, worst=500.0,0.0
            for value in contributions:
                peak=max(peak,500+value)
                worst=max(worst,(peak-500-value)/peak)
            relevant=[f for f in fills if f['symbol' if dimension=='asset' else 'regime']==key]
            metric.update(net_profit=contributions[-1] if contributions else 0,
                return_on_common_eur500=(contributions[-1]/500) if contributions else 0,max_drawdown_on_common_eur500=worst,
                fees=str(sum((D(f['fee']) for f in relevant),ZERO)),
                spread_cost=str(sum((D(f.get('spread_cost','0')) for f in relevant),ZERO)),
                slippage_cost=str(sum((D(f.get('slippage_cost','0')) for f in relevant),ZERO)),
                attribution_policy='Contribution to shared EUR500 portfolio, marked residual positions; not independent asset allocations or stand-alone returns.')
    return {"net_profit": values[-1] - 500, "total_return": values[-1] / 500 - 1, "max_drawdown": dd,
        "trades": len(pnl), "fills_count": len(fills), "gross_profit": sum(wins), "gross_loss": -sum(losses),
        "grouped_closed_position_statistics": grouped,
        "profit_factor": sum(wins) / sum(losses) if losses else None,
        "win_rate": len(wins) / len(pnl) if pnl else 0, "average_gain": sum(wins) / len(wins) if wins else 0,
        "average_loss": -sum(losses) / len(losses) if losses else 0, "expectancy": expectancy,
        "expectancy_normal_95_interval": [expectancy - 1.96 * math.sqrt(variance / len(pnl)), expectancy + 1.96 * math.sqrt(variance / len(pnl))] if pnl else None,
        "uncertainty": "Normal interval is descriptive; overlapping positions and serial dependence reduce effective sample size; gates use unique entry dates",
        "effective_independent_entry_dates": len({p.position.opened_at.date() for p in closed}),
        "sharpe_ratio": mean / std * math.sqrt(365 * 86400 / seconds) if std else None,
        "sortino_ratio": mean / downside * math.sqrt(365 * 86400 / seconds) if downside else None,
        "turnover": str(turnover / 500), "fees": str(fees), "average_exposure_eur": str(exposure),
        "average_holding_seconds": sum((p.position.closed_at - p.position.opened_at).total_seconds() for p in closed if p.position.closed_at) / len(closed) if closed else 0,
        "longest_losing_streak": longest, "worst_closed_position": min(pnl) if pnl else None,
        "per_strategy_realized_pnl": {k: str(v) for k, v in contribution.items()},
        "per_regime_realized_pnl": {k: str(v) for k, v in by_regime.items()}, "drawdown_curve": dd_curve}
