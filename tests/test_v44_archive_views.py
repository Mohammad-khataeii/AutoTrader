import asyncio
import json
import time
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine

from autotrader.api.main import create_app
from autotrader.persistence.models import (
    JournalEventModel,
    StrategySignalModel,
    SystemStateModel,
    TradingDecisionModel,
)
from autotrader.shadow.views import page, record_reconciliation, summaries
from test_v42_shadow import enter


async def test_archive_paused_or_stopped_accounts_releases_slots_preserving_identity_ledger_and_exports(
    lab,
):
    records = [
        await lab.create(str(i), f"Account {i}", "B2_CONFIRMED_COMPRESSION") for i in range(8)
    ]
    original = [r["manifest"] for r in records]
    with pytest.raises(ValueError, match="pause_or_stop"):
        await lab.archive(records[0]["experiment_id"])
    with pytest.raises(ValueError, match="limit"):
        await lab.create("full", "Full", "A2_CONFIRMED_PULLBACK")
    await lab.control(records[0]["experiment_id"], "pause")
    before = await (await lab.repository(records[0]["experiment_id"])).history()
    result = await lab.archive(records[0]["experiment_id"])
    assert result["history_preserved"] and result["slot_released"]
    assert await lab.archive(records[0]["experiment_id"]) == result
    assert (await lab.detail(records[0]["experiment_id"]))["manifest"] == original[0]
    assert (await (await lab.repository(records[0]["experiment_id"])).history())[
        "journal"
    ] == before["journal"]
    with pytest.raises(ValueError, match="archived"):
        await lab.control(records[0]["experiment_id"], "resume")
    new = await lab.create("replacement", "New independent account", "A2_CONFIRMED_PULLBACK")
    assert new["experiment_id"] not in [r["experiment_id"] for r in records]
    assert len(await lab.records()) == 9
    assert len((await summaries(lab))["experiments"]) == 8
    assert len((await summaries(lab, archived=True))["experiments"]) == 1
    await lab.control(records[1]["experiment_id"], "stop")
    await lab.archive(records[1]["experiment_id"])
    for record in await lab.records():
        repo = await lab.repository(record["experiment_id"])
        assert await repo.verify_invariants(D(500)) == []
        async with repo.session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(JournalEventModel)
                    .where(JournalEventModel.event_type == "INITIAL_FUNDING")
                )
                == 1
            )
    assert (await lab.official.snapshot())["equity"] == "500.000000000000"


async def test_archiving_paused_open_position_is_rejected_and_monitoring_remains(lab):
    record = await lab.create("open", "Protected", "A_TREND_PULLBACK")
    repo = await lab.repository(record["experiment_id"])
    assert (await enter(repo))[0].accepted
    await lab.control(record["experiment_id"], "pause")
    with pytest.raises(ValueError, match="open_positions"):
        await lab.archive(record["experiment_id"])
    assert not (await lab.records())[0]["archived_at"]
    assert (await repo.snapshot())["control"] == "PAUSED"
    assert await repo.verify_invariants(D(500)) == []


async def test_keyset_pages_handle_timestamp_ties_new_insertions_and_account_scope(lab):
    records = [await lab.create(str(i), "Page", "A2_CONFIRMED_PULLBACK") for i in range(2)]
    repo = await lab.repository(records[0]["experiment_id"])
    stamp = datetime.now(UTC)
    async with repo.session_factory() as session, session.begin():
        for i in range(113):
            session.add(
                TradingDecisionModel(
                    decision_id=f"dec_v44_{i:04}",
                    symbol="BTC-EUR",
                    action="WAIT",
                    accepted=False,
                    rejected_reason="observed_test_reason",
                    payload_json="{}",
                    created_at=stamp,
                )
            )
    first = await page(repo, "decisions", 17)
    async with repo.session_factory() as session, session.begin():
        session.add(
            TradingDecisionModel(
                decision_id="later",
                symbol="BTC-EUR",
                action="WAIT",
                accepted=False,
                payload_json="{}",
            )
        )
    rows = first["items"]
    cursor = first["next_cursor"]
    while cursor:
        result = await page(repo, "decisions", 17, cursor)
        rows += result["items"]
        cursor = result["next_cursor"]
    assert len(rows) == 113 and len({r["decision_id"] for r in rows}) == 113
    assert "later" not in [r["decision_id"] for r in rows]
    other = await lab.repository(records[1]["experiment_id"])
    with pytest.raises(ValueError, match="cursor"):
        await page(other, "decisions", 17, first["next_cursor"])
    with pytest.raises(ValueError, match="cursor"):
        await page(repo, "fills", 17, first["next_cursor"])
    assert not (await page(repo, "journal"))["next_cursor"]
    assert (await page(repo, "journal"))["items"][0]["event_type"] == "INITIAL_FUNDING"


