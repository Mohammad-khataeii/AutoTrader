"""Run the isolated €7,000 audit and public-only prospective collector."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
from pathlib import Path

from autotrader.domain import utc_now
from autotrader.market_data.revolut import MarketDataError, RevolutXPublicClient
from autotrader.market_data.service import MarketDataService

from .audit import analyze, timestamp
from .context import cutoff
from .shadow import capture, load_captures, registration, report, write_record


async def collect(root: Path, plan: dict, once: bool) -> None:
    market = MarketDataService(
        RevolutXPublicClient(), candle_lookback=288, max_staleness_seconds=15
    )
    try:
        with (root / "capture.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            prior = load_captures(root, plan, recent=288)
            while True:
                now = utc_now()
                start, end = (timestamp(plan[k]) for k in ("start", "shadow_end"))
                if now >= end:
                    return
                if now < start:
                    if once:
                        raise ValueError("capture_window_not_started")
                    await asyncio.sleep(min(300, (start - now).total_seconds()))
                    continue
                path = root / "captures" / f"{int(cutoff(now).timestamp())}.json"
                if not path.exists():
                    try:
                        async with asyncio.timeout(60):
                            row = await capture(market, plan, prior)
                        # The path reflects the cutoff inside capture if a boundary
                        # was crossed before acquisition actually began.
                        path = (
                            root
                            / "captures"
                            / f"{int(timestamp(row['reference']).timestamp())}.json"
                        )
                        if timestamp(row["observed_at"]) < end:
                            write_record(path, row)
                            prior = [
                                *prior[-287:],
                                {
                                    "reference": row["reference"],
                                    "observed_at": row["observed_at"],
                                    "observed_symbols": row["observed_symbols"],
                                    "selected": row["selected"],
                                    "markets": row["markets"],
                                    "macro": row["macro"],
                                },
                            ]
                            print(
                                f"Captured {row['reference']}, {len(row['markets'])} validated markets",
                                flush=True,
                            )
                    except (MarketDataError, TimeoutError) as exc:
                        print(
                            f"Deferred capture {now.isoformat()} {type(exc).__name__}", flush=True
                        )
                        if once:
                            raise
                if once:
                    return
                await asyncio.sleep(305 - now.timestamp() % 300)
    finally:
        await market.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("archive", type=Path)
    audit.add_argument("--output", type=Path)
    register = sub.add_parser("register")
    register.add_argument("root", type=Path)
    for name in ("start", "development-end", "holdout-end", "shadow-end"):
        register.add_argument("--" + name, required=True, type=timestamp)
    recorder = sub.add_parser("collect")
    recorder.add_argument("root", type=Path)
    recorder.add_argument("--once", action="store_true")
    status = sub.add_parser("report")
    status.add_argument("root", type=Path)
    status.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "audit":
        body = analyze(args.archive)
    elif args.action == "register":
        write_record(
            args.root / "registration.json",
            registration(args.start, args.development_end, args.holdout_end, args.shadow_end),
        )
        return
    else:
        plan = json.loads((args.root / "registration.json").read_bytes())
        if args.action == "collect":
            asyncio.run(collect(args.root, plan, args.once))
            return
        body = report(plan, load_captures(args.root, plan), utc_now())
    if args.output:
        write_record(args.output, body, replace=args.action == "report")
    else:
        print(json.dumps(body, default=str, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
