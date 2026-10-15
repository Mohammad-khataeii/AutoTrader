from __future__ import annotations

import copy
from decimal import Decimal as D
from pathlib import Path

import httpx

from autotrader.persistence.repository import PersistentTradingRepository
from process_support import ApiProcess, WorkerProcess, replay_frame, wait_for, write_frame


def multi_frame(identity: str, price: D, *, qualifying: bool = False, depth: str = "1000"):
    result = replay_frame(identity, price, depth, qualifying=qualifying)
    btc = result["markets"]["BTC-EUR"]
    eth = copy.deepcopy(btc)
    for market, width in ((btc, D(".002")), (eth, D(".10"))):
        for candle in market["candles"]:
            closing = D(candle["close"])
            candle.update(open=str(closing-D(".001")), high=str(closing+width), low=str(closing-width))
    result["markets"]["ETH-EUR"] = eth
    result["pairs"].append({**result["pairs"][0], "symbol":"ETH-EUR", "base_asset":"ETH"})
    return result


async def test_v4_real_worker_cost_rejection_partial_targets_restart_and_api(pg_repo: PersistentTradingRepository, tmp_path: Path) -> None:
    repo = pg_repo
    replay = tmp_path / "v4-lifecycle.json"
    write_frame(replay, multi_frame("two-qualifying-candidates", D("9.92"), qualifying=True))
    api = ApiProcess(repo.test_database_url, tmp_path)  # type: ignore[attr-defined]
    worker = WorkerProcess(repo.test_database_url, replay, execution_costs=("10", "8"))  # type: ignore[attr-defined]
    try:
        await worker.wait_started(repo)
        async def opened():
            positions = await repo.list_positions()
            return positions if positions else None
        positions = await wait_for(opened, worker=worker)
        assert len(positions) == 1 and positions[0].symbol == "ETH-EUR"
        async def rejected_cost():
            orders = await repo.execution_analytics(D(10), D(8))
            return any(o["symbol"] == "BTC-EUR" and "first_target_destroyed_by_execution_costs" in (o["rejection_reason"] or "") for o in orders["orders"])
        await wait_for(rejected_cost, worker=worker)
        position = positions[0]
        targets = await repo.list_targets(position.position_id)
        q1, q2 = [D(row["original_planned_quantity"]) for row in targets[:2]]
        async def progress(expected):
            return [D(row["filled_quantity"]) for row in await repo.list_targets(position.position_id)] == expected
        factor = D(".999") * D(".9992")
        write_frame(replay, multi_frame("tp1-net-executable", D(targets[0]["target_price"])/factor+D(".003")))
        await wait_for(lambda: progress([q1,D(0),D(0)]), worker=worker)
        partial = (q2 / 2).quantize(D(".00000001"))
        write_frame(replay, multi_frame("tp2-finite-partial", D(targets[1]["target_price"])/factor+D(".003"), depth=str(partial)))
        await wait_for(lambda: progress([q1,partial,D(0)]), worker=worker)
        old_pid = worker.kill()
        worker = WorkerProcess(repo.test_database_url, replay, execution_costs=("10", "8"))  # type: ignore[attr-defined]
        new_pid = await worker.wait_started(repo)
        assert new_pid != old_pid and await progress([q1,partial,D(0)])
        write_frame(replay, multi_frame("tp2-new-observation", D(targets[1]["target_price"])/factor+D(".004"), depth=str(q2-partial)))
        await wait_for(lambda: progress([q1,q2,D(0)]), worker=worker)
        write_frame(replay, multi_frame("protective-gap", D("9.7")))
        async def closed():
            return (await repo.list_positions())[0].quantity == 0
        await wait_for(closed, worker=worker)
        async with httpx.AsyncClient(base_url=api.url, auth=("admin","change-me"), timeout=10) as client:
            async def ready():
                try:
                    return (await client.get("/readyz")).status_code == 200
                except httpx.TransportError:
                    return False
            await wait_for(ready, worker=api)
            overview = (await client.get("/api/overview")).json()
            assert len(overview["fills"]) == 5 and len({f["fill_id"] for f in overview["fills"]}) == 5
            assert [D(t["filled_quantity"]) for t in overview["targets"]] == [q1,q2,D(0)]
            assert D(overview["portfolio"]["reserved_cash"]) == 0
            assert (await client.get("/api/execution")).status_code == 200
            assert (await client.get("/api/intelligence")).status_code == 200
            assert (await client.get("/api/research")).status_code == 200
        assert await repo.verify_invariants(D(500)) == []
        print(f"V4_LIFECYCLE actual worker {old_pid}->{new_pid}; API={api.actual_pid}; BTC cost rejected; ETH 5 fills; TP2 partial survived restart; replay=[]")
    finally:
        worker.kill()
        api.kill()
