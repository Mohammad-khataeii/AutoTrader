"""Offline deployment model, SQLite backup and rollback scope checks."""

import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from deploy.stockswatch import scoped_release as release

from stockswatch import storage


def model_fixture(tmp_path):
    net = "test-existing-application-network"
    container = {
        "HostConfig": {
            "SecurityOpt": ["no-new-privileges:true"],
            "Memory": 134217728,
            "NanoCpus": 500000000,
        },
        "NetworkSettings": {"Networks": {net: {"Aliases": ["original-service-alias"]}}},
    }
    plan = {
        "images": {"stockswatch": "sha256:" + "a" * 64, "frontend": "sha256:" + "b" * 64},
        "net_ids": {net: "network-id"},
        "data": str(tmp_path),
    }
    return plan, container


def test_scoped_compose_ignores_shared_environment(tmp_path):
    plan, container = model_fixture(tmp_path)
    runtime = tmp_path / "runtime.env"
    runtime.write_text("STOCKSWATCH_ALPACA_PAPER_SECRET=offline-mock-${UNRELATED_UNSET}\n")
    (tmp_path / "empty.env").write_text("")
    for orders in (False, True):
        model = release.compose_model(plan, container, container, tmp_path, orders)
        assert set(model["services"]) == {"stockswatch", "frontend"}
        assert model["services"]["frontend"]["ports"] == ["127.0.0.1:13000:80"]
        sw = model["services"]["stockswatch"]
        assert sw["environment"]["STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS"] == str(int(orders))
        assert sw["volumes"][0]["bind"]["create_host_path"] is False
        assert model["networks"]["net0"] == {
            "external": True,
            "name": "test-existing-application-network",
        }
        assert sw["networks"]["net0"]["aliases"] == ["original-service-alias", "stockswatch"]
        if shutil.which("docker"):
            config = tmp_path / "compose.json"
            config.write_text(json.dumps(model))
            env = {
                k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "SYSTEMROOT"}
            }
            probe = subprocess.run(
                ["docker", "compose", "version"],
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            if probe.returncode:
                pytest.skip("Docker Compose plugin unavailable")
            validate = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--project-directory",
                    str(tmp_path),
                    "--env-file",
                    str(tmp_path / "empty.env"),
                    "-f",
                    str(config),
                    "config",
                    "--format",
                    "json",
                ],
                env=env,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            assert validate.returncode == 0, validate.stderr
            rendered = json.loads(validate.stdout)
            secret = rendered["services"]["stockswatch"]["environment"][
                "STOCKSWATCH_ALPACA_PAPER_SECRET"
            ]
            assert secret.replace("$$", "$") == "offline-mock-${UNRELATED_UNSET}"
            assert "not set" not in validate.stderr


def test_online_backup_verifies_and_retains_pending_orders(tmp_path, monkeypatch):
    db = tmp_path / Path(release.DB).name
    monkeypatch.setattr(storage, "DB_PATH", str(db))
    storage.init()
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO pending_orders VALUES (?,?,?,?,?,?,?,?)",
            ("legacy1", "AAPL", "BUY", "2026-11-05", "{}", "2026-11-06", "PENDING", None),
        )
    destination = tmp_path / "restored.sqlite3"
    result = release.backup(tmp_path, destination)
    assert result["sqlite_sha256"] == release.digest(destination)
    with release.open_readonly(destination) as c:
        assert c.execute("SELECT id,state FROM pending_orders").fetchall() == [
            ("legacy1", "PENDING")
        ]
    with sqlite3.connect(db) as c:
        c.execute("UPDATE portfolio SET cash=1")
    with pytest.raises(RuntimeError, match="legacy_ledger_reconciliation_failed"):
        release.backup(tmp_path, tmp_path / "bad.sqlite3")


def test_private_env_requires_scoped_credentials_and_preserves_optional_values(tmp_path):
    source = tmp_path / "operator.env"
    source.write_text("".join(f"{key}=offline-value\n" for key in sorted(release.REQUIRED)))
    source.chmod(0o600)
    old = {"Config": {"Env": ["POSTGRES_PASSWORD=do-not-copy", "STOCKSWATCH_TICK_SECONDS=900"]}}
    env = release.runtime_env(source, old)
    assert set(env) == release.REQUIRED | {"STOCKSWATCH_TICK_SECONDS"}
    with source.open("a") as file:
        file.write("STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS=1\n")
    with pytest.raises(RuntimeError, match="invalid_runtime_env_line"):
        release.runtime_env(source, old)


def test_rollback_only_stops_scoped_containers_and_restores_original_frontend(monkeypatch):
    plan = {
        "targets": {"stockswatch": {"id": "original-stock"}, "frontend": {"id": "original-front"}}
    }
    commands = []
    monkeypatch.setattr(
        release,
        "scoped_containers",
        lambda _: {
            name: {"Id": f"scoped-{name}", "State": {"Running": True}} for name in release.TARGETS
        },
    )
    monkeypatch.setattr(release, "inspect", lambda *_: {"State": {"Running": False}})
    monkeypatch.setattr(release, "verify_peers", lambda _: None)
    monkeypatch.setattr(release, "run", lambda *cmd, **_: commands.append(cmd))
    release.rollback(plan)
    assert commands == [
        ("docker", "stop", "--time", "180", "scoped-stockswatch"),
        ("docker", "stop", "--time", "20", "scoped-frontend"),
        ("docker", "start", "original-front"),
    ]
