import json
from pathlib import Path

from fastapi.testclient import TestClient

from autotrader.api.main import create_app


def test_authenticated_shadow_controls_cannot_choose_accounts_or_bypass_validation(
    monkeypatch, tmp_path: Path
):
    # SQLite only verifies HTTP/auth/shape; financial shadow tests require PG.
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("SHADOW_ENABLED", "true")
    monkeypatch.setenv("RESEARCH_ROOT", str(tmp_path / "research"))
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/api/shadow").status_code == 401
        auth = ("admin", "change-me")
        view = client.get("/api/shadow", auth=auth)
        assert view.status_code == 200 and view.json()["experiments"] == []
        forged = client.post(
            "/api/shadow",
            auth=auth,
            json={
                "request_id": "fake",
                "name": "Fake",
                "strategy_id": "A2_CONFIRMED_PULLBACK",
                "account_id": "paper-eur",
            },
        )
        assert forged.status_code == 422
        assert (
            client.post(
                "/api/shadow",
                auth=auth,
                json={"request_id": "fake", "name": "Fake", "strategy_id": "D2_MOMENTUM_QUALITY"},
            ).status_code
            == 409
        )
        assert client.post("/api/shadow/missing/force-trade", auth=auth).status_code == 409
        assert client.get("/api/market-data/health", auth=auth).status_code == 200
        assert (
            client.get("/api/research/trade-failures", auth=auth).json()["status"]
            == "NO_DIAGNOSTICS"
        )
        assert client.get("/api/overview", auth=auth).json()["portfolio"]["positions"] == "0"


def test_failure_explorer_filters_recorded_data_and_rejects_bad_queries(
    monkeypatch, tmp_path: Path
):
    root = tmp_path / "research"
    (root / "diagnostics").mkdir(parents=True)
    row = {
        "strategy": "A",
        "asset": "BTC-EUR",
        "regime": "RANGE",
        "timeframe": "5m",
        "entry_timestamp": "2026-10-01T12:00:00+00:00",
        "classifications": {"ENTRY_TOO_LATE": "rule"},
        "exits": [{"reason": "TIME_EXIT"}],
        "net_pnl": "-1",
    }
    (root / "diagnostics" / "v42-original-trades.json").write_text(
        json.dumps(
            {
                "positions": [row, {**row, "net_pnl": "2"}],
                "run_id": "frozen",
                "data_kind": "HISTORICAL_OHLCV_PROXY",
                "classification_counts": {},
                "limitations": [],
            }
        )
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("RESEARCH_ROOT", str(root))
    with TestClient(create_app()) as client:
        auth = ("admin", "change-me")
        response = client.get(
            "/api/research/trade-failures?strategy=A&outcome=LOSS&classification=ENTRY_TOO_LATE&start_date=2026-10-01",
            auth=auth,
        )
        assert response.status_code == 200 and response.json()["positions"] == [row]
        assert client.get("/api/research/trade-failures?limit=501", auth=auth).status_code == 422
        assert client.get("/api/research/trade-failures?offset=-1", auth=auth).status_code == 422


async def test_full_authenticated_export_is_not_truncated_to_the_ui_window(lab, monkeypatch):
    import asyncio
    from decimal import Decimal

    from test_v42_shadow import enter

    record = await lab.create("export", "Export", "A_TREND_PULLBACK")
    repo = await lab.repository(record["experiment_id"])
    result, _ = await enter(repo)
    assert result.accepted
    for _ in range(505):
        await repo.snapshot()
    assert await repo.verify_invariants(Decimal(500)) == []
    monkeypatch.setenv("DATABASE_URL", lab.official.test_database_url)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("SHADOW_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "change-me")
    monkeypatch.setenv("RESEARCH_ROOT", "/tmp/no-export-research-required")

    def read():
        with TestClient(create_app()) as client:
            path = "/api/shadow/" + record["experiment_id"] + "/history/"
            assert client.get(path + "equity").status_code == 401
            response = client.get(path + "equity", auth=("admin", "change-me"))
            assert response.status_code == 200
            rows = [json.loads(line) for line in response.text.splitlines()]
            assert len(rows) > 500
            assert all(r["account_id"] == "shadow:" + record["experiment_id"] for r in rows)
            journal = client.get(path + "journal", auth=("admin", "change-me"))
            entries = [json.loads(line) for line in journal.text.splitlines()]
            assert sum(r["event_type"] == "INITIAL_FUNDING" for r in entries) == 1
            assert any(r["event_type"] == "BUY_FILL" for r in entries)
            assert client.get(path + "accounts", auth=("admin", "change-me")).status_code == 422
            assert (
                client.get(
                    "/api/shadow/not-an-experiment/history/journal", auth=("admin", "change-me")
                ).status_code
                == 404
            )

    await asyncio.to_thread(read)
    assert Decimal((await lab.official.snapshot())["equity"]) == 500
