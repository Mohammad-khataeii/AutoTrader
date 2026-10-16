import asyncio
import copy
import os
import subprocess
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import httpx

from autotrader.domain import utc_now
from autotrader.indicators import calculate_features
from autotrader.market_data.replay import FileReplayClient
from autotrader.research.context import completed_context
from autotrader.research.experimental import ExperimentalStrategyEngine
from process_support import ApiProcess, WorkerProcess, wait_for, write_frame


def experimental_frame(identity: str, price: D, depth="1000"):
    now = utc_now()
    end = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 5 + 5)
    candles = []
    for i in range(720):
        close = D(100) + D(i) * D(".04") if i < 719 else D("129.1")
        candles.append(
            {
                "timestamp": (end - timedelta(minutes=5 * (719 - i))).isoformat(),
                "open": str(close - D(".1")),
                "high": str(close + D(".3")),
                "low": str(close - D(".3")),
                "close": str(close),
                "volume": "1200" if i == 719 else "1000",
            }
        )
    candles[-1]["low"] = "128.3"
    market = {
        "candles": candles,
        "book": {
            "timestamp": now.isoformat(),
            "bids": [[str(price), depth]],
            "asks": [[str(price + D(".01")), "1000"]],
        },
    }
    return {
        "frame_id": identity,
        "pairs": [
            {
                "symbol": s,
                "base_asset": s.split("-")[0],
                "quote_asset": "EUR",
                "price_step": ".001",
                "quantity_step": ".00000001",
                "min_order_quote": "1",
            }
            for s in ("BTC-EUR", "ETH-EUR")
        ],
        "markets": {s: copy.deepcopy(market) for s in ("BTC-EUR", "ETH-EUR")},
    }


async def test_actual_experimental_worker_partial_targets_sigkill_restart_and_official_api(
    lab, tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("SHADOW_ENABLED", "true")
    replay = tmp_path / "shadow-lifecycle.json"
    write_frame(replay, experimental_frame("qualifying-A2", D("129.1")))
    external = FileReplayClient(str(replay))
    cs = await external.get_candles("BTC-EUR", 5, 0, 0)
    f = calculate_features(cs[-240:], D(0), D(1))
    f.metadata["experimental_context"] = completed_context(cs, utc_now())
    assert next(
        s
        for s in ExperimentalStrategyEngine().generate(f, f, f)
        if s.strategy_id == "A2_CONFIRMED_PULLBACK"
    ).evidence["entry_eligible"]
    record = await lab.create("lifecycle", "A2 process acceptance", "A2_CONFIRMED_PULLBACK")
    assert record["manifest"]["data_kind"] == "SYNTHETIC_ACCEPTANCE"
    repo = await lab.repository(record["experiment_id"])
    worker = WorkerProcess(lab.official.test_database_url, replay, execution_costs=("10", "8"))
    api = ApiProcess(lab.official.test_database_url, tmp_path)
    try:
        await worker.wait_started(lab.official)

        async def opened():
            ps = await repo.list_positions()
            return ps if ps else None

        positions = await wait_for(opened, worker=worker)
        # BTC/ETH correlation admits at most one exposure under existing policy.
        assert len(positions) == 1
        p = positions[0]
        targets = await repo.list_targets(p.position_id)
        q1 = D(targets[0]["original_planned_quantity"])
        q2 = D(targets[1]["original_planned_quantity"])
        factor = D(".999") * D(".9992")

        async def progress(expected):
            return [
                D(t["filled_quantity"]) for t in await repo.list_targets(p.position_id)
            ] == expected

        write_frame(
            replay,
            experimental_frame("shadow-TP1", D(targets[0]["target_price"]) / factor + D(".01")),
        )
        await wait_for(lambda: progress([q1, D(0), D(0)]), worker=worker)
        partial = (q2 / 2).quantize(D(".00000001"))
        write_frame(
            replay,
            experimental_frame(
                "shadow-TP2-partial",
                D(targets[1]["target_price"]) / factor + D(".01"),
                str(partial),
            ),
        )
        await wait_for(lambda: progress([q1, partial, D(0)]), worker=worker)
        old_pid = worker.kill()
        worker = WorkerProcess(lab.official.test_database_url, replay, execution_costs=("10", "8"))
        new_pid = await worker.wait_started(lab.official)
        assert new_pid != old_pid and await progress([q1, partial, D(0)])
        write_frame(
            replay,
            experimental_frame(
                "shadow-TP2-remainder",
                D(targets[1]["target_price"]) / factor + D(".02"),
                str(q2 - partial),
            ),
        )
        await wait_for(lambda: progress([q1, q2, D(0)]), worker=worker)
        write_frame(replay, experimental_frame("shadow-stop-gap", D(127)))

        async def closed():
            return (await repo.list_positions())[0].quantity == 0

        await wait_for(closed, worker=worker)
        assert await repo.verify_invariants(D(500)) == []
        async with httpx.AsyncClient(
            base_url=api.url, auth=("admin", "change-me"), timeout=10
        ) as client:

            async def ready():
                try:
                    return (await client.get("/readyz")).status_code == 200
                except httpx.TransportError:
                    return False

            await wait_for(ready, worker=api)
            official = (await client.get("/api/overview")).json()
            assert (
                D(official["portfolio"]["equity"]) == 500
                and not official["fills"]
                and not official["orders"]
            )
            report = (await client.get("/api/shadow/" + record["experiment_id"])).json()
            assert len(report["fills"]) == 5 and report["reconciliation"] == []
            assert report["positions"][0]["quantity"] == "0E-12"
            assert report["manifest"]["data_kind"] == "SYNTHETIC_ACCEPTANCE"
            assert (await client.get("/api/execution")).json()["entry_policy"]["require_validation"]
            assert (
                await client.get("/api/shadow/" + record["experiment_id"] + "/export")
            ).status_code == 200
        if os.environ.get("AUTOTRADER_BROWSER_ACCEPTANCE") == "1":
            completed = await asyncio.to_thread(
                subprocess.run,
                ["node", "frontend/e2e/lifecycle-proof.mjs"],
                env={**os.environ, "AUTOTRADER_LIFECYCLE_API": api.url,
                     "AUTOTRADER_LIFECYCLE_EXPERIMENT": record["experiment_id"]},
                capture_output=True, text=True, check=False,
            )
            assert completed.returncode == 0, completed.stdout + completed.stderr
            print(completed.stdout)
        print(
            f"V42_SHADOW_PROCESS actual worker {old_pid}->{new_pid}; API={api.actual_pid}; A2 real signal; 5 fills; TP2 partial survived SIGKILL; official EUR500 no orders; reconciliation=[]; SYNTHETIC_ACCEPTANCE"
        )
    finally:
        worker.kill()
        api.kill()
