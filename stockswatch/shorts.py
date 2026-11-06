"""Independent short signals and paper admission checks."""

import hashlib
import itertools
import json
import os
from datetime import timedelta
from decimal import ROUND_UP
from decimal import Decimal as D
from statistics import correlation

from . import alpaca_paper as paper
from . import backfill
from .direction import SHORT_PREFIX, intent_action, position
from .intraday_market import MINUTE, ObservationError, parse_bars, positive
from .sessions import calendar, instant, session
from .storage import one, rows
from .universe import BENCHMARKS, REGISTRY

STOP = D(".015")
TARGET = D(".025")
MAX_SYMBOL = D(".03")
MAX_TOTAL = D(".10")
MAX_RISK = D(".0025")
SQUEEZE_STRESS = D(".06")
FLATTEN_BEFORE = timedelta(minutes=30)


def rank(observations):
    peers = [r for r in observations if r["symbol"] in BENCHMARKS and r["valid"]]
    benchmark = sum(D(r["momentum"]) for r in peers) / 2 if len(peers) == 2 else None
    sectors = {}
    for r in observations:
        if r["valid"] and r["symbol"] in REGISTRY:
            sectors.setdefault(REGISTRY[r["symbol"]]["sector"], []).append(D(r["momentum"]))
    threshold = D(os.getenv("STOCKSWATCH_SHORT_MIN_EDGE_BPS", "35"))
    if not threshold.is_finite() or not 30 <= threshold <= 150:
        raise ValueError("short_edge_threshold_outside_reviewed_range")
    result = []
    for r in observations:
        if not r["valid"] or r["symbol"] in BENCHMARKS:
            continue
        gap, move, cost, volume = (D(r[k]) for k in ("gap", "momentum", "cost_bps", "turnover_3m"))
        relative = move - benchmark if benchmark is not None else None
        sector = sectors[REGISTRY[r["symbol"]]["sector"]]
        sector_relative = move - sum(sector) / len(sector)
        recent = r["bar_window"]
        last = [D(b["close"]) for b in recent]
        support = min(D(b.get("low", b["close"])) for b in recent[:-2])
        breakdown = last[-1] < last[-2] < support
        failed_rebound = last[-3] > last[-4] and last[-1] < min(last[-4], last[-2])
        volatility = (max(last) - min(last)) / last[0]
        edge = -(gap + move) * 10000 - cost - D(20)
        strength = -(relative or D(0)) * 10000 + edge
        corr = None
        if len(peers) == 2 and all(len(p["bar_window"]) == len(last) for p in peers):
            market = [
                sum(
                    D(p["bar_window"][i]["close"]) / D(p["bar_window"][i - 1]["close"]) - 1
                    for p in peers
                )
                / 2
                for i in range(1, len(last))
            ]
            changes = [b / a - 1 for a, b in itertools.pairwise(last)]
            if len(set(changes)) > 1 and len(set(market)) > 1:
                corr = correlation(changes, market)
        r.update(
            short_score=str(strength),
            short_relative=str(relative) if relative is not None else None,
            short_sector_relative=str(sector_relative),
            short_benchmark_correlation=corr,
            short_volatility=str(volatility),
            short_reward_to_stress=str(TARGET / SQUEEZE_STRESS),
            historical_short_edge="UNVALIDATED",
        )
        if not r.get("enabled", True) or r["feed"] != "sip" or r["session"] != "CORE":
            reason = "short_requires_core_sip_and_enabled_equity"
        elif benchmark is None or benchmark > D(".001"):
            reason = "short_benchmark_regime_unsuitable"
        elif gap < D("-.065") or volatility > D(".02"):
            reason = "short_gap_or_squeeze_risk"
        elif not (
            D("-.065") <= gap <= D("-.0025")
            and move <= D("-.0015")
            and relative is not None
            and relative <= D("-.001")
            and sector_relative <= 0
            and (breakdown or failed_rebound)
            and volume >= 250_000
            and edge >= threshold
        ):
            reason = "short_breakdown_relative_weakness_or_cost_gate"
        else:
            reason = "short_candidate"
            result.append(r)
        r["short_reason"] = reason
    return sorted(result, key=lambda r: (-D(r["short_score"]), r["symbol"]))


