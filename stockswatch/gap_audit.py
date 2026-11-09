"""Bounded, read-only Alpaca gap verification for RAW EOD technical history.

A raw overnight move >15% is ambiguous: it may be a real price shock or a
corporate action. Only a matching, independently requested split/dividend/spin-
off adjusted feed can certify that a <=35% event did not distort share units.
Both series use IEX, the source of the original certified bars. This module
never submits orders or changes original historical candles.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date, timedelta
from .storage import connect, utc

log = logging.getLogger(__name__)
GAP_THRESHOLD = 0.15
MAX_VERIFIABLE_GAP = 0.35
RAW_TOLERANCE = 0.01
ADJUSTMENT_TOLERANCE = 0.01
COOLING_SESSIONS = 5
SOURCE = "alpaca_iex_raw_vs_all_adjusted"


def overnight_gap(previous, current):
    return float(current["o"]) / float(previous["c"]) - 1.0


def classify(raw_previous_close, raw_open, feed_previous_close, feed_open,
             adjusted_previous_close, adjusted_open):
    """Compare the same two IEX bars with raw and ALL adjustments.

    Adjusted historical prices elsewhere may differ because of later actions;
    comparing the *ratio across this specific boundary* avoids that pitfall.
    """
    vals = [raw_previous_close, raw_open, feed_previous_close, feed_open,
            adjusted_previous_close, adjusted_open]
    try:
        vals = [float(v) for v in vals]
    except (TypeError, ValueError, OverflowError):
        return "INVALID_REFERENCE"
    if any(not math.isfinite(v) or v <= 0 for v in vals):
        return "INVALID_REFERENCE"
    before, opened, raw_before, raw_opened, adj_before, adj_opened = vals
    if abs(raw_before / before - 1) > RAW_TOLERANCE or abs(raw_opened / opened - 1) > RAW_TOLERANCE:
        return "RAW_REFERENCE_MISMATCH"
    unadjusted_return = opened / before
    adjusted_return = adj_opened / adj_before
    if abs(unadjusted_return / adjusted_return - 1) > ADJUSTMENT_TOLERANCE:
        return "CORPORATE_ACTION_ADJUSTMENT_DETECTED"
    if abs(unadjusted_return - 1) > MAX_VERIFIABLE_GAP:
        return "EXTREME_GAP_REQUIRES_REVIEW"
    if abs(unadjusted_return - 1) <= GAP_THRESHOLD:
        return "NO_LARGE_GAP"
    return "VERIFIED_UNADJUSTED_MARKET_GAP"


def _match(proof, prev, current):
    return (
        proof is not None
        and math.isclose(float(proof["raw_prev_close"]), float(prev["c"]), rel_tol=0, abs_tol=0.00001)
        and math.isclose(float(proof["raw_next_open"]), float(current["o"]), rel_tol=0, abs_tol=0.00001)
        and proof["previous_day"] == prev["day"]
    )


def _known_actions(c, symbol, day):
    table = c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sw_history_actions'"
    ).fetchone()
    if not table:
        return False
    return c.execute(
        "SELECT 1 FROM sw_history_actions WHERE symbol=? AND day=? LIMIT 1",
        (symbol, day),
    ).fetchone() is not None


def reason_for_gap(c, symbol, prev, current, sessions_since_gap):
    """Return None only after independent provider verification, otherwise block."""
    change = overnight_gap(prev, current)
    if abs(change) <= GAP_THRESHOLD:
        return None
    if _known_actions(c, symbol, current["day"]):
        return "historical_corporate_action_requires_adjustment"
    if abs(change) > MAX_VERIFIABLE_GAP:
        return "historical_extreme_gap_requires_review"
    if sessions_since_gap < COOLING_SESSIONS:
        return "historical_recent_large_gap_cooling_period"
    row = c.execute(
        """SELECT previous_day,raw_prev_close,raw_next_open,status
           FROM sw_historical_gap_proofs WHERE symbol=? AND gap_day=?""",
        (symbol, current["day"]),
    ).fetchone()
    if not _match(row, prev, current):
        return "historical_gap_verification_pending"
    if row["status"] != "VERIFIED_UNADJUSTED_MARKET_GAP":
        return "historical_gap_"+row["status"].lower()
    return None


def pending(c, symbol, bars):
    """Identify the first eligible unproven historical gap for a symbol."""
    for idx in range(1, len(bars)):
        prev, curr = bars[idx - 1], bars[idx]
        diff = overnight_gap(prev, curr)
        if not GAP_THRESHOLD < abs(diff) <= MAX_VERIFIABLE_GAP:
            continue
        if len(bars) - idx < COOLING_SESSIONS or _known_actions(c, symbol, curr["day"]):
            continue
        proof = c.execute(
            """SELECT previous_day,raw_prev_close,raw_next_open,status
               FROM sw_historical_gap_proofs WHERE symbol=? AND gap_day=?""",
            (symbol, curr["day"]),
        ).fetchone()
        if not _match(proof, prev, curr):
            return (symbol, dict(prev), dict(curr))
    return None


async def _fetch_pair(client, symbol, prev_day, day, adjustment):
    from .market import alpaca_headers, alpaca_status
    from .sessions import NY, instant
    end = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    resp = await client.get(
        "https://data.alpaca.markets/v2/stocks/" + symbol + "/bars",
        params={
            "timeframe": "1Day", "start": prev_day, "end": end,
            "feed": "iex", "adjustment": adjustment, "limit": 20,
        },
        headers=alpaca_headers(),
    )
    alpaca_status(resp)
    if len(resp.content) > 80000:
        raise ValueError("gap_reference_payload_too_large")
    body = resp.json()
    if not isinstance(body, dict) or body.get("symbol") != symbol or body.get("next_page_token"):
        raise ValueError("gap_reference_unverifiable")
    result = {}
    for bar in body.get("bars", []):
        stamp = instant(bar["t"]).astimezone(NY).date().isoformat()
        if stamp in (prev_day, day):
            if stamp in result:
                raise ValueError("gap_reference_duplicate_session")
            # Both values are required. Never infer a missing price.
            result[stamp] = {"o": float(bar["o"]), "c": float(bar["c"])}
    if not all(s in result for s in (prev_day, day)):
        raise ValueError("gap_reference_missing_session")
    return result


async def refresh_proofs(client, now, limit=6):
    """GET-only, rate-bounded refresh; persisted results are ancillary evidence."""
    from .ledger import TRUSTED, history
    from .sessions import completed_day
    day = completed_day(now)
    targets = []
    with connect() as c:
        c.execute("PRAGMA query_only=ON")
        for a in c.execute("SELECT symbol FROM assets WHERE enabled=1 AND sector!='Benchmark'"):
            symbol = a["symbol"]
            bars = history(c, symbol, day)
            if len(bars) != 201 or any((b["source"], b["adjustment"]) != TRUSTED for b in bars):
                continue
            target = pending(c, symbol, bars)
            if target is not None:
                targets.append(target)
                if len(targets) == limit:
                    break
    verified = rejected = 0
    for symbol, prev, curr in targets:
        try:
            raw = await _fetch_pair(client, symbol, prev["day"], curr["day"], "raw")
            adjusted = await _fetch_pair(client, symbol, prev["day"], curr["day"], "all")
            status = classify(
                prev["c"], curr["o"],
                raw[prev["day"]]["c"], raw[curr["day"]]["o"],
                adjusted[prev["day"]]["c"], adjusted[curr["day"]]["o"],
            )
        except Exception as exc:
            # Authentication, transport and malformed observations remain blocked.
            log.warning("StocksWatch gap check deferred for %s: %s", symbol, type(exc).__name__)
            break
        with connect() as c:
            c.execute(
                """INSERT INTO sw_historical_gap_proofs
                   (symbol,gap_day,previous_day,raw_prev_close,raw_next_open,
                    status,verified_at,source)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(symbol,gap_day) DO UPDATE SET
                    previous_day=excluded.previous_day,
                    raw_prev_close=excluded.raw_prev_close,
                    raw_next_open=excluded.raw_next_open,
                    status=excluded.status,
                    verified_at=excluded.verified_at,
                    source=excluded.source""",
                (symbol, curr["day"], prev["day"], prev["c"], curr["o"], status, utc(), SOURCE),
            )
        verified += int(status == "VERIFIED_UNADJUSTED_MARKET_GAP")
        rejected += int(status != "VERIFIED_UNADJUSTED_MARKET_GAP")
    return {"checked": verified + rejected, "verified_genuine_gaps": verified, "rejected_or_unverified": rejected}


def gap_snapshot(c, symbol, day):
    return [
        dict(r) for r in c.execute(
            """SELECT gap_day,previous_day,status,verified_at,source
               FROM sw_historical_gap_proofs WHERE symbol=?
               ORDER BY gap_day DESC LIMIT 6""",
            (symbol,),
        )
    ]