async def test_summary_size_time_query_budget_authentication_and_readiness(lab, monkeypatch,tmp_path):
    for i in range(4):
        record = await lab.create(f"metric-{i}", f"Metric {i}", "A2_CONFIRMED_PULLBACK")
        repo = await lab.repository(record["experiment_id"])
        async with repo.session_factory() as session, session.begin():
            for j in range(60):
                session.add(
                    StrategySignalModel(
                        signal_id=f"sig_{i}_{j}",
                        strategy_id="A2_CONFIRMED_PULLBACK",
                        symbol="BTC-EUR",
                        timestamp=datetime.now(UTC),
                        score=D(0),
                        data_quality="GOOD",
                        payload_json=json.dumps(
                            {
                                "data_kind": "SYNTHETIC_ACCEPTANCE",
                                "large_signal_evidence": "x" * 15000,
                            }
                        ),
                    )
                )
        await record_reconciliation(repo)
    monkeypatch.setenv("DATABASE_URL", lab.official.test_database_url)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("SHADOW_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "change-me")

    def browser():
        queries = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            queries.append(statement)

        with TestClient(create_app()) as client:
            assert client.get("/api/shadow/summary").status_code == 401
            auth = ("admin", "change-me")
            event.listen(Engine, "before_cursor_execute", capture)
            start = time.perf_counter()
            try:
                response = client.get("/api/shadow/summary", auth=auth)
            finally:
                event.remove(Engine, "before_cursor_execute", capture)
            elapsed = (time.perf_counter() - start) * 1000
            assert response.status_code == 200
            body = response.json()
            assert len(body["experiments"]) == 4 and all(
                e["reconciliation_status"]["status"] == "CONSISTENT" for e in body["experiments"]
            )
            assert all("history" not in e and "signals" not in e for e in body["experiments"])
            assert len(response.content) < 30000 and len(queries) < 130 and elapsed < 5000
            assert not any("FROM strategy_signals" in q for q in queries)
            original = client.get("/api/shadow", auth=auth)
            assert len(response.content) < len(original.content) / 10
            identity = body["experiments"][0]["experiment_id"]
            assert client.delete("/api/shadow/" + identity, auth=auth).status_code == 409
            assert client.get("/api/shadow/" + identity + "/view", auth=auth).status_code == 200
            assert (
                client.get(
                    "/api/shadow/" + identity + "/pages/fills?limit=101", auth=auth
                ).status_code
                == 422
            )
            assert client.get("/api/trades?view=open", auth=auth).json()["items"] == []
            assert (
                client.get("/api/overview/summary", auth=auth).json()["portfolio"]["equity"]
                == "500.000000000000"
            )
            assert client.get("/readyz").json()["live_trading_enabled"] is False
            return {
                "data_kind": "SYNTHETIC_ACCEPTANCE_LOCAL_PG",
                "accounts": 4,
                "seeded_signal_rows": 240,
                "before_bytes": len(original.content),
                "after_bytes": len(response.content),
                "after_elapsed_ms": elapsed,
                "after_sql_queries": len(queries),
                "production_reference": {
                    "shadow_bytes": 3074748,
                    "shadow_ms": 652,
                    "source": "User-supplied single bounded production sample; not comparable latency conditions.",
                },
            }

    evidence = await asyncio.to_thread(browser)
    (tmp_path/"api-benchmark.json").write_text(json.dumps(evidence, indent=2) + "\n")


async def test_pilot_started_under_test_replay_remains_synthetic_with_shadows_enabled(
    lab, monkeypatch, tmp_path
):
    from autotrader.config import get_settings
    from autotrader.persistence.pilot import pilot_configuration

    monkeypatch.setenv("DATABASE_URL", lab.official.test_database_url)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("SHADOW_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "change-me")
    monkeypatch.setenv("MARKET_DATA_REPLAY_FILE", str(tmp_path / "explicit-synthetic.json"))
    settings = get_settings()

    def start():
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/pilots",
                auth=("admin", "change-me"),
                json={"request_id": "v44-synthetic-pilot"},
            )
            assert response.status_code == 201
            result = response.json()
            assert result["mode"] == "SYNTHETIC_ACCEPTANCE"
            assert result["config"]["market_data_source"] == "synthetic-acceptance-replay"
            return result

    result = await asyncio.to_thread(start)
    await lab.official.capture_pilot_snapshot(
        test_environment=True, current_config=pilot_configuration(settings)
    )
    report = await lab.official.pilot_report(result["pilot_id"])
    assert report["observations"] > 0 and report["mode"] == "SYNTHETIC_ACCEPTANCE"
    assert not report["thirty_days_elapsed"]


async def test_feedback_keyset_and_stopped_official_control_are_independent_of_worker_health(
    lab, monkeypatch
):
    from autotrader.domain import utc_now

    stamp = utc_now()
    async with lab.official.session_factory() as session, session.begin():
        for i in range(73):
            session.add(
                SystemStateModel(
                    key=f"feedback:v44_{i:04}",
                    state="RECORDED",
                    reason="synthetic_test",
                    payload_json=json.dumps(
                        {
                            "decision_id": f"v44_{i:04}",
                            "symbol": "BTC-EUR",
                            "large_evidence": "x" * 15000,
                        }
                    ),
                    created_at=stamp,
                )
            )
        session.add(
            SystemStateModel(
                key="worker",
                state="RUNNING",
                reason="test_heartbeat",
                payload_json=json.dumps({"heartbeat": stamp.isoformat()}),
            )
        )
        session.add(
            SystemStateModel(
                key="scanner",
                state="OK",
                reason="test_scan",
                payload_json=json.dumps({"status": "OK", "candidates": [{"symbol": "BTC-EUR"}]}),
            )
        )
    await lab.official.set_control("stop")
    monkeypatch.setenv("DATABASE_URL", lab.official.test_database_url)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("SHADOW_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "change-me")

    def first_page():
        with TestClient(create_app()) as client:
            auth = ("admin", "change-me")
            health = client.get("/api/monitoring/summary", auth=auth).json()
            assert health["service"]["worker"] == "ok"
            assert health["market_data"]["fresh"] is True
            assert health["official"]["control"] == "STOPPED"
            assert health["current_system_errors"] == []
            result = client.get("/api/intelligence/summary?limit=17", auth=auth)
            assert result.status_code == 200 and len(result.content) < 15000
            assert (
                client.get("/api/intelligence/summary?cursor=invalid", auth=auth).status_code == 422
            )
            return result.json()

    first = await asyncio.to_thread(first_page)
    async with lab.official.session_factory() as session, session.begin():
        session.add(
            SystemStateModel(
                key="feedback:v44_0000_new",
                state="RECORDED",
                reason="later_insert",
                payload_json="{}",
            )
        )
    rows = first["feedback"]
    cursor = first["next_cursor"]
    while cursor:
        result = await page(lab.official, "feedback", 17, cursor)
        rows += [json.loads(r["payload_json"]) for r in result["items"]]
        cursor = result["next_cursor"]
    assert len(rows) == 73 and len({r["decision_id"] for r in rows}) == 73
    assert await lab.official.verify_invariants(D(500)) == []
