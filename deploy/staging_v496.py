"""Approved exact-commit replacement of the Aruba paper staging application."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import sys
import tarfile
import time
from pathlib import Path

from release import verify_source_release
from staging_v49 import BASE, CORE, PROJECT, check_config, dc, flat_portfolio, inventory, run, save, verify_private_access
from staging_v495 import PROFILE, LEDGERS, api, compare_financial_backups, same_controls, selected_controls

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.9.6-rc.1"
LAB = "perpetuals-worker"
GATES = {"backend-tests.json", "frontend-tests.json", "linux-amd64-tests.json",
         "perpetuals-accounting-and-restart.json", "financial-restore.json", "rollback-readiness.json"}
PERP_TABLES = {"paper_perp_state", "paper_perp_events", "paper_perp_schema_version"}


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def require_readiness(manifest: dict, incoming: Path) -> None:
    folder = incoming / "reviewed"
    path = folder / "staging-readiness.json"
    if not path.is_file():
        raise ValueError("No reviewed engineering evidence; activation blocked")
    readiness = json.loads(path.read_text())
    if (readiness.get("status"), readiness.get("commit"), readiness.get("source_fingerprint")) != (
        "PASS", manifest["commit"], manifest["source_fingerprint"],
    ) or not GATES.issubset(readiness.get("gates", {})):
        raise ValueError("Release readiness is incomplete or belongs to different source")
    for name, digest in readiness["gates"].items():
        if Path(name).name != name or sha(folder / name) != digest:
            raise ValueError("Release evidence hash mismatch")
        report = json.loads((folder / name).read_text())
        if (report.get("status"), report.get("commit"), report.get("source_fingerprint")) != (
            "PASS", manifest["commit"], manifest["source_fingerprint"],
        ):
            raise ValueError("Unverified or unrelated release evidence")


def bound_images(manifest: dict, incoming: Path) -> dict:
    binding = json.loads((incoming / "binding.json").read_text())
    commit = manifest["commit"]
    if (binding["commit"] != commit
            or binding["manifest_sha256"] != sha(ROOT / "release-manifest.json")
            or binding["source_sha256"] != sha(incoming / "source.tar.gz")
            or binding["images_sha256"] != sha(incoming / "images.tar.gz")):
        raise ValueError("Immutable source/image binding mismatch")
    images = {}
    with tarfile.open(incoming / "images.tar.gz", "r:gz") as archive:
        rows = json.load(archive.extractfile("manifest.json"))
        for role in ("app", "frontend"):
            tag = f"autotrader-{role}:{commit}"
            matches = [r for r in rows if tag in (r["RepoTags"] or [])]
            if len(matches) != 1:
                raise ValueError("Candidate image tag missing or ambiguous in archive")
            config = archive.extractfile(matches[0]["Config"]).read()
            canonical = "sha256:" + hashlib.sha256(config).hexdigest()
            if canonical != binding[role]:
                raise ValueError("Canonical image configuration digest mismatch")
            info = json.loads(run(["docker", "image", "inspect", tag]))[0]
            # Legacy storage reports config as Id; containerd may report manifest as Id.
            descriptor = info.get("Descriptor") or {}
            loaded_config = (descriptor.get("annotations") or {}).get("config.digest", info["Id"])
            if (loaded_config, info["Os"], info["Architecture"],
                (info["Config"].get("Labels") or {}).get("org.opencontainers.image.revision")) != (
                canonical, "linux", "amd64", commit,
            ) or not re.fullmatch("sha256:[a-f0-9]{64}", info["Id"]):
                raise ValueError("Loaded image identity, platform or revision mismatch")
            images[role] = info["Id"]
    expected = {n.removeprefix("src/autotrader/"): v for n, v in manifest["files"].items()
                if n.startswith("src/autotrader/") and n.endswith(".py")}
    script = ("import hashlib,json,autotrader;from pathlib import Path;"
              "p=Path(autotrader.__file__).parent;"
              "print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() "
              "for f in p.rglob('*.py')}))")
    actual = json.loads(run(["docker", "run", "--rm", "--network", "none", "--read-only",
                             images["app"], "python", "-c", script]))
    if actual != expected:
        raise ValueError("Installed app source does not match release")
    return images


def financial_state(*, require_flat: bool) -> dict:
    p = api("/api/personal-paper")
    official = api("/api/overview/summary")["portfolio"]
    system = api("/api/system")
    official["pending_orders"] = system["pending_intents"]
    controls = api("/api/intelligence/competition")["experiments"]
    selected_controls(controls)
    if (len(controls) != 15 or p.get("reconciliation") != []
            or system.get("reconciliation", {}).get("problems") != []
            or not p.get("runtime_matches") or p["manifest"]["version"] != PROFILE):
        raise ValueError("Existing account/profile or reconciliation check failed")
    portfolios = {"official": official, "personal": p["portfolio"],
                  **{r["experiment_id"]: r["portfolio"] for r in controls}}
    if require_flat and any(a["control"] not in {"PAUSED", "STOPPED"} or not flat_portfolio(a)
                            for a in portfolios.values()):
        raise ValueError("Pause entries and let all spot accounts become flat before cutover")
    return portfolios


def require_perpetuals_flat() -> None:
    # A previous recovery may have kept the lab tables even if the old UI
    # cannot show them. Verify retained exposure directly before any cutover.
    if inventory()["services"].get(LAB, {}).get("state") == "running":
        raise ValueError("An existing perpetuals worker is running; verify and defer replacement")
    command = ("exec", "-T", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1",
               "-U", "autotrader", "-d", "autotrader_aruba_staging", "-Atc")
    relation = dc(*command, "SELECT to_regclass('public.paper_perp_state')").decode().strip()
    if not relation:
        return
    raw = dc(*command, "SELECT COALESCE(payload, 'null') FROM public.paper_perp_state WHERE id=1")
    state = json.loads(raw)
    if state is not None and (state.get("entries_enabled") is not False or state.get("pending")
                              or any(a["position"] for a in state["accounts"])):
        raise ValueError("Retained perpetuals are armed or open; keep protection and defer")


def backup(images: dict) -> dict:
    proof = json.loads(run([sys.executable, str(ROOT / "deploy/staging_backup.py"),
                            "--restore-test", "--candidate-image", images["app"]]))
    if proof.get("accounts") != 17 or proof.get("restore", {}).get("status") != "PASS":
        raise ValueError("All 17 retained ledger restores must reconcile")
    return proof


def verify(images: dict, *, require_flat: bool) -> dict:
    current = inventory()["services"]
    for service in (*CORE, LAB):
        expected = images["frontend" if service == "frontend" else "app"]
        if current[service]["image"] != expected or current[service]["state"] != "running":
            raise ValueError("Candidate service is missing or has the wrong image")
    for service in ("backend", "worker", "frontend", "postgres", "redis"):
        if current[service]["health"] != "healthy":
            raise ValueError("A required service is unhealthy")
    if any((current[LAB]["ports"] or {}).values()):
        raise ValueError("Perpetuals worker must have no published ports")
    ready, health, lab = api("/readyz"), api("/healthz"), api("/api/perpetuals")
    if (ready.get("live_trading_enabled") is not False or ready.get("ready") is not True
            or health.get("version") != VERSION or lab.get("paper_only") is not True
            or not lab.get("data_fresh") or not lab.get("available")
            or tuple(a["leverage"] for a in lab["accounts"]) != (1, 3, 10)):
        raise ValueError("Paper mode, application identity or perpetuals feed is not ready")
    if require_flat and (lab.get("entries_enabled") or any(a["position"] for a in lab["accounts"])):
        raise ValueError("Perpetuals must be paused and flat during cutover")
    financial_state(require_flat=require_flat)
    personal = api("/api/personal-paper")
    system = api("/api/system")
    learning = api("/api/personal-paper/learning")
    if (not personal.get("worker_health", {}).get("fresh") or system.get("worker") != "ok"
            or system.get("postgresql") != "ok" or system.get("redis") != "ok"
            or learning.get("backend_version") != VERSION or learning.get("collector_stale") is not False
            or learning.get("collection_failure") or learning.get("live_authorized") is not False
            or learning.get("primary_promotion_automatic") is not False):
        raise ValueError("Existing worker, learning collector or data services are not ready")
    return {"status": "PASS", "images": images, "private_access": verify_private_access(),
            "perpetuals_feed": lab["feed_status"], "entries_enabled": lab["entries_enabled"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preflight", "activate", "verify"])
    parser.add_argument("--commit", required=True)
    parser.add_argument("--approved-commit")
    args = parser.parse_args()
    if not re.fullmatch("[a-f0-9]{40}", args.commit) or ROOT != BASE / "releases" / args.commit:
        raise ValueError("Run from the immutable Aruba staging release directory")
    manifest_file = ROOT / "release-manifest.json"
    verify_source_release(ROOT, manifest_file, args.commit)
    manifest = json.loads(manifest_file.read_text())
    if manifest["version"] != "4.9.6rc1":
        raise ValueError("Unexpected release version")
    incoming = BASE / "incoming" / args.commit
    require_readiness(manifest, incoming)
    if args.action == "activate" and args.approved_commit != args.commit:
        raise ValueError("Supply the explicitly approved full commit before activation")
    os.umask(0o077)
    images = bound_images(manifest, incoming)
    if args.action == "verify":
        print(json.dumps(verify(images, require_flat=False)))
        return
    verify_private_access()
    financial_state(require_flat=args.action == "activate")
    if args.action == "preflight":
        print(json.dumps({"status": "PASS", "commit": args.commit, "images": images}))
        return

    lock = (BASE / "ops/v49-release.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    require_perpetuals_flat()
    directory = BASE / "evidence" / ("v496-" + args.commit[:12])
    directory.mkdir(mode=0o700)
    previous = inventory()["services"]
    old_wrapper = BASE / "ops/compose"
    (directory / "previous-compose").write_bytes(old_wrapper.read_bytes())
    backup_wrapper = BASE / "ops/backup.py"
    (directory / "previous-backup").write_bytes(backup_wrapper.read_bytes())
    save(directory / "previous-images.json", previous)
    save(directory / "paused-financial-state.json", financial_state(require_flat=True))
    override = directory / "images.json"
    app_services = (*CORE, LAB, "migrate", "research-init")
    services = {s: {"image": images["frontend" if s == "frontend" else "app"]} for s in app_services}
    services["backend"]["environment"] = {"PAPER_PERPETUALS_ENABLED": "true"}
    services[LAB]["environment"] = {"ENVIRONMENT": "staging", "PAPER_PERPETUALS_ENABLED": "true"}
    save(override, {"services": services})
    command = [
        "env", "PAPER_PERPETUALS_DATABASE_NAME=autotrader_aruba_staging", "docker", "compose",
        "--project-directory", str(ROOT), "-p", PROJECT, "--profile", "research",
        "--profile", "perpetuals", "--env-file", str(BASE / "config/.env.staging"),
        "-f", str(ROOT / "docker-compose.yml"), "-f", str(BASE / "config/compose.staging.yml"), "-f", str(override),
    ]
    check_config(command)
    configured = json.loads(run([*command, "config", "--format", "json"]))["services"]
    env = configured[LAB]["environment"]
    if (configured[LAB].get("ports") or configured[LAB].get("volumes")
            or env.get("DATABASE_URL") != configured["backend"]["environment"]["DATABASE_URL"]
            or env.get("LIVE_TRADING_ENABLED") != "false" or env.get("PAPER_TRADING_ENABLED") != "true"):
        raise ValueError("Perpetuals worker scope mismatch")
    old_ledgers = json.loads(dc("exec", "-T", "backend", "python", "-c", LEDGERS))
    try:
        before = backup(images)
        save(directory / "backup-restore.json", before)
        financial_state(require_flat=True)
        require_perpetuals_flat()
        dc("stop", "worker", "research-worker", "backend")
        wrapper = directory / "candidate-compose"
        wrapper.write_text("#!/bin/sh\nexec " + shlex.join(command) + ' "$@"\n')
        wrapper.chmod(0o700)
        temporary = BASE / "ops/compose.v496.tmp"
        with temporary.open("x") as handle:
            handle.write(wrapper.read_text())
        temporary.chmod(0o700)
        os.replace(temporary, old_wrapper)
        dc("up", "-d", "--wait", "--wait-timeout", "240", "--no-build", "--no-deps", *CORE, LAB)
        after_services = inventory()["services"]
        for service in ("postgres", "redis"):
            if any(previous[service][key] != after_services[service][key] for key in ("image", "volumes")):
                raise ValueError("Retained infrastructure identity changed")
        after = backup(images)
        save(directory / "after-backup-restore.json", after)
        save(directory / "spot-financial-seals.json", compare_financial_backups(before, after))
        records = json.loads(Path(after["manifest"]).read_text())["databases"]
        official = next(r for r in records if r["database"] == "autotrader_aruba_staging")
        if not PERP_TABLES.issubset(official["financial_seal"]):
            raise ValueError("Perpetuals state and journal were not restore-verified")
        new_ledgers = json.loads(dc("exec", "-T", "backend", "python", "-c", LEDGERS))
        save(directory / "retained-shadow-identities.json", same_controls(old_ledgers, new_ledgers))
        for attempt in range(12):
            try:
                result = verify(images, require_flat=True)
                break
            except (KeyError, ValueError, OSError):
                if attempt == 11:
                    raise
                time.sleep(5)
        backup_wrapper.write_text("import runpy\nrunpy.run_path(" + repr(str(ROOT / "deploy/staging_backup.py"))
                                  + ",run_name='__main__')\n")
        backup_wrapper.chmod(0o600)
        save(directory / "verified.json", result)
        print(json.dumps(result))
    except Exception:
        # Leave all entry controls paused. An operator decides how to recover
        # using the saved wrapper/images and current exposure; never restore over live data.
        save(directory / "activation-failed.json", {"status": "FAILED", "automatic_restore": False,
                                                    "entries_must_remain_paused": True})
        raise


if __name__ == "__main__":
    main()
