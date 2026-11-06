"""Resumable, feed-separated historical research archive. This module sends only GETs."""

from __future__ import annotations

import argparse
import fcntl
import json
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from datetime import time as wall_time
from pathlib import Path

from . import storage
from .intraday_market import IntradayData, ObservationError, positive
from .intraday_policy import phase_at
from .sessions import NY, calendar, completed_day, history_days, instant, published_after, session
from .universe import NEW, REGISTRY

SCHEMA = """
CREATE TABLE IF NOT EXISTS sw_asset_verification (
    symbol TEXT PRIMARY KEY, at TEXT NOT NULL, evidence TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sw_history_jobs (
    symbol TEXT NOT NULL, timeframe TEXT NOT NULL, feed TEXT NOT NULL, adjustment TEXT NOT NULL,
    first_at TEXT NOT NULL, end_at TEXT NOT NULL, token TEXT, last_bar TEXT, state TEXT NOT NULL,
    error TEXT, updated_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol,timeframe,feed,adjustment,first_at,end_at)
);
CREATE TABLE IF NOT EXISTS sw_historical_bars (
    symbol TEXT NOT NULL, timeframe TEXT NOT NULL, feed TEXT NOT NULL, adjustment TEXT NOT NULL,
    at TEXT NOT NULL, trade_date TEXT NOT NULL, phase TEXT NOT NULL, observed_at TEXT NOT NULL,
    o TEXT NOT NULL,h TEXT NOT NULL,l TEXT NOT NULL,c TEXT NOT NULL,v TEXT NOT NULL,
    PRIMARY KEY (symbol,timeframe,feed,adjustment,at)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS sw_historical_retention ON sw_historical_bars(timeframe,trade_date);
CREATE TABLE IF NOT EXISTS sw_history_actions (
    symbol TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, observed_at TEXT NOT NULL,
    PRIMARY KEY(symbol,day,kind)
);
"""
KEY = ("symbol", "timeframe", "feed", "adjustment", "first_at", "end_at")
LISTED = {"AMEX", "ARCA", "BATS", "NASDAQ", "NYSE", "NYSEARCA", "NYSEAMERICAN", "IEX"}


def initialize():
    with storage.connect() as c:
        c.executescript(SCHEMA)


def asset_evidence(symbol, asset):
    verified = (
        isinstance(asset, dict)
        and asset.get("symbol") == symbol
        and bool(asset.get("id"))
        and asset.get("class") == "us_equity"
        and asset.get("exchange") in LISTED
        and asset.get("status") == "active"
        and asset.get("tradable") is True
    )
    asset = asset if isinstance(asset, dict) else {}
    return {
        "symbol": symbol,
        "verified": verified,
        "reason": "VERIFIED_PAPER_ASSET" if verified else "ASSET_MISSING_OR_INELIGIBLE",
        **{
            k: asset.get(k)
            for k in (
                "id",
                "name",
                "class",
                "exchange",
                "status",
                "tradable",
                "shortable",
                "marginable",
                "borrow_status",
                "easy_to_borrow",
                "halted",
                "trading_halted",
                "short_sale_restricted",
            )
        },
    }


def verify_assets(client, now):
    client.account()  # Require the explicitly configured paper account even for capability discovery.
    assets = client.get("/v2/assets", {"status": "active", "asset_class": "us_equity"})
    if not isinstance(assets, list) or any(not isinstance(a, dict) for a in assets):
        raise ObservationError("asset_inventory_invalid")
    matched = {}
    for asset in assets:
        symbol = asset.get("symbol")
        if symbol not in REGISTRY:
            continue
        if symbol in matched:
            raise ObservationError("asset_inventory_duplicate")
        matched[symbol] = asset
    with storage.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        c.executemany(
            """INSERT INTO sw_asset_verification VALUES(?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET at=excluded.at,evidence=excluded.evidence
            WHERE excluded.at>=sw_asset_verification.at""",
            [(s, now.isoformat(), json.dumps(asset_evidence(s, matched.get(s)))) for s in REGISTRY],
        )
        c.commit()


def midnight(day):
    return datetime.combine(day, wall_time(), NY).astimezone(UTC)


