"""Complete retained-account backup sets and network-isolated restore proofs."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

RETAINED_IDS = frozenset({"9b18cabcc94c45fe84a59917226ebb58", "39cddc6d7e584a369ce223945f06e629",
    "52746de1116e4852b61cb16988917545", "2f12b0257a3b453a8e2a61ab695d8146",
    "40f3f37036f848d0a417b06b6a6fc201", "dc1edd63598e4caeb476864bee8851e3",
    "baac318a9797469c8f3693c042eb2855", "b97173b5abec41208c8541015d30003c"})
FINANCIAL_TABLES = ("accounts", "balances", "financial_journal", "orders", "fills", "positions",
    "capital_reservations", "exit_intents", "exit_targets", "exit_plans", "risk_periods", "cooldowns",
    "equity_snapshots", "ai_budgets", "ai_usage", "order_transitions", "risk_evaluations",
    "portfolio_snapshots", "market_marks")


def manifest_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_inventory(records: list[dict[str, Any]], *, required: frozenset[str] = RETAINED_IDS) -> None:
    identities = {r["account_id"].removeprefix("shadow:") for r in records if r["account_id"] != "paper-eur"}
    if not required <= identities or len(records) != len(identities) + 1:
        raise ValueError("incomplete_or_duplicate_financial_registry")
    if len({r["database"] for r in records}) != len(records):
        raise ValueError("duplicate_financial_database")
    if sum(r["account_id"] == "paper-eur" and r["database"] == "autotrader" for r in records) != 1:
        raise ValueError("official_financial_identity_mismatch")
    for record in records:
        if record["state"] not in {"OFFICIAL", "SHADOW_ACTIVE", "PAUSED", "STOPPED", "PAPER_EXPERIMENTAL_ACTIVE"}:
            raise ValueError("incomplete_shadow_provisioning")
        if record["account_id"] == "paper-eur":
            continue
        m = record["manifest"]
        if record["account_id"] == "PERSONAL_PLAN_PAPER_7000":
            if (not re.fullmatch(r"autotrader_paper_[a-f0-9]{32}", record["database"])
                or m["database_name"] != record["database"] or m["official_database"] != "autotrader"
                or m["account_id"] != record["account_id"] or m["initial_cash_eur"] != "7000"
                or m["currency"] != "EUR" or m["live_authorized"] is not False
                or manifest_hash(m) != record["manifest_hash"]):
                raise ValueError("primary_paper_registry_manifest_identity_mismatch")
            active = record.get('active_profile')
            if active and (active.get('account_origin') != m or manifest_hash(active) != record.get('active_profile_hash')):
                raise ValueError('primary_active_profile_identity_mismatch')
            continue
        if (not re.fullmatch(r"autotrader_shadow_[a-f0-9]{32}", record["database"])
            or m["database_name"] != record["database"] or m["official_database"] != "autotrader"
            or "shadow:" + m["experiment_id"] != record["account_id"]
            or manifest_hash(m) != record["manifest_hash"]):
            raise ValueError("shadow_registry_manifest_identity_mismatch")


def discover(dc: Any, *, required: frozenset[str] = RETAINED_IDS) -> list[dict[str, Any]]:
    def query(database: str, sql: str) -> Any:
        return json.loads(dc("exec", "-T", "postgres", "psql", "-U", "autotrader", "-d", database, "-Atc", sql))
    rows = query("autotrader", "SELECT COALESCE(json_agg(json_build_object('id',experiment_id,'database',database_name,'state',state,'manifest',manifest_json::json) ORDER BY experiment_id),'[]'::json) FROM shadow_experiments")
    archives = query("autotrader", "SELECT COALESCE(json_object_agg(key,payload_json::json),'{}'::json) FROM system_state WHERE key LIKE 'shadow_archive:%'")
    records = [{"database": "autotrader", "account_id": "paper-eur", "state": "OFFICIAL", "manifest": None, "manifest_hash": None, "archive": None}]
    records += [{"database": r["database"], "account_id": "shadow:" + r["id"], "state": r["state"],
                 "manifest": r["manifest"], "manifest_hash": manifest_hash(r["manifest"]),
                 "archive": archives.get("shadow_archive:" + r["id"])} for r in rows]
    primary = query("autotrader", "SELECT COALESCE(json_agg(json_build_object('state',state,'manifest',payload_json::json)),'[]'::json) FROM system_state WHERE key='personal_paper_v47'")
    records += [{"database": r["manifest"]["database_name"], "account_id": r["manifest"]["account_id"],
                 "state": r["state"], "manifest": r["manifest"], "manifest_hash": manifest_hash(r["manifest"]),
                 "archive": None} for r in primary]
    active = query('autotrader', "SELECT COALESCE(json_agg(json_build_object('pointer',a.payload_json::json,'profile',p.payload_json::json)),'[]'::json) FROM system_state a LEFT JOIN system_state p ON p.key=(a.payload_json::json->>'key') WHERE a.key='personal_paper_active_profile'")
    if active:
        if len(primary) != 1 or len(active) != 1 or not active[0]['profile']:
            raise ValueError('incomplete_primary_profile_registry')
        records[-1].update(active_profile=active[0]['profile'],active_profile_hash=active[0]['pointer']['hash'])
    validate_inventory(records, required=required)
    for record in records:
        accounts = query(record["database"], "SELECT COALESCE(json_agg(account_id),'[]'::json) FROM accounts")
        if accounts != [record["account_id"]]:
            raise ValueError("financial_account_identity_mismatch")
        if record["manifest"]:
            marker = query(record["database"], "SELECT json_build_object('manifest',manifest_json::json,'hash',manifest_hash) FROM shadow_identity WHERE singleton=1")
            if marker != {"manifest": record["manifest"], "hash": record["manifest_hash"]}:
                raise ValueError("retained_shadow_marker_mismatch")
    return records


def financial_seal(dc: Any, database: str) -> dict[str, Any]:
    result = {}
    for table in FINANCIAL_TABLES:
        query = "SELECT COALESCE(json_agg(to_jsonb(t)::text ORDER BY to_jsonb(t)::text),'[]'::json) FROM " + table + " t"
        rows = json.loads(dc("exec", "-T", "postgres", "psql", "-U", "autotrader", "-d", database, "-Atc", query))
        result[table] = {"rows": len(rows), "sha256": hashlib.sha256(b''.join(r.encode()+b'\n' for r in rows)).hexdigest()}
    return result


def backup_all(dc: Any, directory: Path, *, required: frozenset[str] = RETAINED_IDS) -> Path:
    records = discover(dc, required=required)
    destination = directory / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for record in records:
        record["financial_seal"] = financial_seal(dc, record["database"])
        data = dc("exec", "-T", "postgres", "pg_dump", "-U", "autotrader", "-Fc", record["database"])
        dc("exec", "-T", "postgres", "pg_restore", "--list", data=data)
        path = destination / (record["database"] + ".dump")
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        record.update(file=path.name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    if records != [{**r, **{k: prior[k] for k in ("file", "bytes", "sha256", "financial_seal")}} for r, prior in zip(discover(dc, required=required), records, strict=True)]:
        raise ValueError("registry_changed_during_backup")
    if any(financial_seal(dc, record["database"]) != record["financial_seal"] for record in records):
        raise ValueError("financial_state_changed_during_backup_stop_all_writers")
    manifest = destination / "backup-set.json"
    manifest.write_text(json.dumps({"schema": "financial-backup-set/2", "databases": records,
        "created_at": datetime.now(UTC).isoformat(), "required_identities": sorted(required)}, indent=2) + "\n")
    manifest.chmod(0o600)
    return manifest


def verify_archives(manifest: Path) -> dict[str, Any]:
    data = json.loads(manifest.read_text())
    validate_inventory(data["databases"])
    for record in data["databases"]:
        path = (manifest.parent / record["file"]).resolve()
        if path.parent != manifest.parent.resolve():
            raise ValueError("backup_path_outside_set")
        contents = path.read_bytes()
        if len(contents) != record["bytes"] or hashlib.sha256(contents).hexdigest() != record["sha256"]:
            raise ValueError("backup_checksum_mismatch")
    return data


def restore_isolated(manifest: Path, candidate_image: str, postgres_image: str,
                     rollback_image: str | None = None, *, exercise_backup: bool = False) -> dict[str, Any]:
    """Original DB names live in a fresh internal network; production has no route."""
    data = verify_archives(manifest)
    token = "autotrader-rc2-restore-" + uuid4().hex[:12]
    network, container = token + "-net", token + "-pg"
    def run(args: list[str], payload: bytes | None = None) -> bytes:
        result = subprocess.run(args, input=payload, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError("isolated_restore_command_failed: " + result.stderr.decode()[-1500:])
        return result.stdout
    created_network = created_container = False
    report: dict[str, Any] = {"evidence_class": "ISOLATED_PRODUCTION_DERIVED_CLONE",
        "source_backup_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "network": network, "container": container, "production_connections": False,
        "schema_migration": False, "synthetic_funding": False, "database_count": len(data["databases"])}
    try:
        run(["docker", "network", "create", "--internal", "--label", "autotrader.rc2.restore=" + token, network])
        created_network = True
        network_info = json.loads(run(["docker", "network", "inspect", network]))[0]
        if not network_info["Internal"]:
            raise ValueError("restore_network_has_external_route")
        report["network_internal"] = network_info["Internal"]
        report["candidate_image_id"] = run(["docker", "image", "inspect", "--format", "{{.Id}}", candidate_image]).decode().strip()
        report["rollback_image_id"] = run(["docker", "image", "inspect", "--format", "{{.Id}}", rollback_image]).decode().strip() if rollback_image else None
        report["backups"] = [{k: record.get(k) for k in ("account_id", "database", "manifest_hash", "sha256", "bytes")} for record in data["databases"]]
        run(["docker", "run", "-d", "--name", container, "--network", network, "--network-alias", "restore-postgres",
             "--label", "autotrader.rc2.restore=" + token, "--tmpfs", "/var/lib/postgresql/data",
             "-e", "POSTGRES_DB=postgres", "-e", "POSTGRES_USER=autotrader", "-e", "POSTGRES_HOST_AUTH_METHOD=trust", postgres_image])
        created_container = True
        for _ in range(60):
            if subprocess.run(["docker", "exec", container, "pg_isready", "-h", "127.0.0.1", "-U", "autotrader"], capture_output=True, check=False).returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("isolated_postgres_unavailable")
        for record in data["databases"]:
            payload = (manifest.parent / record["file"]).read_bytes()
            run(["docker", "exec", "-i", container, "pg_restore", "--list"], payload)
            run(["docker", "exec", container, "createdb", "-U", "autotrader", record["database"]])
            run(["docker", "exec", "-i", container, "pg_restore", "--exit-on-error", "--no-owner", "-U", "autotrader", "-d", record["database"]], payload)
        if exercise_backup:
            def isolated_dc(*parts: str, data: bytes | None = None) -> bytes:
                if len(parts) < 4 or parts[:3] != ("exec", "-T", "postgres"):
                    raise ValueError("isolated_backup_command_scope")
                return run(["docker", "exec", "-i", container, *parts[3:]], data)
            proof = backup_all(isolated_dc, manifest.parent/"isolated-backup-exercise")
            proof_data = verify_archives(proof)
            report["backup_discovery_exercise"] = {"status": "PASS", "databases": len(proof_data["databases"]),
                "backup_manifest_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
                "financial_seals": {r["account_id"]: r["financial_seal"] for r in proof_data["databases"]}}
        verifier = Path(__file__).with_name("verify_financial_set.py").resolve()
        def verify(image: str) -> dict[str, Any]:
            return json.loads(run(["docker", "run", "--rm", "--network", network, "--read-only", "--tmpfs", "/tmp",
                "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "DATABASE_URL=postgresql+asyncpg://autotrader@restore-postgres:5432/autotrader",
                "-e", "LIVE_TRADING_ENABLED=false", "-e", "AUTOTRADER_ISOLATED_RESTORE=1",
                "-v", str(verifier) + ":/verify.py:ro", "-v", str(manifest.resolve()) + ":/backup-set.json:ro",
                image, "python", "/verify.py"]))
        report["candidate"] = verify(candidate_image)
        if exercise_backup and {a["account_id"]: a["financial_seal"] for a in report["candidate"]["accounts"]} != report["backup_discovery_exercise"]["financial_seals"]:
            raise ValueError("isolated_backup_financial_seal_mismatch")
        if rollback_image:
            report["rollback"] = verify(rollback_image)
            if [a["financial_seal"] for a in report["candidate"]["accounts"]] != [a["financial_seal"] for a in report["rollback"]["accounts"]]:
                raise ValueError("rollback_changed_financial_history")
        report["status"] = "PASS"
    except Exception:
        # Retain only the scoped failing clone/network for diagnosis; never erase evidence.
        report["status"] = "FAILED_DIAGNOSTIC_CLONE_RETAINED"
        raise
    finally:
        manifest.with_name("restore-" + token + ".json").write_text(json.dumps(report, indent=2) + "\n")
        if report.get("status") == "PASS":
            if created_container:
                run(["docker", "rm", "-f", container])
            if created_network:
                run(["docker", "network", "rm", network])
    return report