def borrow(asset):
    for field in ("borrow_fee_rate", "daily_borrow_fee", "borrow_rate"):
        if asset.get(field) is not None:
            cost = paper.money(asset[field], D("-1"))
            if cost != 0:
                return "CHARGEABLE_OR_UNVERIFIED"
    if asset.get("halted") or asset.get("trading_halted") or asset.get("short_sale_restricted"):
        return "RESTRICTED"
    if asset.get("borrow_recalled") or asset.get("locate_required"):
        return "UNAVAILABLE"
    if asset.get("shortable") is not True or asset.get("marginable") is not True:
        return "UNAVAILABLE"
    if "borrow_status" in asset:
        return {
            "easy_to_borrow": "ETB",
            "hard_to_borrow": "UNAVAILABLE",
            "not_available": "UNAVAILABLE",
        }.get(asset["borrow_status"], "UNKNOWN")
    return "ETB" if asset.get("easy_to_borrow") is True else "UNKNOWN"


def owned(raw, fills, account_id):
    """Prove the exact signed inventory from the last short open and its covers."""
    try:
        pos = position(raw)
        if pos.direction != "SHORT" or pos.available != pos.quantity or fills is None:
            return None
        intents = rows(
            """SELECT * FROM sw_alpaca_intents WHERE account_id=? AND symbol=? AND client_id LIKE ?
            AND broker_order_id IS NOT NULL ORDER BY created_at,client_id""",
            (account_id, raw["symbol"], SHORT_PREFIX + "%"),
        )
        # Last opening order with an actual confirmed fill, not a zero-fill rejection.
        by_id = {f["order_id"] for f in fills if f.get("symbol") == raw["symbol"]}
        entry = next(
            (i for i in reversed(intents) if i["side"] == "SELL" and i["broker_order_id"] in by_id),
            None,
        )
        if not entry:
            return None
        start = instant(entry["created_at"])
        stamped = [(instant(f["transaction_time"]), f) for f in fills]
        if len(fills) >= paper.FILL_PAGE_SIZE and min(t for t, _ in stamped) >= start:
            return None
        allowed = {i["broker_order_id"]: i for i in intents if instant(i["created_at"]) >= start}
        used = set()
        remaining = D(0)
        for _, fill in sorted(stamped, key=lambda r: (r[0], r[1]["id"])):
            if fill["symbol"] != raw["symbol"] or instant(fill["transaction_time"]) < start:
                continue
            i = allowed.get(fill["order_id"])
            if not i or fill["id"] in used:
                return None
            action = intent_action(i["client_id"], i["side"])
            if (
                json.loads(i["detail_json"]).get("action") != action.value
                or fill["side"] != action.broker_side
                or (action.opening and i["client_id"] != entry["client_id"])
            ):
                return None
            used.add(fill["id"])
            qty = positive(fill["qty"])
            remaining += qty if action.opening else -qty
            if remaining < 0:
                return None
        return entry if remaining == pos.quantity else None
    except (KeyError, ValueError, TypeError, ObservationError):
        return None


def cover_trigger(row, raw, entry, phase, now, borrow_status, daily_pause, exposure=None):
    pos = position(raw)
    ask = positive(row["quote"]["ap"])
    if borrow_status != "ETB":
        return "short_borrow_recall_or_unverified"
    if daily_pause or (exposure is not None and exposure > MAX_TOTAL):
        return "short_account_risk_exit"
    if now >= phase.end - FLATTEN_BEFORE or now - instant(entry["created_at"]) >= timedelta(
        minutes=75
    ):
        return "short_time_or_session_exit"
    if ask >= pos.entry * (1 + STOP):
        return "short_adverse_price_exit"
    if ask <= pos.entry * (1 - TARGET):
        return "short_profit_exit"
    if row.get("market_risk") == "MIXED_OR_SUPPORTIVE" and D(row.get("momentum", "0")) > D(".0015"):
        return "short_regime_reversal_exit"
    return None