def jobs(now, *, new_only, feed="iex", adjustment="raw", minute_days=20, minute_feed=None):
    last = date.fromisoformat(completed_day(now))
    first = max(date(2016, 1, 1), last - timedelta(days=3652))
    for symbol in sorted(NEW if new_only else REGISTRY):
        # Calendar-year boundaries stay stable across resumed runs. The newest
        # open year is checkpointed in completed monthly partitions.
        month = first.replace(day=1)
        last_month = last.replace(day=1)
        while month < last_month:
            following = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
            yield (
                symbol,
                "1Day",
                feed,
                adjustment,
                midnight(month).isoformat(),
                midnight(following).isoformat(),
            )
            month = following
        cursor = last_month
        while cursor <= last:
            following = cursor + timedelta(days=1)
            if session(cursor.isoformat()):
                yield (
                    symbol,
                    "1Day",
                    feed,
                    adjustment,
                    midnight(cursor).isoformat(),
                    midnight(following).isoformat(),
                )
            cursor = following
    labels = calendar().sessions_window(last.isoformat(), 1 - minute_days) if minute_days else ()
    for label in reversed(labels):
        d = label.date()
        opened = datetime.combine(d, wall_time(4), NY).astimezone(UTC)
        close = session(d.isoformat())[1].astimezone(NY)
        end = datetime.combine(d, wall_time(17 if close.hour < 16 else 20), NY).astimezone(UTC)
        for symbol in REGISTRY:
            yield symbol, "1Min", minute_feed or feed, "raw", opened.isoformat(), end.isoformat()


def queue(now, **kwargs):
    with storage.connect() as c:
        c.executemany(
            """INSERT OR IGNORE INTO sw_history_jobs
            (symbol,timeframe,feed,adjustment,first_at,end_at,state) VALUES(?,?,?,?,?,?,'PENDING')""",
            jobs(now, **kwargs),
        )


def _bars(job, values, now):
    start, end = map(instant, (job["first_at"], job["end_at"]))
    last = instant(job["last_bar"]) if job["last_bar"] else None
    result = []
    for value in values:
        stamp = instant(value["t"])
        if stamp == end:  # provider end is inclusive; partitions are half-open
            continue
        day = stamp.astimezone(NY).date().isoformat()
        if not start <= stamp < end or (last is not None and stamp <= last):
            raise ObservationError("historical_page_not_chronological")
        if job["timeframe"] == "1Day":
            if (
                not session(day)
                or stamp != midnight(date.fromisoformat(day))
                or published_after(day) > now
            ):
                raise ObservationError("historical_daily_session_invalid_or_unpublished")
            phase = "DAILY"
        else:
            phase = phase_at(stamp).name
            if (
                stamp.second
                or stamp.microsecond
                or stamp + timedelta(minutes=1) > now
                or phase not in {"PREMARKET", "CORE", "AFTERHOURS"}
            ):
                raise ObservationError("historical_minute_session_invalid")
        o, h, l, c, v = (positive(value[k]) for k in ("o", "h", "l", "c", "v"))
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ObservationError("historical_invalid_ohlcv")
        result.append(
            (
                job["symbol"],
                job["timeframe"],
                job["feed"],
                job["adjustment"],
                stamp.isoformat(),
                day,
                phase,
                now.isoformat(),
                *(str(x) for x in (o, h, l, c, v)),
            )
        )
        last = stamp
    return result


def step(data, now):
    # Alternate fresh-day partitions with daily research, while giving retries
    # time to cool off. One safe request/page per worker tick except daily actions.
    job = storage.one(
        """SELECT * FROM sw_history_jobs WHERE state IN ('PENDING','RUNNING','RETRY')
        AND (state!='RETRY' OR updated_at IS NULL OR updated_at<?)
        ORDER BY CASE WHEN state='RUNNING' THEN 0 ELSE 1 END, end_at DESC,symbol LIMIT 1""",
        ((now - timedelta(minutes=5)).isoformat(),),
    )
    if not job:
        return False
    key = tuple(job[k] for k in KEY)
    selector = " AND ".join(f"{k}=?" for k in KEY)
    try:
        page, token = data.bar_page(
            [job["symbol"]],
            job["feed"],
            instant(job["first_at"]),
            instant(job["end_at"]),
            job["timeframe"],
            job["adjustment"],
            job["token"],
        )
        bars = _bars(job, page.get(job["symbol"], []), now)
        if token and (token == job["token"] or not bars):
            raise ObservationError("historical_pagination_not_advancing")
        actions = []
        if job["timeframe"] == "1Day" and not token:
            first = instant(job["first_at"]).astimezone(NY).date().isoformat()
            end = (instant(job["end_at"]).astimezone(NY).date() - timedelta(days=1)).isoformat()
            actions = data.corporate_actions(job["symbol"], first, end)
        with storage.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.executemany(
                "INSERT OR IGNORE INTO sw_historical_bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", bars
            )
            c.executemany(
                "INSERT OR IGNORE INTO sw_history_actions VALUES(?,?,?,?)",
                [(job["symbol"], a["day"], a["kind"], now.isoformat()) for a in actions],
            )
            c.execute(
                f"""UPDATE sw_history_jobs SET token=?,last_bar=?,state=?,updated_at=?,error=NULL,attempts=0
                WHERE {selector}""",
                (
                    token,
                    bars[-1][4] if bars else job["last_bar"],
                    "RUNNING" if token else "COMPLETE",
                    now.isoformat(),
                    *key,
                ),
            )
            c.commit()
    except (ObservationError, KeyError, TypeError, ValueError) as exc:
        code = (
            str(exc) if isinstance(exc, ObservationError) else "historical_malformed_provider_row"
        )
        attempts = job["attempts"] + 1
        with storage.connect() as c:
            c.execute(
                f"""UPDATE sw_history_jobs SET state=?,updated_at=?,error=?,attempts=?
                WHERE {selector}""",
                ("ERROR" if attempts >= 5 else "RETRY", now.isoformat(), code, attempts, *key),
            )
    return True


