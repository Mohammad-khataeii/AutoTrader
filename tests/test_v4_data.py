from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from autotrader.research.artifacts import load_latest
from autotrader.research.data import (
    CoinbaseHistory,
    HistoricalBar,
    aggregate_complete,
    canonical,
    digest,
    load_dataset,
    save_dataset,
    validate_bar,
)

START = datetime(2024, 1, 1, tzinfo=UTC)


def bar(hour: int = 0) -> HistoricalBar:
    return HistoricalBar("unit-fixture", "BTC-EUR", "BTC", "EUR", (START + timedelta(hours=hour)).isoformat(),
        "1h", "100", "102", "99", "101", "3", START.isoformat(), ())


def test_complete_aggregation_omits_gapped_and_partial_buckets() -> None:
    result = aggregate_complete([bar(i) for i in range(7)], "4h")
    assert len(result) == 1 and result[0].volume == "12"
    assert result[0].start == START.isoformat()
    assert aggregate_complete([bar(i) for i in (0, 1, 3)], "4h") == []
    assert aggregate_complete([bar(0), bar(1), bar(1), bar(3)], "4h") == []


@pytest.mark.parametrize("changes", [{"quote": "USD"}, {"symbol": "BTC-USD"}, {"high": "98"},
                                     {"volume": "-1"}, {"close": "NaN"}, {"start": START.replace(tzinfo=None).isoformat()}])
def test_invalid_history_rejected(changes: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        validate_bar(replace(bar(), **changes))  # type: ignore[arg-type]


def test_manifest_gap_provenance_duplicates_hash_and_resume_identity(tmp_path: Path) -> None:
    manifest = save_dataset(tmp_path, [bar(0), bar(0), bar(2)], requested_start=START,
        requested_end=START + timedelta(hours=4), symbol="BTC-EUR", timeframe="1h", provenance={"test": "unit fixture"})
    assert manifest["observations"] == 2 and manifest["duplicates_removed"] == 1
    assert manifest["missing_observations"] == 2 and len(manifest["gaps"]) == 2
    loaded = load_dataset(tmp_path, manifest)
    assert len(loaded) == 2 and loaded[0].dataset_version == manifest["dataset_version"]
    second = save_dataset(tmp_path, [replace(bar(0), ingested_at="2025-01-01T00:00:00+00:00"), bar(2)],
        requested_start=START, requested_end=START + timedelta(hours=4), symbol="BTC-EUR", timeframe="1h", provenance={})
    assert second["dataset_version"] == manifest["dataset_version"]
    path = tmp_path / second["file"]
    path.write_bytes(path.read_bytes() + b"corrupted")
    with pytest.raises(ValueError, match="hash_mismatch"):
        load_dataset(tmp_path, second)


async def test_public_provider_page_filtering_and_cached_resumption(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def boundary(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET" and "authorization" not in request.headers
        if request.url.path == "/products":
            return httpx.Response(200, json=[{"id": "BTC-EUR", "base_currency": "BTC", "quote_currency": "EUR", "status": "online"}])
        start = datetime.fromisoformat(request.url.params["start"])
        # Include the documented provider extras before the requested page.
        rows = [[int((start + timedelta(hours=i)).timestamp()), 99, 102, 100, 101, 3] for i in range(-1, 300)]
        return httpx.Response(200, json=rows)

    client = httpx.AsyncClient(base_url="https://api.exchange.coinbase.com", transport=httpx.MockTransport(boundary))
    provider = CoinbaseHistory(tmp_path, client)
    try:
        result, provenance = await provider.fetch("BTC-EUR", "1h", START, START + timedelta(hours=301))
        assert len(result) == 301 and len(provenance["pages"]) == 2
        assert len(requests) == 3
        repeated, _ = await provider.fetch("BTC-EUR", "1h", START, START + timedelta(hours=301))
        assert repeated == result and len(requests) == 3
        with pytest.raises(ValueError, match="unsupported_genuine_eur"):
            await provider.fetch("BTC-USD", "1h", START, START + timedelta(hours=1))
        raw = tmp_path / "raw" / (digest(canonical({"path":"/products", "params":{}})) + ".json")
        stored = json.loads(raw.read_text(encoding="utf-8"))
        stored["body"] = "{}"
        raw.write_text(json.dumps(stored), encoding="utf-8")
        with pytest.raises(ValueError, match="cache_hash_mismatch"):
            await provider._get("/products", {})
    finally:
        await provider.close()


def test_report_pointer_portable_between_windows_and_linux(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "research-20261015T000000"
    run.mkdir(parents=True)
    body = canonical({"verdict":"NO STRATEGY PASSED VALIDATION"})
    (run / "summary.json").write_bytes(body)
    (tmp_path / "latest-run.json").write_bytes(canonical({"summary":"runs\\research-20261015T000000\\summary.json", "summary_sha256":digest(body)}))
    assert load_latest(tmp_path)["verdict"] == "NO STRATEGY PASSED VALIDATION"
    (tmp_path / "latest-run.json").write_bytes(canonical({"summary":"../outside.json", "summary_sha256":digest(body)}))
    with pytest.raises(ValueError, match="outside_store"):
        load_latest(tmp_path)