def cid(account_id, phase, symbol, action, now):
    key = phase.day if action.opening else now.replace(second=0, microsecond=0).isoformat()
    return (
        SHORT_PREFIX
        + hashlib.sha256(f"{account_id}|{symbol}|{action}|{key}".encode()).hexdigest()[:40]
    )


def restriction_check(data, symbol, phase, at):
    """Conservative two-session SIP proxy and above-bid limit; broker remains authoritative."""
    prior = calendar().previous_session(phase.day).date().isoformat()
    before = calendar().previous_session(prior).date().isoformat()
    end = at.replace(second=0, microsecond=0)
    for day, reference_day, until in ((prior, before, session(prior)[1]), (phase.day, prior, end)):
        start = session(day)[0]
        ref = data.regular_closes([symbol], "sip", reference_day).get(symbol)
        if (
            not ref
            or ref["at"] != (session(reference_day)[1] - MINUTE).isoformat()
            or until <= start
        ):
            raise paper.PaperError("short_price_test_evidence_unavailable")
        bars = parse_bars(
            data.bars([symbol], "sip", start, until, max_window=timedelta(hours=7))[symbol],
            start,
            until,
        )
        if len(bars) != int((until - start) / MINUTE):
            raise paper.PaperError("short_price_test_evidence_gap")
        if min(b["low"] for b in bars) <= positive(ref["price"]) * D(".92"):
            raise paper.PaperError("short_price_test_or_deep_decline")
    return "TWO_SESSION_SIP_LOW_PROXY_ABOVE_BID_REQUIRED"


def _short_budget(snapshot, config, asset, sectors, symbol, phase, mark):
    account = snapshot["account"]
    equity = paper.money(account.get("equity"))
    if (
        equity < 2000
        or account.get("shorting_enabled") is not True
        or paper.money(account.get("multiplier"), D(0)) < 2
        or not isinstance(config, dict)
        or config.get("no_shorting") is not False
        or config.get("suspend_trade") is not False
        or paper.money(config.get("max_margin_multiplier"), D(0)) < 2
    ):
        raise paper.PaperError("short_account_not_eligible")
    margin = max(
        paper.money(account.get("initial_margin")), paper.money(account.get("maintenance_margin"))
    )
    if margin < 0:
        raise paper.PaperError("short_margin_unverified")
    requirement = (
        paper.money(
            asset.get("margin_requirement_short", asset.get("maintenance_margin_requirement"))
        )
        / 100
    )
    if requirement <= 0:
        raise paper.PaperError("short_asset_margin_unverified")
    requirement = max(requirement, D(".50"))
    positions = {p["symbol"]: p for p in snapshot["positions"]}
    try:
        shorts = [position(p) for p in positions.values() if p["side"] == "short"]
    except (KeyError, ValueError):
        raise paper.PaperError("short_position_margin_unverified") from None
    active_ids = {
        i["broker_order_id"]
        for i in rows(
            """SELECT broker_order_id FROM sw_alpaca_intents
            WHERE account_id=? AND state='ACKNOWLEDGED'""",
            (account["id"],),
        )
    }
    active = [{**o, "owned_intent": o["id"] in active_ids} for o in snapshot["open_orders"]]
    reserved = sum(
        paper.money(o["limit_price"])
        * max(D(0), paper.money(o["qty"]) - paper.money(o["filled_qty"]))
        for o in active
        if o.get("client_order_id", "").startswith(SHORT_PREFIX) and o["side"] == "sell"
    )
    count = one(
        """SELECT COUNT(*) AS n FROM sw_alpaca_intents
        WHERE account_id=? AND signal_day=? AND client_id LIKE ? AND side='SELL'""",
        (account["id"], phase.day, SHORT_PREFIX + "%"),
    )["n"]
    if count >= 2:
        raise paper.PaperError("short_daily_entry_cap")
    collateral = max(D(0), equity - margin - reserved)
    buying = min(
        paper.money(account.get("regt_buying_power")), paper.money(account.get("buying_power"))
    )
    headroom = paper._entry_budget(snapshot, sectors, sectors[symbol], active, positions)
    gross = sum(p.gross for p in shorts)
    budget = min(
        headroom,
        equity * MAX_SYMBOL,
        equity * MAX_TOTAL - gross - reserved,
        equity * MAX_RISK / SQUEEZE_STRESS,
        collateral / requirement,
        buying,
    )
    return budget, requirement, mark * D("1.03")