def prune(now, keep=30):
    limit = calendar().sessions_window(completed_day(now), 1 - keep)[0].date().isoformat()
    with storage.connect() as c:
        c.execute(
            "DELETE FROM sw_historical_bars WHERE timeframe='1Min' AND trade_date<?", (limit,)
        )
        c.execute("DELETE FROM sw_history_jobs WHERE timeframe='1Min' AND end_at<?", (limit,))


def report(now, db=None):
    day = completed_day(now)
    expected = set(history_days(day))
    path = Path(db or storage.DB_PATH).resolve()
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) if path.is_file() else None
    try:
        tables = set()
        if connection:
            connection.row_factory = sqlite3.Row
            tables = {
                r[0]
                for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }

        def query(sql, args=()):
            return list(connection.execute(sql, args))

        result = []
        for s, meta in REGISTRY.items():
            legacy = (
                query(
                    "SELECT day FROM sw_eod_observations WHERE symbol=? AND source='alpaca_iex_daily' AND adjustment='RAW' AND day BETWEEN ? AND ?",
                    (s, min(expected), day),
                )
                if "sw_eod_observations" in tables
                else []
            )
            coverage = (
                query(
                    """SELECT timeframe,feed,adjustment,count(*) AS rows,min(trade_date) AS first,
                max(trade_date) AS last,max(observed_at) AS ingested FROM sw_historical_bars WHERE symbol=?
                GROUP BY timeframe,feed,adjustment""",
                    (s,),
                )
                if "sw_historical_bars" in tables
                else []
            )
            archived = (
                query(
                    """SELECT trade_date FROM sw_historical_bars WHERE symbol=? AND timeframe='1Day'
                AND feed='iex' AND adjustment='raw' AND trade_date BETWEEN ? AND ?""",
                    (s, min(expected), day),
                )
                if coverage
                else []
            )
            gaps = sorted(expected - {r[0] for r in legacy} - {r[0] for r in archived})
            cert = sorted(expected - {r[0] for r in legacy})
            checks = (
                query(
                    "SELECT state,count(*) AS jobs,max(updated_at) AS updated_at FROM sw_history_jobs WHERE symbol=? GROUP BY state",
                    (s,),
                )
                if "sw_history_jobs" in tables
                else []
            )
            faults = (
                query(
                    "SELECT DISTINCT error FROM sw_history_jobs WHERE symbol=? AND error IS NOT NULL LIMIT 8",
                    (s,),
                )
                if checks
                else []
            )
            verify = (
                query("SELECT at,evidence FROM sw_asset_verification WHERE symbol=?", (s,))
                if "sw_asset_verification" in tables
                else []
            )
            listing = (
                {"status": "UNVERIFIED"}
                if not verify
                else {**json.loads(verify[0]["evidence"]), "verified_at": verify[0]["at"]}
            )
            enabled = (
                query("SELECT enabled FROM assets WHERE symbol=?", (s,))
                if "assets" in tables
                else []
            )
            state = (
                "RAW_HISTORY_COMPLETE"
                if not gaps
                else "PROVIDER_UNAVAILABLE_OR_INVALID"
                if faults
                else "PARTIAL_HISTORY"
                if len(gaps) < 201
                else "AWAITING_INGESTION"
            )
            result.append(
                {
                    **meta,
                    "enabled": bool(enabled[0][0]) if enabled else True,
                    "asset": listing,
                    "history": state,
                    "eod_certified_window_complete": not cert,
                    "missing_sessions": gaps,
                    "last_expected_session": day,
                    "coverage": [dict(r) for r in coverage],
                    "jobs": [dict(r) for r in checks],
                    "errors": [r[0] for r in faults],
                }
            )
        return {
            "as_of": now.isoformat(),
            "instruments": len(result),
            "companies": 50,
            "benchmarks": 2,
            "kind": "READ_ONLY_HISTORICAL_COVERAGE",
            "symbols": result,
        }
    finally:
        if connection:
            connection.close()


