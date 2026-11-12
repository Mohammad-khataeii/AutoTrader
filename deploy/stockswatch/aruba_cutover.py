"""Verified StocksWatch-only cutover on the existing Aruba paper deployment."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
from urllib.error import HTTPError
from urllib.request import urlopen

PROJECT = "autotrader-aruba-stockswatch"
STAGING = Path("/opt/personal-plan/staging")
DATA_TARGET = "/stockswatch-data"
MODULE_TARGET = "/opt/stockswatch/stockswatch/"
PYTHON = "/opt/stockswatch/venv/bin/python"
DB = "stockswatch.sqlite3"
FLAT_PROBE = """
from stockswatch.alpaca_paper import PaperClient, broker_mode
from stockswatch.alpaca_crypto_paper import CryptoPaperClient
from stockswatch.storage import DB_PATH
from pathlib import Path
from contextlib import closing
import sqlite3
assert broker_mode()
with PaperClient(retry_reads=True) as client:
    stocks = client.snapshot()
with CryptoPaperClient() as client:
    crypto = client.snapshot()
counts = {key: len(stocks[key]) for key in
          ("positions", "open_orders", "other_positions", "other_open_orders")}
counts.update({f"crypto_account_{k}": len(crypto[k]) for k in
               ("positions", "orders", "other_positions", "other_open_orders")})
