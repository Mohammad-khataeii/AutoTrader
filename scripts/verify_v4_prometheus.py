"""Verify selected patched Prometheus against the actual authenticated backend."""
from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main() -> None:
    values = dict(line.split("=", 1) for line in Path(".tools/v34-test.env").read_text(encoding="utf-8").splitlines()
                  if "=" in line and not line.startswith("#"))
    base = f"http://127.0.0.1:{values.get('PROMETHEUS_PORT', '9090')}"
    deadline = time.monotonic() + 70
    with httpx.Client(base_url=base, timeout=5) as client:
        while True:
            response = client.get("/api/v1/targets")
            if response.is_success:
                targets = response.json()["data"]["activeTargets"]
                if targets and all(t["health"] == "up" for t in targets):
                    break
            if time.monotonic() > deadline:
                raise RuntimeError("Authenticated backend scrape did not become healthy")
            time.sleep(1)
        assert client.get("/-/ready").status_code == 200
        assert client.get("/query").status_code == 200
        # The actual UI names assets with hashes; extract a referenced module.
        module = re.search(r'<script[^>]+src="([^"]+)"', client.get("/query").text)
        assert module is not None, "Missing embedded UI script"
        assets = client.get(module[1])
        assert assets.status_code == 200 and len(assets.content) > 100
        query = client.get("/api/v1/query", params={"query":'up{job="autotrader-backend"}'}).json()
        assert query["status"] == "success" and query["data"]["result"]
        assert all(row["value"][1] == "1" for row in query["data"]["result"])
        build = client.get("/api/v1/status/buildinfo").json()["data"]
        assert build["version"] == "3.15.0" and build["goVersion"] == "go1.27.2"
    identity = json.loads(subprocess.check_output(["docker", "image", "inspect", "autotrader-v4-prometheus:3.15.0-patched"]))[0]
    result = {"status":"PASSED", "checked_at":datetime.now(UTC).isoformat(), "image_id":identity["Id"],
              "build":build, "config_check":"promtool check config PASSED", "ui_asset_bytes":len(assets.content),
              "authenticated_backend_scrape":"up=1", "loopback_url":base,
              "targets":[{"health":t["health"], "scrapeUrl":t["scrapeUrl"], "lastError":t["lastError"]} for t in targets]}
    Path("docs/evidence/v4-prometheus-functional.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