def main():
    from .alpaca_paper import PaperClient, PaperError

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path)
    p.add_argument("--new-universe", action="store_true")
    p.add_argument("--verify", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--feed", choices=("iex", "sip"), default="iex")
    p.add_argument("--adjustment", choices=("raw", "split", "dividend", "all"), default="raw")
    p.add_argument("--minute-feed", choices=("iex", "sip"))
    p.add_argument("--minute-days", type=int, choices=range(31), default=20)
    p.add_argument("--max-steps", type=int, default=100)
    args = p.parse_args()
    now = datetime.now(UTC)
    if args.report:
        print(json.dumps(report(now, args.db), indent=2))
        return
    opts = {
        "new_only": args.new_universe,
        "feed": args.feed,
        "adjustment": args.adjustment,
        "minute_days": args.minute_days,
        "minute_feed": args.minute_feed,
    }
    if args.dry_run:
        print(
            json.dumps(
                {"jobs": sum(1 for _ in jobs(now, **opts)), "instruments": 52, "writes": False}
            )
        )
        return
    if not args.db or not 1 <= args.max_steps <= 10_000:
        p.error("write operations require an explicit --db and 1 to 10000 steps")
    path = args.db.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.DB_PATH = str(path)
    with (path.parent / (path.name + ".worker.lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        initialize()
        if args.verify:
            try:
                with PaperClient(retry_reads=True) as client:
                    verify_assets(client, now)
            except (PaperError, ObservationError) as exc:
                print(
                    json.dumps({"asset_verification": "UNAVAILABLE", "reason": str(exc)}),
                    file=__import__("sys").stderr,
                )
        queue(now, **opts)
        if args.resume:
            with storage.connect() as c:
                c.execute(
                    "UPDATE sw_history_jobs SET state='RETRY',attempts=0,updated_at=NULL WHERE state='ERROR'"
                )
        try:
            with closing(IntradayData(background=True)) as data:
                for _ in range(args.max_steps):
                    if not step(data, datetime.now(UTC)):
                        break
        except RuntimeError as exc:
            if str(exc) != "alpaca_credentials_not_configured":
                raise
            print(
                json.dumps({"history_ingestion": "UNAVAILABLE", "reason": str(exc)}),
                file=__import__("sys").stderr,
            )
        prune(now)
    print(json.dumps(report(now, path), indent=2))


def short_history_ready(symbol, now, asset_id=None):
    """Require a recent real asset verification plus bounded causal research coverage."""
    day = completed_day(now)
    expected = set(history_days(day))
    asset = storage.one("SELECT at,evidence FROM sw_asset_verification WHERE symbol=?", (symbol,))
    if (
        not asset
        or not timedelta(0) <= now - instant(asset["at"]) <= timedelta(days=3)
        or not json.loads(asset["evidence"]).get("verified")
        or (asset_id is not None and json.loads(asset["evidence"]).get("id") != asset_id)
    ):
        return False
    dates = storage.rows(
        """SELECT trade_date AS day FROM sw_historical_bars WHERE symbol=? AND timeframe='1Day'
       AND feed='iex' AND adjustment='raw' AND trade_date BETWEEN ? AND ?
       UNION SELECT day FROM sw_eod_observations WHERE symbol=? AND source='alpaca_iex_daily' AND adjustment='RAW'
       AND day BETWEEN ? AND ?""",
        (symbol, min(expected), day, symbol, min(expected), day),
    )
    if {r["day"] for r in dates} != expected:
        return False
    floor = calendar().sessions_window(day, -10)[0].date().isoformat()
    result = storage.one(
        """SELECT COUNT(*) n FROM (SELECT trade_date FROM sw_historical_bars
       WHERE symbol=? AND timeframe='1Min' AND feed='sip' AND adjustment='raw' AND phase='CORE'
       AND trade_date BETWEEN ? AND ? GROUP BY trade_date HAVING COUNT(*)>=180)""",
        (symbol, floor, day),
    )
    return result["n"] >= 5


if __name__ == "__main__":
    main()