with closing(sqlite3.connect(Path(DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)) as db:
    db.execute("PRAGMA temp_store=MEMORY")
    db.execute("PRAGMA query_only=ON")
    for table in ("sw_alpaca_intents", "ac_intents"):
        counts[table] = db.execute(f"SELECT COUNT(*) FROM {table} "
                                   "WHERE state IN ('PREPARED','UNKNOWN','ACKNOWLEDGED')").fetchone()[0]
print(json.dumps(counts, sort_keys=True))
"""
RUNTIME_FILES = """
import hashlib, json
from pathlib import Path
p = Path('/opt/stockswatch/stockswatch')
print(json.dumps({x.name: hashlib.sha256(x.read_bytes()).hexdigest()
                  for x in p.iterdir() if x.suffix == '.py' or x.name == 'research_evidence.json'}))
"""


def require(test, message):
    if not test:
        raise RuntimeError(message)


def sha(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def cmd(*args, timeout=120):
    # Docker Compose can mention env values in its diagnostics. Retain only exit codes.
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    require(p.returncode == 0, f"{args[0]} {args[1]} failed ({p.returncode})")
    return p.stdout.strip()


def inspect(container):
    return json.loads(cmd("docker", "container", "inspect", container))[0]


def scoped(service, *, running=True):
    args = ["docker", "ps", "--no-trunc", "-q"]
    if not running:
        args.append("-a")
    ids = cmd(*args, "--filter", f"label=com.docker.compose.project={PROJECT}",
              "--filter", f"label=com.docker.compose.service={service}").splitlines()
    require(len(ids) == 1, f"expected exactly one scoped {service} container")
    return inspect(ids[0])


def env_map(container):
    return dict(entry.split("=", 1) for entry in container["Config"]["Env"])


def compose_command(stock):
    labels = stock["Config"]["Labels"]
    work = Path(labels["com.docker.compose.project.working_dir"])
    files = [Path(name) for name in labels["com.docker.compose.project.config_files"].split(",")]
    require(work.is_dir() and work.resolve().is_relative_to(STAGING), "unexpected Compose working directory")
    require(all(path.is_absolute() and path.is_file() for path in files), "missing active Compose file")
    base = ["docker", "compose", "--project-directory", str(work), "-p", PROJECT]
    for path in files:
        base.extend(("-f", str(path)))
    return base


def frontend_health():
    with urlopen("http://127.0.0.1:13000/healthz", timeout=5) as reply:
        require(reply.status == 200, "scoped frontend health failed")
    try:
        with urlopen("http://127.0.0.1:13000/api/stockswatch/status", timeout=5):
            raise RuntimeError("unauthenticated StocksWatch proxy unexpectedly granted access")
    except HTTPError as exc:
        require(exc.code == 401, "StocksWatch proxy failed authenticated-route check")


def broker_flat(stock):
    counts = json.loads(cmd("docker", "exec", stock["Id"], PYTHON, "-c",
                            "import json\n" + FLAT_PROBE, timeout=90))
    print(f"Paper exposure and unresolved intent counts {json.dumps(counts)}", flush=True)
    require(not any(counts.values()), "cutover deferred until both paper accounts and intent journals are clear")


def preflight():
    require(not os.getenv("DOCKER_HOST") and not os.getenv("DOCKER_CONTEXT"), "expected local Docker")
    require(cmd("docker", "info", "--format", "{{.OSType}}/{{.Architecture}}") == "linux/x86_64",
            "expected Linux AMD64 Docker on Aruba")
    stock, frontend = scoped("stockswatch"), scoped("frontend")
    require(frontend["State"]["Health"]["Status"] == "healthy", "scoped frontend unhealthy")
    port = frontend["NetworkSettings"]["Ports"].get("80/tcp")
    require(port == [{"HostIp": "127.0.0.1", "HostPort": "13000"}], "unexpected frontend port binding")
    require(stock["HostConfig"]["ReadonlyRootfs"], "expected read-only StocksWatch root")
    current = env_map(stock)
    require(current.get("STOCKSWATCH_DB", DATA_TARGET + "/" + DB) == DATA_TARGET + "/" + DB
            and current.get("STOCKSWATCH_EXECUTION_BACKEND") == "alpaca_paper",
            "unexpected database or execution backend")
    mounts = stock["Mounts"]
    data = [Path(m["Source"]).resolve() for m in mounts
            if m["Type"] == "bind" and m["Destination"] == DATA_TARGET and m["RW"]]
    require(len(data) == 1 and data[0].is_relative_to(STAGING) and (data[0] / DB).is_file(),
            "existing staged ledger mount missing")
    require(all(m["Destination"] == DATA_TARGET or
                (m["Type"] == "bind" and not m["RW"] and
                 re.fullmatch(r"/opt/stockswatch/stockswatch/[a-z_]+\.py", m["Destination"]))
                for m in mounts), "unexpected live mount")
    print(f"Scoped StocksWatch health {stock['State'].get('Health', {}).get('Status', 'unknown')}",
          flush=True)
    base = compose_command(stock)
    compose = json.loads(cmd(*base, "config", "--format", "json"))
    require(set(compose["services"]) == {"stockswatch", "frontend"}, "unexpected Compose services")
    model = compose["services"]["stockswatch"]
    require(all(current.get(k) == str(v) for k, v in model["environment"].items()),
            "existing Compose environment differs from the running worker")
    broker_flat(stock)
    frontend_health()
    return stock, frontend, data[0], base, model


def verify_bundle(directory, commit):
    record = json.loads((directory / "release.json").read_text())
    require(re.fullmatch("[0-9a-f]{40}", commit) and record["commit"] == commit,
            "expected exact reviewed release commit")
    require(sha(directory / "source.tar.gz") == record["source_archive_sha256"] and
            sha(directory / "image.tar.gz") == record["image_archive_sha256"],
            "reviewed release archive mismatch")
    require(re.fullmatch("sha256:[0-9a-f]{64}", record["image_id"]), "image ID missing")
    with tarfile.open(directory / "source.tar.gz") as archive:
        manifest = archive.extractfile("release-manifest.json").read()
    require(hashlib.sha256(manifest).hexdigest() == record["manifest_sha256"],
            "reviewed source manifest mismatch")
    files = json.loads(manifest)
    require(files["commit"] == commit and all(
        sha(Path("deploy/stockswatch") / name) == files["files"][f"deploy/stockswatch/{name}"]
        for name in ("aruba_cutover.py", "deploy_aruba.sh")
    ), "local deployment scripts differ from the reviewed release")
    print(record["source_archive_sha256"], record["image_archive_sha256"], record["image_id"])


def wait_healthy(frontend_id, image_id):
    for _ in range(40):
        current = scoped("stockswatch", running=False)
        require(current["Image"] == image_id, "unexpected StocksWatch runtime image")
        require(current["State"]["Status"] not in ("dead", "exited"), "StocksWatch stopped")
        if current["State"].get("Health", {}).get("Status") == "healthy":
            require(scoped("frontend")["Id"] == frontend_id, "scoped frontend was recreated")
            frontend_health()
            return current
        time.sleep(3)
    raise RuntimeError("StocksWatch health did not recover within 120 seconds")


def deploy(state, commit, source_sha, image_sha, image_id):
    require(state.is_dir() and state.resolve().parent == STAGING / "integrations" and
            state.name.startswith(f"stockswatch-{commit[:12]}."), "unexpected release state")
    require(re.fullmatch("[0-9a-f]{40}", commit)
            and re.fullmatch("sha256:[0-9a-f]{64}", image_id), "invalid release identity")
    require(sha(state / "source.tar.gz") == source_sha and sha(state / "image.tar.gz") == image_sha,
            "uploaded archive failed hash verification")
    source = state / "source"
    source.mkdir()
    with tarfile.open(state / "source.tar.gz") as archive:
        archive.extractall(source, filter="data")
    sys.path.insert(0, str(source))
    from deploy.release import verify_source_release
    from deploy.stockswatch.scoped_release import backup, open_readonly, verified_ledger
    manifest = source / "release-manifest.json"
    verify_source_release(source, manifest, commit)
    record = json.loads(manifest.read_text())
    module_hashes = {Path(name).name: digest for name, digest in record["files"].items()
                     if name.startswith("stockswatch/")}

    with (STAGING / "integrations" / ".stockswatch-cutover.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stock, frontend, data, base, old_model = preflight()
        docker_root = Path(cmd("docker", "info", "--format", "{{.DockerRootDir}}"))
        require(shutil.disk_usage(docker_root).free >= 2 * 1024**3, "insufficient Docker image space")
        require(shutil.disk_usage(state).free >= 3 * (data / DB).stat().st_size + 512 * 1024**2,
                "insufficient SQLite backup and verification space")
        cmd("docker", "load", "--input", str(state / "image.tar.gz"), timeout=600)
        image = json.loads(cmd("docker", "image", "inspect", image_id))[0]
        require(image["Architecture"] == "amd64" and image["Os"] == "linux"
                and image["Config"]["Labels"].get("org.opencontainers.image.revision") == commit,
                "loaded image platform or revision mismatch")
        args = ("docker", "run", "--rm", "--network", "none", "--read-only")
        require(json.loads(cmd(*args, image_id, PYTHON, "-c", RUNTIME_FILES)) == module_hashes,
                "loaded image module hashes differ from the source manifest")

        # Compose's override replaces the inherited historical source binds.
        # The verified image owns all module bytes. The original data bind stays in place.
        override = state / "release.override.yml"
        override.write_text(
            f'services:\n  stockswatch:\n    image: "{image_id}"\n'
            f'    volumes: !override\n      - type: bind\n        source: "{data}"\n'
            f'        target: {DATA_TARGET}\n        bind:\n          create_host_path: false\n'
        )
        candidate = [*base, "-f", str(override)]
        rendered = json.loads(cmd(*candidate, "config", "--format", "json"))
        model = rendered["services"]["stockswatch"]
        require(set(rendered["services"]) == {"stockswatch", "frontend"} and
                model["image"] == image_id and len(model["volumes"]) == 1 and
                model["volumes"][0]["source"] == str(data) and
                all(model.get(k) == old_model.get(k) for k in old_model if k not in ("image", "volumes")),
                "unexpected Compose changes outside the image and source binds")

        # Keep the old canonical image reachable even if another tag later moves.
        rollback_tag = f"local/stockswatch-aruba-rollback:{commit}"
        cmd("docker", "tag", stock["Image"], rollback_tag)
        prior = state / "rollback-image.override.json"
        prior.write_text(json.dumps({"services": {"stockswatch": {"image": stock["Image"]}}}))
        rollback = [*base, "-f", str(prior)]
        cmd(*rollback, "config", "--quiet")
        rollback_sources = {Path(m["Source"]): sha(Path(m["Source"])) for m in stock["Mounts"]
                            if m["Destination"] != DATA_TARGET}
        first = backup(data, state / "online.sqlite3")
        verify = state / "isolated-restore.sqlite3"
        shutil.copyfile(state / "online.sqlite3", verify)
        # A frozen standalone backup needs no WAL sidecar or writable parent.
        from contextlib import closing
        with closing(sqlite3.connect(verify)) as isolated:
            require(isolated.execute("PRAGMA journal_mode=DELETE").fetchone() == ("delete",),
                    "could not open the isolated restored database without WAL")
            require(verified_ledger(isolated) == first["financial_tables"],
                    "isolated restore did not reconcile")
        cmd(*args, "--user", "0", "--mount", f"type=bind,src={verify},dst=/verified.sqlite3,readonly",
            image_id, PYTHON, "-c", """
from stockswatch.app import app
from stockswatch.storage import connect_readonly
with connect_readonly('/verified.sqlite3') as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert db.execute('SELECT COUNT(*) FROM assets WHERE enabled=1').fetchone()[0] == 102
    db.execute('SELECT action,COUNT(*) FROM sw_intraday_observations GROUP BY action').fetchall()
""", timeout=180)

        def extended_fingerprint(path):
            with open_readonly(path) as db:
                db.execute("PRAGMA query_only=ON")
                db.execute("PRAGMA temp_store=MEMORY")
                db.execute("BEGIN")
                proof = verified_ledger(db)
                for table in ("sw_alpaca_intents", "sw_alpaca_state", "sw_protection",
                              "sw_oco_exit_requests", "sw_intraday_fills", "sw_intraday_fill_costs",
                              "ac_intents", "ac_managed"):
                    values = db.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
                    proof[table] = hashlib.sha256(repr(values).encode()).hexdigest()
                return proof

        require(scoped("stockswatch")["Id"] == stock["Id"], "StocksWatch changed during preparation")
        before_stop = extended_fingerprint(data / DB)
        broker_flat(stock)
        receipt = {"commit": commit, "image_id": image_id, "previous_image_id": stock["Image"],
                   "source_archive_sha256": source_sha, "image_archive_sha256": image_sha,
                   "manifest_sha256": sha(manifest), "online_backup": first}
        (state / "receipt.json").write_text(json.dumps(receipt, indent=2))
        frozen = None
        try:
            cmd(*base, "stop", "-t", "180", "stockswatch", timeout=210)
            require(not inspect(stock["Id"])["State"]["Running"], "old writer is still running")
            cutover = state / "cutover.sqlite3"
            receipt["cutover_backup"] = backup(data, cutover)
            frozen = extended_fingerprint(cutover)
            require(extended_fingerprint(data / DB) == frozen, "cutover reconciliation failed")
            require(frozen == before_stop, "financial state changed during cutover; retry after reconciliation")
            receipt["financial_fingerprints"] = frozen
            (state / "receipt.json").write_text(json.dumps(receipt, indent=2))
            cmd(*candidate, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "stockswatch")
            active = wait_healthy(frontend["Id"], image_id)
            require(json.loads(cmd("docker", "exec", active["Id"], PYTHON, "-c", RUNTIME_FILES))
                    == module_hashes, "running module identity mismatch")
            require(len(active["Mounts"]) == 1 and active["Mounts"][0]["Source"] == str(data),
                    "running ledger mount differs")
            require(all(env_map(active).get(k) == str(v) for k, v in old_model["environment"].items()),
                    "paper runtime settings changed")
            cmd("docker", "exec", active["Id"], PYTHON, "-c",
                "from stockswatch.alpaca_paper import PaperClient; "
                "from stockswatch.alpaca_crypto_paper import CryptoPaperClient; "
                "exec('with PaperClient(retry_reads=True) as c: c.snapshot()\\n"
                "with CryptoPaperClient() as c: c.snapshot()')", timeout=90)
            print(f"Healthy scoped StocksWatch release {commit}. Evidence and backups in {state}")
        except Exception:
            print(f"Cutover failed. Preserve diagnostics in {state}; the ledger is never restored in place.",
                  file=sys.stderr)
            # Restore the original worker only if no broker/financial state could be lost.
            # If state cannot be verified, preserve the stopped worker and evidence for review.
            try:
                current = scoped("stockswatch", running=False)
                (state / "failed-runtime.json").write_text(json.dumps({
                    "id": current["Id"], "image": current["Image"],
                    "state": current["State"],
                }, indent=2))
                if current["Image"] == image_id:
                    if current["State"]["Running"]:
                        cmd(*candidate, "stop", "-t", "180", "stockswatch", timeout=210)
                    if (frozen is not None and extended_fingerprint(data / DB) == frozen
                            and all(sha(path) == value for path, value in rollback_sources.items())):
                        cmd(*rollback, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "stockswatch")
                        wait_healthy(frontend["Id"], stock["Image"])
                elif current["Id"] == stock["Id"] and not current["State"]["Running"]:
                    cmd("docker", "start", stock["Id"])
            except Exception as recovery_error:
                print(f"Scoped rollback needs operator review ({type(recovery_error).__name__}).",
                      file=sys.stderr)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--preflight", action="store_true")
    modes.add_argument("--verify-bundle", nargs=2)
    modes.add_argument("--deploy", nargs=5)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.preflight:
            preflight()
            print("Read-only Aruba preflight passed")
        elif args.verify_bundle:
            directory, commit = args.verify_bundle
            verify_bundle(Path(directory), commit)
        else:
            state, *identity = args.deploy
            deploy(Path(state), *identity)
    except RuntimeError as exc:
        parser.exit(1, f"{exc}\n")
    except Exception as exc:
        parser.exit(1, f"{type(exc).__name__}; see the protected release state for recorded evidence\n")


if __name__ == "__main__":
    main()
