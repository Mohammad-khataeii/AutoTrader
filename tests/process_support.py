from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from autotrader.domain import utc_now


def replay_frame(frame_id: str, price: Decimal, bid_quantity: str = "1000", *, qualifying: bool = False) -> dict[str, Any]:
    # Every observation is closed and timestamped. No internal trading component is mocked.
    now = utc_now()
    end = now.replace(second=0, microsecond=0) - timedelta(minutes=5)
    candles = []
    for i in range(240):
        close = Decimal("9.8") + Decimal(i) / Decimal("2000") if qualifying else price
        volume = Decimal("450") if qualifying and i == 239 else Decimal("100")
        candles.append({"timestamp": (end - timedelta(minutes=5 * (239-i))).isoformat(),
            "open": str(close - Decimal("0.005")), "high": str(close + Decimal("0.02")),
            "low": str(close - Decimal("0.02")), "close": str(close), "volume": str(volume)})
    return {"frame_id": frame_id, "pairs": [{"symbol": "BTC-EUR", "base_asset": "BTC", "quote_asset": "EUR", "price_step": "0.001", "quantity_step": "0.00000001", "min_order_quote": "1"}],
        "markets": {"BTC-EUR": {"candles": candles, "book": {"timestamp": now.isoformat(),
            "bids": [[str(price-Decimal("0.001")), bid_quantity]],
            "asks": [[str(price+Decimal("0.001")), "1000"]]}}}}


def write_frame(path: Path, frame: dict[str, Any]) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(frame), encoding="utf-8")
    os.replace(temp, path)


class WorkerProcess:
    def __init__(self, database_url: str, replay_file: Path, failpoint: str | None = None) -> None:
        env = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "test",
            "AI_PROVIDER": "mock", "MARKET_DATA_REPLAY_FILE": str(replay_file),
            "WORKER_SCAN_INTERVAL_SECONDS": "1", "DEFAULT_FEE_BPS": "0", "DEFAULT_SLIPPAGE_BPS": "0"}
        env.pop("AUTOTRADER_FAILPOINT", None)
        if failpoint:
            env["AUTOTRADER_FAILPOINT"] = failpoint
        self.log_path = replay_file.parent / ("worker-" + str(time.time_ns()) + ".log")
        self.log = self.log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen([sys.executable, "-m", "autotrader.worker.runner"], env=env,
            stdout=self.log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def kill(self) -> int:
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=15)
        self.log.close()
        assert self.process.poll() is not None
        return self.process.pid


class ApiProcess(WorkerProcess):
    def __init__(self, database_url: str, directory: Path) -> None:
        import socket
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        self.log_path = directory / "api.log"
        self.log = self.log_path.open("w", encoding="utf-8")
        env = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "test", "AI_PROVIDER": "mock"}
        env.pop("MARKET_DATA_REPLAY_FILE", None)
        env.pop("AUTOTRADER_FAILPOINT", None)
        self.process = subprocess.Popen([sys.executable, "-m", "uvicorn", "autotrader.api.main:app",
            "--host", "127.0.0.1", "--port", str(port)], env=env,
            stdout=self.log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


async def wait_for(check: Callable[[], Any], *, worker: WorkerProcess | None = None, timeout: float = 40) -> Any:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        value = await check()
        if value:
            return value
        if worker and worker.process.poll() is not None:
            raise AssertionError("Worker exited: " + worker.log_path.read_text(encoding="utf-8"))
        await asyncio.sleep(0.15)
    raise AssertionError("Timed out waiting for persisted transition. " + (worker.log_path.read_text(encoding="utf-8") if worker else ""))
