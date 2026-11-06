"""NYSE phase clock and fail-closed deployment gate for intraday orders."""

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from .sessions import NY, calendar, session

STRATEGY = "stockswatch-intraday/1"
ORDER_PREFIX = "swx1-"
TRADABLE_PHASES = frozenset({"PREMARKET", "CORE", "AFTERHOURS"})
GATES = frozenset({"native", "linux_amd64", "frontend", "offline_broker", "read_only_rehearsal"})


@dataclass(frozen=True)
class Phase:
    name: str
    day: str
    start: datetime | None = None
    end: datetime | None = None

    def contains(self, stamp):
        return self.start is not None and self.start <= stamp < self.end


def phase_at(now):
    if now.tzinfo is None:
        raise ValueError("intraday_timezone_required")
    local = now.astimezone(NY)
    day = local.date()

    def boundary(d, hour):
        return datetime.combine(d, time(hour), NY).astimezone(UTC)

    try:
        bounds = session(day.isoformat())
        pre = boundary(day, 4)
        night = boundary(day, 20)
        if now < pre or now >= night:
            following = day if now < pre else day + timedelta(days=1)
            if session(following.isoformat()):
                return Phase(
                    "OVERNIGHT",
                    following.isoformat(),
                    boundary(following - timedelta(days=1), 20),
                    boundary(following, 4),
                )
        if bounds:
            opened, closed = bounds
            late_end = boundary(day, 17 if closed.astimezone(NY).hour < 16 else 20)
            for name, start, end in (
                ("PREMARKET", pre, opened),
                ("CORE", opened, closed),
                ("AFTERHOURS", closed, late_end),
            ):
                if start <= now < end:
                    return Phase(name, day.isoformat(), start, end)
            if late_end <= now < night:
                return Phase("MAINTENANCE", day.isoformat(), late_end, night)
        return Phase("CLOSED", day.isoformat())
    except ValueError:
        return Phase("UNAVAILABLE", day.isoformat())


def previous_regular_day(phase):
    return calendar().previous_session(phase.day).date().isoformat()


def order_gate():
    if os.getenv("STOCKSWATCH_INTRADAY_ALLOW_ORDERS") != "1":
        return "intraday_orders_disabled"
    if os.getenv("STOCKSWATCH_INTRADAY_FEED", "iex") != "sip":
        return "intraday_realtime_sip_required"
    commit = os.getenv("STOCKSWATCH_BUILD_COMMIT", "")
    expected = os.getenv("STOCKSWATCH_INTRADAY_PREFLIGHT_SHA256", "")
    if not re.fullmatch(r"[a-f0-9]{40}", commit) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        return "intraday_pinned_preflight_required"
    try:
        with Path(os.environ["STOCKSWATCH_INTRADAY_PREFLIGHT"]).open("rb") as stream:
            data = stream.read(16385)
        proof = json.loads(data)
        if (
            len(data) <= 16384
            and hashlib.sha256(data).hexdigest() == expected
            and proof["commit"] == commit
            and proof["strategy"] == STRATEGY
            and proof["paper_only"] is True
            and set(proof["checks"]) == GATES
            and all(value == "PASS" for value in proof["checks"].values())
        ):
            return None
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return "intraday_pinned_preflight_required"


SHORT_STRATEGY = "stockswatch-short/1"
SHORT_GATES = GATES | {"account_short", "etb", "history", "sip"}


def short_gate(*, cover=False):
    if not cover and os.getenv("STOCKSWATCH_SHORT_ALLOW_ORDERS") != "1":
        return "short_orders_disabled"
    common = order_gate()
    if common:
        return common
    try:
        expected = os.environ["STOCKSWATCH_SHORT_PREFLIGHT_SHA256"]
        with Path(os.environ["STOCKSWATCH_SHORT_PREFLIGHT"]).open("rb") as stream:
            data = stream.read(16385)
        proof = json.loads(data)
        if (
            len(data) <= 16384
            and hashlib.sha256(data).hexdigest() == expected
            and proof["commit"] == os.environ["STOCKSWATCH_BUILD_COMMIT"]
            and proof["strategy"] == SHORT_STRATEGY
            and proof["paper_only"] is True
            and set(proof["checks"]) == SHORT_GATES
            and all(v == "PASS" for v in proof["checks"].values())
        ):
            return None
    except (OSError, KeyError, ValueError, TypeError):
        pass
    return "short_pinned_preflight_required"
