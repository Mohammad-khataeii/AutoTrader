from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from autotrader.domain import utc_now
from autotrader.research.data import (
    ASSETS,
    TIMEFRAMES,
    CoinbaseHistory,
    aggregate_complete,
    atomic_write,
    canonical,
    save_dataset,
)


async def download(root: Path, *, start: datetime, end: datetime, assets: list[str],
                   hourly_days: int, intraday_days: int) -> dict[str, Any]:
    provider = CoinbaseHistory(root)
    manifests = []
    failures = []
    try:
        for asset in assets:
            symbol = f"{asset}-EUR"
            for timeframe, since in (("1d", start), ("1h", max(start, end - timedelta(days=hourly_days))),
                                     ("1m", max(start, end - timedelta(days=intraday_days))),
                                     ("5m", max(start, end - timedelta(days=intraday_days))),
                                     ("15m", max(start, end - timedelta(days=intraday_days)))):
                if since >= end:
                    continue
                try:
                    bars, provenance = await provider.fetch(symbol, timeframe, since, end)
                    manifest = save_dataset(root, bars, requested_start=since, requested_end=end,
                        symbol=symbol, timeframe=timeframe, provenance=provenance)
                    manifests.append(manifest)
                    print(f"DATA {symbol} {timeframe}: {manifest['observations']} bars, {manifest['missing_observations']} missing", flush=True)
                    if timeframe == "1h":
                        derived = aggregate_complete(bars, "4h")
                        manifests.append(save_dataset(root, derived, requested_start=since, requested_end=end,
                            symbol=symbol, timeframe="4h", provenance={"parent_dataset": manifest["dataset_version"], "aggregation": "4 contiguous completed UTC hours; gaps are not filled"}))
                except (ValueError, TypeError, OSError, httpx.HTTPError) as exc:
                    failure = {"symbol": symbol, "timeframe": timeframe, "error": str(exc)}
                    failures.append(failure)
                    print("DATA_FAILURE " + json.dumps(failure), flush=True)
    finally:
        await provider.close()
    catalog = {"created_at": utc_now().isoformat(), "requested_assets": assets,
               "manifests": manifests, "failures": failures}
    atomic_write(root / "catalog.json", canonical(catalog))
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Versioned genuine EUR history and reproducible paper research")
    sub = parser.add_subparsers(dest="command", required=True)
    research = sub.add_parser("research")
    research.add_argument("action", choices=["download", "full"])
    research.add_argument("--root", type=Path, default=Path(".data/research"))
    research.add_argument("--start", default="2020-01-01")
    research.add_argument("--end", default=utc_now().date().isoformat())
    research.add_argument("--assets", nargs="+", choices=ASSETS, default=list(ASSETS))
    research.add_argument("--hourly-days", type=int, default=180)
    research.add_argument("--intraday-days", type=int, default=2)
    research.add_argument("--timeframes", nargs="+", choices=TIMEFRAMES, default=["1d", "4h"])
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if args.hourly_days < 0 or args.intraday_days < 0:
        parser.error("History windows cannot be negative")
    catalog = asyncio.run(download(args.root, start=start, end=end, assets=args.assets,
        hourly_days=args.hourly_days, intraday_days=args.intraday_days))
    if args.action == "full":
        from autotrader.research.workflow import run_full
        report = run_full(args.root, catalog, timeframes=tuple(args.timeframes))
        print(json.dumps({"run_id": report["run_id"], "verdict": report["verdict"],
                          "passed_strategies": report["passed_strategies"]}), flush=True)
    if catalog["failures"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
