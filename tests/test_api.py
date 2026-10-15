from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autotrader.api.main import create_app
from autotrader.scanner import ScanResult


class UnavailableScanner:
    async def scan_once(self, _max_pairs: int) -> ScanResult:
        return ScanResult(
            status="DATA_UNAVAILABLE",
            scanned=0,
            rejected=[],
            provider_errors=["provider offline"],
            candidates=[],
            duration_ms=Decimal("1"),
        )


def test_api_scanner_serializes_domain_objects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL",f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    app=create_app()
    with TestClient(app) as client:
        client.portal.call(app.state.repository.store_scan, __import__("asyncio").run(UnavailableScanner().scan_once(1)))
        response = client.get("/api/scanner", auth=("admin", "change-me"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "DATA_UNAVAILABLE"
    assert "features" in payload
    assert "signals" in payload
    assert "decision" in payload


def test_api_paper_order_rejects_when_no_real_candidate() -> None:
    app=create_app()
    app.state.scanner = UnavailableScanner()
    client = TestClient(app)
    response = client.post("/api/paper/orders", auth=("admin", "change-me"))
    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "DATA_UNAVAILABLE"
