"""Autonomous USD EOD paper ledger. Every financial mutation is transactional."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone

from .market import validate_bars
from .sessions import completed_day, history_days, instant, next_day, published_after, session
from .signals import POLICY_VERSION as SIGNAL_VERSION, evaluate
from .storage import connect

POLICY_VERSION = "stockswatch-eod-paper-v2.0"
EXECUTION_MODE = "EOD_OBSERVED_PAPER"
FRICTION_BPS = 12.0
MAX_POSITIONS = 5
MAX_SYMBOL_WEIGHT = 0.12
MAX_SECTOR_WEIGHT = 0.26
MAX_GROSS_EXPOSURE = 0.60
MAX_DRAWDOWN = 0.12
MAX_ONE_DAY_LOSS = 0.035
MAX_VOLATILITY = 0.70
SCORE_MIN = 2.0
SOURCE = "alpaca_iex_daily"
TRUSTED = (SOURCE, "RAW")


def order_key(symbol, day, side):
    return hashlib.sha256(f"sw1:{symbol}:{day}:{side}".encode()).hexdigest()[:28]


def latest_bars(symbol, max_count=600):
    with connect() as c:
        return history(c, symbol, "9999-12-31", max_count)


def history(c, symbol, day, count=201):
    """Prefer certified observations without overwriting legacy source evidence."""
    return [
        dict(row)
        for row in reversed(
            c.execute(
                """
        SELECT * FROM (
            SELECT * FROM sw_eod_observations WHERE symbol=:sym AND day<=:day
            UNION ALL
            SELECT b.* FROM bars b WHERE b.symbol=:sym AND b.day<=:day AND NOT EXISTS (
                SELECT 1 FROM sw_eod_observations o WHERE o.symbol=b.symbol AND o.day=b.day)
        ) ORDER BY day DESC LIMIT :count
        """,
                {"sym": symbol, "day": day, "count": count},
            ).fetchall()
        )
    ]


def execution_configuration_gate():
    if os.getenv("STOCKSWATCH_PRICE_PROVIDER", "stooq").lower() != "alpaca":
        return "source_not_configured_for_execution"
    if not all(os.getenv(k) for k in ("STOCKSWATCH_ALPACA_KEY", "STOCKSWATCH_ALPACA_SECRET")):
        return "alpaca_credentials_not_configured"
    return None


def evidence(c, symbol, day, now, since=None):
    check = c.execute("SELECT * FROM sw_price_checks WHERE symbol=?", (symbol,)).fetchone()
    bar = c.execute(
        "SELECT * FROM sw_eod_observations WHERE symbol=? AND day=?", (symbol, day)
    ).fetchone()
    if not check or check["day"] != day:
        return None, "price_check_pending"
    if check["status"] != "OK":
        return None, check["status"]
    if not bar:
        return None, "current_daily_bar_missing"
    if (bar["source"], bar["adjustment"]) != TRUSTED:
        return None, "unapproved_execution_source"
    if (
        not published_after(day)
        <= instant(bar["observed_at"])
        <= instant(check["checked_at"])
        <= now
    ):
        return None, "invalid_observation_time"
    if not validate_bars([dict(bar)], day):
        return None, "invalid_price"
    if not check["actions_since"] or check["actions_since"] > (since or day):
        return None, "corporate_action_coverage_missing"
    for event in json.loads(check["actions_json"]):
        event_day = event["day"]
        if (since or day) <= event_day <= day:
            return None, "corporate_action_requires_reconciliation"
    return dict(bar), None


def series(c, symbol, day, now, since=None):
    bar, reason = evidence(c, symbol, day, now, since)
    if reason:
        return None, [], reason
    bars = history(c, symbol, day)
    if len(bars) < 201:
        return bar, [], "insufficient_201_bar_history"
    if tuple(b["day"] for b in bars) != history_days(day):
        return bar, [], "history_session_gap"
    if any((b["source"], b["adjustment"]) != TRUSTED for b in bars):
        return bar, [], "mixed_source_or_adjustment"
    if len(validate_bars(bars, day)) != len(bars) or any(
        not published_after(b["day"]) <= instant(b["observed_at"]) <= now for b in bars
    ):
        return bar, [], "invalid_or_partial_history"
    if any(abs(b["o"] / prev["c"] - 1) > 0.15 for prev, b in zip(bars, bars[1:])):
        return bar, [], "historical_gap_or_split"
    return bar, bars, None


def portfolio_view(c, day, now):
    account = dict(c.execute("SELECT * FROM portfolio WHERE id=1").fetchone())
    positions = []
    for row in c.execute("SELECT * FROM positions ORDER BY symbol").fetchall():
        p = dict(row)
        bar, reason = evidence(c, p["symbol"], day, now, p["entry_day"])
        if bar:
            recent = history(c, p["symbol"], day, 2)
            if len(recent) == 2 and abs(bar["o"] / recent[0]["c"] - 1) > 0.15:
                bar, reason = None, "ambiguous_gap_or_split"
        # Keep the last certified mark for visibility on outages. Freeze to
        # acquisition cost when a corporate action makes share units ambiguous.
        if not bar and reason != "corporate_action_requires_reconciliation":
            bar = c.execute(
                "SELECT * FROM sw_eod_observations WHERE symbol=? AND day<? ORDER BY day DESC LIMIT 1",
                (p["symbol"], day),
            ).fetchone()
        mark = bar["c"] if bar else p["avg_cost"]
        value = p["qty"] * mark
        positions.append(
            {
                **p,
                "mark": mark,
                "market_day": bar["day"] if bar else None,
                "market_value": value,
                "unrealized": value - p["qty"] * p["avg_cost"],
                "mark_warning": reason,
            }
        )
    exposure = sum(p["market_value"] for p in positions)
    equity = account["cash"] + exposure
    drawdown = max(0.0, (account["high_water"] - equity) / max(1, account["high_water"]))
    return account, positions, equity, exposure, drawdown


def mark_to_market():
    now = datetime.now(timezone.utc)
    with connect() as c:
        c.execute("BEGIN")
        account, held, equity, exposure, dd = portfolio_view(c, completed_day(now), now)
    return account, held, round(equity, 2), round(exposure, 2), dd


def ledger_reconciles(c, account, held):
    totals = c.execute("""SELECT
        COALESCE(SUM(CASE side WHEN 'BUY' THEN -qty*price-fee ELSE qty*price-fee END),0),
        COALESCE(SUM(realized),0) FROM fills""").fetchone()
    shares = dict(
        c.execute("""SELECT symbol,SUM(CASE side WHEN 'BUY' THEN qty ELSE -qty END)
        FROM fills GROUP BY symbol HAVING SUM(CASE side WHEN 'BUY' THEN qty ELSE -qty END)!=0
        """).fetchall()
    )
    return (
        account["cash"] >= 0
        and math.isclose(
            account["initial_cash"] + totals[0], account["cash"], abs_tol=0.005, rel_tol=0
        )
        and math.isclose(totals[1], account["realized"], abs_tol=0.005, rel_tol=0)
        and shares == {p["symbol"]: p["qty"] for p in held}
        and not c.execute("""SELECT 1 FROM fills f LEFT JOIN pending_orders o ON o.id=f.order_id
            WHERE o.id IS NULL OR o.state!='FILLED' OR o.symbol!=f.symbol OR o.side!=f.side
                OR o.fill_day IS NOT f.fill_day OR f.qty<=0 OR f.price<=0 OR f.fee<0
            UNION ALL SELECT 1 FROM pending_orders o LEFT JOIN fills f ON f.order_id=o.id
            WHERE o.state='FILLED' AND f.id IS NULL LIMIT 1""").fetchone()
    )


def buy_gate(c, view, spy, day):
    account, held, equity, _, dd = view
    if account["paused"] or dd >= MAX_DRAWDOWN:
        return "drawdown_or_buy_pause"
    if not spy:
        return "benchmark_missing_or_stale"
    if spy[-1]["c"] <= sum(x["c"] for x in spy[-200:]) / 200:
        return "benchmark_risk_off"
    if any(p["mark_warning"] for p in held):
        return "held_mark_stale_or_ambiguous"
    previous = c.execute(
        "SELECT equity FROM equity_curve WHERE day<? ORDER BY day DESC LIMIT 1", (day,)
    ).fetchone()
    if previous and equity < previous["equity"] * (1 - MAX_ONE_DAY_LOSS):
        return "daily_loss_buy_pause"
    return None


def allocation(view, sector, reserved):
    account, held, equity, exposure, _ = view
    if len(held) + len(reserved) >= MAX_POSITIONS:
        return 0, "position_slot_cap"
    base = min(account["initial_cash"], equity)
    reserved_value = equity * MAX_SYMBOL_WEIGHT
    sector_exp = sum(p["market_value"] for p in held if p["sector"] == sector)
    caps = {
        "symbol_weight_cap": base * MAX_SYMBOL_WEIGHT,
        "cash_reserve_cap": account["cash"]
        - 0.40 * account["initial_cash"]
        - reserved_value * len(reserved),
        "gross_exposure_cap": equity * MAX_GROSS_EXPOSURE
        - exposure
        - reserved_value * len(reserved),
        "sector_exposure_cap": equity * MAX_SECTOR_WEIGHT
        - sector_exp
        - reserved_value * reserved.count(sector),
    }
    reason = min(caps, key=caps.get)
    return max(0, caps[reason]), reason


def outcome(c, order, state, reason, now, **detail):
    c.execute(
        "UPDATE pending_orders SET state=?,fill_day=? WHERE id=?",
        (state, detail.get("fill_day"), order["id"]),
    )
    c.execute(
        "INSERT INTO sw_order_outcomes VALUES(?,?,?,?)",
        (order["id"], reason, now.isoformat(), json.dumps(detail, sort_keys=True)),
    )


def settle(c, day, now, spy):
    """Re-read and fill under the same write transaction as account/risk checks."""
    result = {}
    orders = c.execute("""SELECT o.*,e.target_day,e.signal_source,e.signal_observed_at,a.sector,
        a.enabled FROM pending_orders o LEFT JOIN sw_order_evidence e ON e.order_id=o.id
        LEFT JOIN assets a ON a.symbol=o.symbol WHERE o.state='PENDING'
        ORDER BY CASE o.side WHEN 'SELL' THEN 0 ELSE 1 END,o.created_at,o.id""").fetchall()
    for order in orders:
        oid, sym, target = order["id"], order["symbol"], order["target_day"]
        if not target:
            outcome(c, order, "CANCELLED", "legacy_order_evidence_unavailable", now)
            result[oid] = "legacy_order_evidence_unavailable"
            continue
        if day > target or now >= session(next_day(target))[0]:
            outcome(c, order, "EXPIRED", "next_observation_window_missed", now)
            result[oid] = "next_observation_window_missed"
            continue
        if day < target:
            result[oid] = "awaiting_next_session_observation"
            continue
        configuration_gate = execution_configuration_gate()
        if configuration_gate:
            result[oid] = configuration_gate
            continue

        view = portfolio_view(c, day, now)
        account, positions, _, _, dd = view
        held = next((p for p in positions if p["symbol"] == sym), None)
        bar, reason = evidence(c, sym, day, now, held["entry_day"] if held else order["signal_day"])
        if reason:
            result[oid] = reason
            continue
        created = instant(order["created_at"])
        old = c.execute(
            "SELECT observed_at FROM bars WHERE symbol=? AND day=?", (sym, day)
        ).fetchone()
        reference = history(c, sym, order["signal_day"], 1)
        prev = reference[0] if reference and reference[0]["day"] == order["signal_day"] else None
        buying = order["side"] == "BUY"
        if not instant(order["signal_observed_at"]) <= created < min(
            instant(bar["observed_at"]), session(day)[0]
        ) or (old and instant(old["observed_at"]) <= created):
            reason = "observation_not_forward_of_order"
        elif (
            not prev
            or prev["source"] != bar["source"]
            or prev["adjustment"] != bar["adjustment"]
            or bar["source"] != order["signal_source"]
        ):
            reason = "execution_source_or_adjustment_changed"
        elif (
            max(abs(bar["o"] / prev["c"] - 1), abs(bar["c"] / prev["c"] - 1)) > 0.15
            or bar["h"] / bar["l"] > 1.25
        ):
            reason = "ambiguous_gap_or_split"
        elif buying and (held or not order["enabled"]):
            reason = "position_already_open_or_symbol_disabled"
        elif not buying and not held:
            reason = "position_no_longer_held"
        elif buying and bar["c"] * bar["v"] < 1_000_000:
            reason = "low_iex_dollar_volume"
        elif buying:
            reason = buy_gate(c, view, spy, day)
            if reason in {"benchmark_missing_or_stale", "held_mark_stale_or_ambiguous"}:
                result[oid] = reason
                continue
        price = bar["c"] * (1 + (1 if buying else -1) * FRICTION_BPS / 10000)
        fee = 0.0
        qty = 0
        if not reason:
            if buying:
                budget, cap = allocation(view, order["sector"], [])
                qty = int(budget / price)
                if qty < 1:
                    reason = cap
            else:
                qty = held["qty"]
        if reason:
            if dd >= MAX_DRAWDOWN:
                c.execute("UPDATE portfolio SET paused=1 WHERE id=1")
            outcome(c, order, "CANCELLED", reason, now)
            result[oid] = reason
            continue

        realized = 0.0
        if buying:
            c.execute("UPDATE portfolio SET cash=cash-? WHERE id=1", (qty * price + fee,))
            c.execute(
                "INSERT INTO positions VALUES(?,?,?,?,?,?)",
                (sym, qty, price, price * 0.92, day, order["sector"]),
            )
        else:
            proceeds = qty * price - fee
            realized = proceeds - qty * held["avg_cost"]
            c.execute(
                "UPDATE portfolio SET cash=cash+?,realized=realized+? WHERE id=1",
                (proceeds, realized),
            )
            c.execute("DELETE FROM positions WHERE symbol=?", (sym,))
        c.execute(
            "INSERT INTO fills VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "fill:" + oid,
                oid,
                sym,
                order["side"],
                order["signal_day"],
                day,
                qty,
                price,
                abs(price - bar["c"]),
                fee,
                realized,
                bar["source"],
                now.isoformat(),
            ),
        )
        outcome(
            c,
            order,
            "FILLED",
            "filled",
            now,
            mode=EXECUTION_MODE,
            fill_day=day,
            source=bar["source"],
            observed_at=bar["observed_at"],
            publication_at=published_after(day).isoformat(),
            price_rule="observed_daily_close",
            reference_price=bar["c"],
            slippage_bps=FRICTION_BPS,
            fee=fee,
        )
        result[oid] = "filled"
    return result


def eligible_signals():
    """Retain the research-facing preview contract with certified data only."""
    now = datetime.now(timezone.utc)
    day = completed_day(now)
    with connect() as c:
        c.execute("BEGIN")
        _, spy, _ = series(c, "SPY", day, now)
        output = []
        for a in c.execute(
            "SELECT symbol,name,sector FROM assets WHERE enabled=1 AND sector!='Benchmark'"
        ):
            bar, bars, _ = series(c, a["symbol"], day, now)
            ev = evaluate(bars, spy)
            if ev:
                output.append(
                    {
                        **dict(a),
                        "day": day,
                        **ev,
                        "source": bar["source"],
                        "adjustment": bar["adjustment"],
                    }
                )
    return sorted(output, key=lambda r: (-r["score"], r["symbol"])), day if spy else None


def queue(c, assets, view, day, now, spy, entry_gate, run_id):
    account, held, equity, exposure, _ = view
    held_by = {p["symbol"]: p for p in held}
    pending = c.execute("""SELECT o.symbol,o.side,a.sector FROM pending_orders o
        JOIN assets a USING(symbol) WHERE o.state='PENDING'""").fetchall()
    pending_symbols = {row["symbol"] for row in pending}
    reserved = [row["sector"] for row in pending if row["side"] == "BUY"]
    already = {
        r[0] for r in c.execute("SELECT symbol FROM pending_orders WHERE signal_day=?", (day,))
    }
    buys = c.execute(
        "SELECT COUNT(*) FROM pending_orders WHERE signal_day=? AND side='BUY'", (day,)
    ).fetchone()[0]
    target = next_day(day)
    window_open = now < session(target)[0]
    configuration_gate = execution_configuration_gate()
    candidates = []
    gates = []
    for a in assets:
        sym = a["symbol"]
        p = held_by.get(sym)
        bar, bars, reason = series(c, sym, day, now, p["entry_day"] if p else None)
        ev = evaluate(bars, spy)
        score = ev["score"] if ev else None
        sell = bool(
            p
            and bar
            and (
                bar["c"] < p["stop"]
                or (ev and (bar["c"] < ev["features"]["sma50"] * 0.96 or (spy and score < 0.8)))
            )
        )
        buy = bool(not p and ev and spy and score >= SCORE_MIN)
        data_ready = bool(bar and (bars or sell))
        candidate = {
            "symbol": sym,
            "score": score,
            "data_ready": data_ready,
            "signal_qualified": sell or buy,
            "action": "WATCH",
            "observed_at": bar["observed_at"] if bar else None,
        }
        candidates.append((candidate, a, ev, bar, reason, sell, buy))
    # Compare eligible opportunities with an explicit, stable tie break. Exits
    # are admitted before entries and do not consume BUY capacity.
    candidates.sort(key=lambda x: (not x[5], -(x[0]["score"] or 0), x[0]["symbol"]))
    for item, asset, ev, bar, reason, sell, buy in candidates:
        sym = item["symbol"]
        budget, cap = allocation(view, asset["sector"], reserved)
        if configuration_gate:
            gate = configuration_gate
        elif not window_open:
            gate = "waiting_for_next_session"
        elif sym in pending_symbols:
            gate = "pending_fill_awaiting_observation"
        elif sym in already:
            gate = "symbol_period_already_ordered"
        elif sell:
            gate = "stop_exit" if bar["c"] < held_by[sym]["stop"] else "strategy_exit"
            item["action"] = "SELL"
        elif reason:
            gate = reason
        elif sym in held_by:
            gate = "position_held_no_exit"
        elif entry_gate:
            gate = entry_gate
        elif not buy:
            gate = "score_below_threshold"
        elif ev["features"]["volatility_annual"] >= MAX_VOLATILITY:
            gate = "volatility_cap"
        elif bar["c"] * bar["v"] < 1_000_000:
            gate = "low_iex_dollar_volume"
        elif buys >= 2:
            gate = "daily_entry_cap"
        elif budget < bar["c"] * (1 + FRICTION_BPS / 10000):
            gate = cap
        else:
            gate = "buy_eligible"
            item["action"] = "BUY"
        item["reason"] = gate
        if ev or sell:
            record_decision(
                c, item, ev, bar, gate, day, now, target, budget, exposure, equity, run_id
            )
        if item["action"] == "BUY":
            reserved.append(asset["sector"])
            buys += 1
        gates.append(item)
    return gates


def record_decision(c, item, ev, bar, gate, day, now, target, budget, exposure, equity, run_id):
    sym, action = item["symbol"], item["action"]
    order_id = order_key(sym, day, action)
    decision_id = "dec:" + order_key(sym, day, action + POLICY_VERSION)
    reasons = [gate, *((ev or {}).get("reasons", []))]
    payload = {
        **((ev or {}).get("features", {})),
        "signal_policy": SIGNAL_VERSION,
        "observed_at": bar["observed_at"],
        "cost_bps_per_side": FRICTION_BPS,
        "risk_budget_usd": budget,
        "portfolio_exposure_usd": exposure,
        "portfolio_equity_usd": equity,
        "invalidation": "eight-percent initial stop or baseline score/trend deterioration",
        "holding_period": "condition-based",
    }
    score, regime, signals = (
        (ev["score"], ev["regime"], ev["signals"]) if ev else (0, "UNKNOWN", {})
    )
    c.execute(
        """INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET score=excluded.score,regime=excluded.regime,
            signals_json=excluded.signals_json,reasons_json=excluded.reasons_json,
            created_at=excluded.created_at WHERE decisions.action='WATCH'""",
        (
            decision_id,
            sym,
            day,
            score,
            regime,
            json.dumps(signals),
            json.dumps(reasons),
            action,
            POLICY_VERSION,
            now.isoformat(),
        ),
    )
    snapshot = hashlib.sha256(
        json.dumps(
            [sym, day, POLICY_VERSION, action, signals, reasons, payload], sort_keys=True
        ).encode()
    ).hexdigest()
    c.execute(
        """INSERT INTO sw_signal_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO NOTHING""",
        (
            snapshot,
            run_id,
            sym,
            day,
            POLICY_VERSION,
            score,
            regime,
            action,
            bar["source"],
            bar["adjustment"],
            json.dumps(payload),
            json.dumps(signals),
            json.dumps(reasons),
            now.isoformat(),
        ),
    )
    if action != "WATCH":
        c.execute(
            "INSERT INTO pending_orders VALUES(?,?,?,?,?,?,'PENDING',NULL)",
            (order_id, sym, action, day, decision_id, now.isoformat()),
        )
        c.execute(
            "INSERT INTO sw_order_evidence VALUES(?,?,?,?,?)",
            (order_id, POLICY_VERSION, target, bar["source"], bar["observed_at"]),
        )
        item["order_id"] = order_id


def decide_and_queue(observer=None, now=None):
    now = now or datetime.now(timezone.utc)
    day = completed_day(now)
    run_id = observer.id if observer else now.isoformat()
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        view = portfolio_view(c, day, now)
        if not ledger_reconciles(c, view[0], view[1]):
            result = {
                "status": "ERROR",
                "reason": "ledger_reconciliation_failed",
                "ledger": "RECONCILIATION_FAILED",
                "market_day": day,
                "at": now.isoformat(),
            }
            c.execute(
                "INSERT INTO sw_trade_cycles VALUES(?,?,?,?) ON CONFLICT(id) DO NOTHING",
                (run_id, now.isoformat(), day, json.dumps(result)),
            )
            c.commit()
            return result
        _, spy, spy_reason = series(c, "SPY", day, now)
        settled = settle(c, day, now, spy)
        view = portfolio_view(c, day, now)
        account, held, equity, exposure, dd = view
        if not ledger_reconciles(c, account, held):
            raise RuntimeError("ledger_reconciliation_failed")
        if dd >= MAX_DRAWDOWN and not any(p["mark_warning"] for p in held):
            c.execute("UPDATE portfolio SET paused=1 WHERE id=1")
        assets = c.execute("""SELECT * FROM assets WHERE sector!='Benchmark'
            AND (enabled=1 OR symbol IN (SELECT symbol FROM positions)) ORDER BY symbol""").fetchall()
        unchecked = c.execute(
            """SELECT COUNT(*) FROM assets a
            LEFT JOIN sw_price_checks p ON a.symbol=p.symbol AND p.day=?
            WHERE a.enabled=1 AND a.sector!='Benchmark' AND p.symbol IS NULL""",
            (day,),
        ).fetchone()[0]
        entry_gate = buy_gate(c, view, spy, day) or (
            "universe_refresh_pending" if unchecked else None
        )
        gates = queue(c, assets, view, day, now, spy, entry_gate, run_id)
        if (spy or "filled" in settled.values()) and not any(p["mark_warning"] for p in held):
            high = max(equity, account["high_water"])
            c.execute("UPDATE portfolio SET high_water=? WHERE id=1", (high,))
            c.execute(
                """INSERT INTO equity_curve VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(day) DO UPDATE SET equity=excluded.equity,cash=excluded.cash,
                exposure=excluded.exposure,drawdown=excluded.drawdown,spy_close=excluded.spy_close,
                created_at=excluded.created_at""",
                (
                    day,
                    equity,
                    account["cash"],
                    exposure,
                    (high - equity) / max(1, high),
                    spy[-1]["c"] if spy else None,
                    now.isoformat(),
                ),
            )
        funnel = {
            "scanned": len(gates),
            "data_ready": sum(x["data_ready"] for x in gates),
            "signal_qualified": sum(x["signal_qualified"] for x in gates),
            "risk_eligible": sum(x["action"] != "WATCH" for x in gates),
            "order_created": sum("order_id" in x for x in gates),
            "order_filled": sum(reason == "filled" for reason in settled.values()),
        }
        pending = c.execute("SELECT COUNT(*) FROM pending_orders WHERE state='PENDING'").fetchone()[
            0
        ]
        if funnel["order_created"]:
            state = "TRADE_READY"
        elif pending or now >= session(next_day(day))[0]:
            state = "WAITING_FOR_NEXT_SESSION"
        elif execution_configuration_gate() or spy_reason or unchecked or not funnel["data_ready"]:
            state = "WAITING_FOR_DATA"
        elif entry_gate:
            state = "RISK_PAUSED"
        else:
            state = "NO_ELIGIBLE_SIGNAL"
        result = {
            "status": state,
            "processed": len(gates),
            "orders_queued": funnel["order_created"],
            "benchmark_day": day if spy else None,
            "benchmark_gate": spy_reason,
            "market_day": day,
            "next_core_open": session(next_day(day))[0].isoformat(),
            "mode": EXECUTION_MODE,
            "funnel": funnel,
            "why_no_trade": gates,
            "order_checks": settled,
            "pending_count": pending,
            "entry_gate": execution_configuration_gate() or entry_gate,
            "ledger": "RECONCILED",
            "at": now.isoformat(),
        }
        c.execute(
            "INSERT INTO sw_trade_cycles VALUES(?,?,?,?) ON CONFLICT(id) DO NOTHING",
            (run_id, now.isoformat(), day, json.dumps(result, sort_keys=True)),
        )
        c.execute(
            "DELETE FROM sw_trade_cycles WHERE recorded_at<?",
            ((now - timedelta(days=45)).isoformat(),),
        )
        c.commit()
    return result
