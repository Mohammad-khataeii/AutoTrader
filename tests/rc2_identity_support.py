"""Production-identical manifests inside an owned test cluster with a deny-by-default socket guard."""
import asyncio
import json
import os
import socket
import subprocess
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from autotrader.config import Settings
from autotrader.persistence.database import create_schema, make_engine, make_session_factory
from autotrader.persistence.models import (
    ShadowExperimentModel,
    ShadowIdentityModel,
    SystemStateModel,
)
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.shadow.lab import ShadowLab
from autotrader.shadow.repository import ShadowScope, ShadowTradingRepository


async def identity_fixture(monkeypatch):
    token = "autotrader-rc2-identity-" + uuid4().hex[:12]
    def run(*args, data=None):
        return subprocess.check_output(["docker", *args], input=data, stderr=subprocess.PIPE)
    run("network", "create", "--opt", "com.docker.network.bridge.enable_ip_masquerade=false", token)
    engine = lab = None
    try:
        run("run", "-d", "--name", token, "--network", token, "--tmpfs", "/var/lib/postgresql/data",
            "-p", "127.0.0.1::5432", "-e", "POSTGRES_DB=autotrader", "-e", "POSTGRES_USER=autotrader",
            "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:16-alpine")
        for _ in range(60):
            if (await asyncio.to_thread(subprocess.run, ["docker", "exec", token, "pg_isready", "-U", "autotrader"], capture_output=True, check=False)).returncode == 0:
                break
            await asyncio.sleep(.25)
        port = json.loads(run("inspect", token))[0]["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        # Host-side acceptance additionally refuses every non-loopback socket.
        connect = socket.socket.connect
        def local_only(sock, address):
            if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1"}:
                raise RuntimeError("acceptance_outbound_network_refused")
            return connect(sock, address)
        monkeypatch.setattr(socket.socket, "connect", local_only)
        settings = Settings(database_url=f"postgresql+asyncpg://autotrader@127.0.0.1:{port}/autotrader",
                            environment="local", shadow_enabled=True, _env_file=None)
        engine = make_engine(settings)
        await create_schema(engine)
        official = PersistentTradingRepository(make_session_factory(engine))
        await official.initialize_portfolio(Decimal(500))
        official.test_database_url = settings.database_url
        lab = ShadowLab(official, settings)
        inventory = json.loads(Path("docs/evidence/v4_5_rc2/production-before.json").read_text())
        for record in inventory["accounts"]:
            manifest = record["manifest"]
            if manifest is None:
                continue
            run("exec", token, "createdb", "-U", "autotrader", manifest["database_name"])
            scoped = settings.model_copy(update={"database_url": settings.database_url.rsplit("/", 1)[0] + "/" + manifest["database_name"]})
            child_engine = make_engine(scoped)
            try:
                await create_schema(child_engine)
                factory = make_session_factory(child_engine)
                async with factory() as session, session.begin():
                    session.add(ShadowIdentityModel(singleton=1, manifest_hash=record["manifest_hash"], manifest_json=json.dumps(manifest)))
                repo = ShadowTradingRepository(factory, ShadowScope(manifest["database_name"], json.dumps(manifest)))
                await repo.initialize_portfolio(Decimal(500))
            finally:
                await child_engine.dispose()
            async with official.session_factory() as session, session.begin():
                session.add(ShadowExperimentModel(experiment_id=record["identity"], request_id="isolated-" + record["identity"],
                    name="SYNTHETIC identity acceptance", state=record["state"], database_name=manifest["database_name"], manifest_json=json.dumps(manifest)))
                if record["archive"]:
                    session.add(SystemStateModel(key="shadow_archive:" + record["identity"], state="ARCHIVED", reason="copied_identity_fixture", payload_json=json.dumps(record["archive"])))
        yield lab
        async with official.session_factory() as session:
            assert await session.scalar(text("SELECT count(*) FROM financial_journal WHERE event_type='INITIAL_FUNDING'")) == 1
    finally:
        if lab:
            await lab.close()
        if engine:
            await engine.dispose()
        # Scoped ephemeral container only; no Docker volume or unrelated project operations.
        await asyncio.to_thread(subprocess.run, ["docker", "rm", "-f", token], capture_output=True, check=False)
        await asyncio.to_thread(subprocess.run, ["docker", "network", "rm", token], capture_output=True, check=False)


def evidence(name, payload):
    root = os.environ.get("AUTOTRADER_RC2_EVIDENCE")
    if root:
        destination = Path(root)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / name).write_text(json.dumps({"evidence_class": "SYNTHETIC_DETERMINISTIC_ENGINEERING_TEST",
            **payload}, indent=2, default=str) + "\n")
