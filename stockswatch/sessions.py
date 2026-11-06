"""NYSE core sessions and a conservative publication boundary for daily data."""

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars

NY = ZoneInfo("America/New_York")


@lru_cache
def calendar():
    return exchange_calendars.get_calendar("XNYS", start="1990-01-01", end="2050-12-31")


def instant(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("observation_timestamp_missing_timezone")
    return parsed.astimezone(timezone.utc)


@lru_cache(maxsize=1024)
def session(day):
    cal = calendar()
    if not cal.is_session(day):
        return None
    return cal.session_open(day).to_pydatetime(), cal.session_close(day).to_pydatetime()


@lru_cache(maxsize=1024)
def published_after(day):
    # Alpaca groups daily bars by New York civil day. Wait until that entire
    # interval has ended plus 15 minutes for late prints/provider updates.
    return datetime.combine(
        date.fromisoformat(day) + timedelta(days=1), time(0, 15), NY
    ).astimezone(timezone.utc)


def completed_day(now):
    day = now.astimezone(NY).date()
    if now < published_after((day - timedelta(days=1)).isoformat()):
        day -= timedelta(days=1)
    return (
        calendar()
        .date_to_session((day - timedelta(days=1)).isoformat(), direction="previous")
        .date()
        .isoformat()
    )


def market_session_state(now):
    day = now.astimezone(NY).date().isoformat()
    bounds = session(day)
    if not bounds:
        return "MARKET_CLOSED_NON_SESSION"
    opened, closed = bounds
    if now < opened:
        return "BEFORE_CORE_OPEN"
    return "CORE_OPEN" if now < closed else "AFTER_CORE_CLOSE"


@lru_cache(maxsize=1024)
def next_day(day):
    return calendar().next_session(day).date().isoformat()


@lru_cache(maxsize=256)
def history_days(day):
    return tuple(label.date().isoformat() for label in calendar().sessions_window(day, -201))