def payload(client, snapshot, row, phase, action, now, asset, sectors, reason):
    symbol = row["symbol"]
    account_id = snapshot["account"]["id"]
    if any(o["symbol"] == symbol for o in snapshot["open_orders"]):
        raise paper.PaperError("short_symbol_open_order_conflict")
    raw = next((p for p in snapshot["positions"] if p["symbol"] == symbol), None)
    bid, ask = (positive(row["quote"][k]) for k in ("bp", "ap"))
    if action.opening:
        if raw or one(
            """SELECT 1 FROM sw_alpaca_intents WHERE account_id=? AND symbol=?
            AND (signal_day=? OR substr(created_at,1,10)=?)""",
            (account_id, symbol, phase.day, phase.day),
        ):
            raise paper.PaperError("short_inventory_or_same_day_conflict")
        if borrow(asset) != "ETB":
            raise paper.PaperError("short_borrow_not_etb")
        if not backfill.asset_evidence(symbol, asset)[
            "verified"
        ] or not backfill.short_history_ready(symbol, now, asset["id"]):
            raise paper.PaperError("short_history_or_listing_unverified")
        if now >= phase.end - FLATTEN_BEFORE:
            raise paper.PaperError("short_flatten_window")
        config = client.get("/v2/account/configurations")
        budget, requirement, bp_mark = _short_budget(
            snapshot, config, asset, sectors, symbol, phase, ask
        )
        # Strictly above the displayed NBB. Never request short-exempt handling.
        limit = (bid + D(".01")).quantize(D(".01"), rounding=ROUND_UP)
        qty = min(
            int(max(budget, D(0)) / max(limit, bp_mark)), int(positive(row["quote"]["bs"]) / 4)
        )
        risk = {
            "borrow": "ETB",
            "verified_at": now.isoformat(),
            "margin_requirement": str(requirement),
            "estimated_initial_collateral": str(limit * qty * requirement),
            "financing_cost": "UNVERIFIED",
            "modeled_adverse_loss_usd": str(limit * qty * SQUEEZE_STRESS),
            "price_test": row.get("short_price_test"),
        }
    else:
        entry = owned(raw, snapshot["fills"], account_id) if raw else None
        if not entry or raw.get("asset_id") != asset["id"]:
            raise paper.PaperError("short_cover_ownership_unverified")
        limit = (ask * D("1.001")).quantize(D(".01"), rounding=ROUND_UP)
        qty = min(int(position(raw).available), int(positive(row["quote"]["as"]) / 4))
        risk = {
            "borrow": borrow(asset),
            "verified_at": now.isoformat(),
            "cover_reason": reason,
            "financing_cost": "UNVERIFIED",
        }
    if qty < 1 or limit < 1:
        raise paper.PaperError("short_margin_or_displayed_depth_insufficient")
    return {
        "symbol": symbol,
        "side": action.broker_side,
        "qty": str(qty),
        "limit_price": str(limit),
        "type": "limit",
        "time_in_force": "day",
        "extended_hours": False,
        "client_order_id": cid(account_id, phase, symbol, action, now),
    }, risk
