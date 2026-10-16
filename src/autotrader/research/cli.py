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
    ingest_incremental,
    load_dataset,
    save_dataset,
)


async def download(root: Path, *, start: datetime, end: datetime, assets: list[str],
                   hourly_days: int, intraday_days: int, five_minute_days: int = 180,
                   other_five_minute_days: int = 90, context_days: int = 90) -> dict[str, Any]:
    provider = CoinbaseHistory(root)
    catalog_path = root / "catalog.json"
    previous = json.loads(catalog_path.read_bytes()) if catalog_path.exists() else {}
    indexed = {(m["symbol"], m["timeframe"]): m for m in previous.get("manifests", [])}
    failures: list[dict[str, str]] = []
    def checkpoint() -> dict[str, Any]:
        catalog = {"created_at": utc_now().isoformat(), "requested_assets": assets,
                   "manifests": list(indexed.values()), "failures": failures}
        atomic_write(catalog_path, canonical(catalog))
        return catalog
    try:
        for asset in assets:
            symbol = f"{asset}-EUR"
            for timeframe, since in (("1d", start), ("1h", max(start, end - timedelta(days=hourly_days))),
                                     ("1m", max(start, end - timedelta(days=intraday_days))),
                                     ("5m", max(start, end - timedelta(days=five_minute_days if asset in {"BTC", "ETH"} else other_five_minute_days))),
                                     ("15m", max(start, end - timedelta(days=context_days)))):
                if since >= end:
                    continue
                try:
                    manifest = await ingest_incremental(provider, symbol, timeframe, since, end)
                    indexed[symbol, timeframe] = manifest
                    print(f"DATA {symbol} {timeframe}: {manifest['observations']} bars, {manifest['missing_observations']} missing", flush=True)
                    if timeframe == "1h":
                        bars = load_dataset(root, manifest)
                        derived = aggregate_complete(bars, "4h")
                        indexed[symbol, "4h"] = save_dataset(root, derived,
                            requested_start=datetime.fromisoformat(manifest["requested_start"]),
                            requested_end=datetime.fromisoformat(manifest["requested_end_exclusive"]),
                            symbol=symbol, timeframe="4h", provenance={"parent_dataset": manifest["dataset_version"], "aggregation": "4 contiguous completed UTC hours; gaps are not filled"})
                except (ValueError, TypeError, OSError, httpx.HTTPError) as exc:
                    failure = {"symbol": symbol, "timeframe": timeframe, "error": str(exc)}
                    failures.append(failure)
                    print("DATA_FAILURE " + json.dumps(failure), flush=True)
                checkpoint()
    finally:
        await provider.close()
    return checkpoint()


def main() -> None:
    parser = argparse.ArgumentParser(description="Versioned genuine EUR history and reproducible paper research")
    sub = parser.add_subparsers(dest="command", required=True)
    research = sub.add_parser("research")
    research.add_argument("action", choices=["download", "full", "evaluate", "availability"])
    research.add_argument("--root", type=Path, default=Path(".data/research"))
    research.add_argument("--start", default="2020-01-01")
    research.add_argument("--end", default=utc_now().date().isoformat())
    research.add_argument("--assets", nargs="+", choices=ASSETS, default=list(ASSETS))
    research.add_argument("--hourly-days", type=int, default=180)
    research.add_argument("--intraday-days", type=int, default=2)
    research.add_argument("--five-minute-days", type=int, default=180)
    research.add_argument("--other-five-minute-days", type=int, default=90)
    research.add_argument("--context-days", type=int, default=90)
    research.add_argument("--timeframes", nargs="+", choices=TIMEFRAMES, default=["5m", "15m"])
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if min(args.hourly_days, args.intraday_days, args.five_minute_days, args.other_five_minute_days, args.context_days) < 0:
        parser.error("History windows cannot be negative")
    if args.action in {"evaluate", "availability"}:
        catalog = json.loads((args.root / "catalog.json").read_bytes())
    else:
        catalog = asyncio.run(download(args.root, start=start, end=end, assets=args.assets,
            hourly_days=args.hourly_days, intraday_days=args.intraday_days,
            five_minute_days=args.five_minute_days, other_five_minute_days=args.other_five_minute_days,
            context_days=args.context_days))
    if args.action == "availability":
        for manifest in catalog["manifests"]:
            load_dataset(args.root, manifest)
        print(json.dumps(catalog, indent=2))
    if args.action in {"full", "evaluate"}:
        from autotrader.research.workflow import run_full
        report = run_full(args.root, catalog, timeframes=tuple(args.timeframes), assets=tuple(args.assets))
        print(json.dumps({"run_id": report["run_id"], "verdict": report["verdict"],
                          "passed_strategies": report["passed_strategies"]}), flush=True)
    if catalog["failures"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
