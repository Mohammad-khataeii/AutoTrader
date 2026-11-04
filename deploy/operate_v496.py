"""Operate the user-approved V4.9.6 artifact; engineering tests explicitly skipped.

This is a deployment operator, not a changed application release. Application
source and images remain bound to a5720dca2592929c69d99442e8a89450fbb0c06b.
Remote backups are restored on the local host because Aruba lacks clone space.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import urllib.request

COMMIT = "a5720dca2592929c69d99442e8a89450fbb0c06b"
TASK = "autotrader-v496-20261104-user-no-tests"
REQUEST = "run the new version on the server and replace with the previous one, make it to be on runing, do no do any tests"
BASE = Path("/opt/personal-plan/staging")
RELEASE = BASE / "releases" / COMMIT
INCOMING = BASE / "incoming" / COMMIT
DIRECTORY = BASE / "evidence" / TASK


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write(path, value):
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    temp = path.with_name(path.name + ".tmp")
    with temp.open("x") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temp.chmod(0o600)
    os.replace(temp, path)


def report(phase, **details):
    print(json.dumps({"phase": phase, **details}), flush=True)


CONTROLS = '''import asyncio,json,sys
from autotrader.config import get_settings
from autotrader.persistence.database import make_engine,make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.personal_paper.service import PersonalPaperService
from autotrader.shadow.lab import ShadowLab
async def main():
 s=get_settings();assert s.environment=='staging' and not s.live_trading_enabled
 e=make_engine(s);official=PersistentTradingRepository(make_session_factory(e));personal=PersonalPaperService(official,s);lab=ShadowLab(official,s)
 try:
  primary=await personal.repository();assert primary
  controls=json.loads(sys.argv[1]);action=sys.argv[2]
  for name,repo in [('official',official),('personal',primary)]:
   if controls[name]['control']=='RUNNING':await repo.set_control(action)
  for identity,p in controls.items():
   if identity not in {'official','personal'} and p['control']=='RUNNING':await lab.control(identity,action)
  print(json.dumps({'status':'PASS','action':action,'previously_running':sum(p['control']=='RUNNING' for p in controls.values())}))
 finally:await lab.close();await personal.close();await e.dispose()
asyncio.run(main())
'''


def proof(h, label, path):
    data = json.loads(path.read_text())
    backup = json.loads((DIRECTORY / (label + "-backup.json")).read_text())
    manifest = Path(backup["manifest"])
    if (data.get("status") != "PASS" or data.get("commit") != COMMIT
            or data.get("backup_manifest_sha256") != sha(manifest)
            or data.get("app_config_id") != json.loads((INCOMING / "binding.json").read_text())["app"]
            or data.get("restore", {}).get("status") != "PASS"
            or len(data["restore"].get("accounts", [])) != 17
            or data.get("source_databases_restored") is not False):
        raise ValueError("Isolated local restore proof is missing, unrelated or incomplete")
    records = json.loads(manifest.read_text())["databases"]
    if data.get("dump_hashes") != {r["file"]: r["sha256"] for r in records}:
        raise ValueError("Restored dump identities do not match the remote backup")
    write(DIRECTORY / (label + "-restore-proof.json"), data)
    return backup


def backup(h, images, label):
    report("BACKUP", label=label)
    data = json.loads(h.run([sys.executable, str(RELEASE / "deploy/staging_backup.py"),
                              "--candidate-image", images["app"]]))
    if data.get("status") != "PASS" or data.get("accounts") != 17:
        raise ValueError("All 17 retained ledger backups are required")
    write(DIRECTORY / (label + "-backup.json"), data)
    report("AWAITING_LOCAL_RESTORE", label=label, manifest=data["manifest"], bytes=data["dump_bytes"])


def post_entries(enabled):
    values = dict(line.split("=", 1) for line in (BASE / "config/.env.staging").read_text().splitlines()
                  if "=" in line and not line.startswith("#"))
    auth = base64.b64encode((values.get("DASHBOARD_USERNAME", "admin") + ":" + values["DASHBOARD_PASSWORD"]).encode()).decode()
    request = urllib.request.Request("http://127.0.0.1:18000/api/perpetuals/entries", method="POST",
        data=json.dumps({"enabled": enabled}).encode(),
        headers={"Authorization": "Basic " + auth, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    if result["entries_enabled"] is not enabled:
        raise ValueError("Paper perpetuals entry control failed")


def prepare(h, images, binding):
    if DIRECTORY.exists():
        raise ValueError("A deployment record already exists; inspect and resume the recorded phase")
    h.verify_private_access()
    h.require_perpetuals_flat()
    original = h.financial_state(require_flat=False)
    DIRECTORY.mkdir(mode=0o700)
    authorization = {
        "task": TASK, "user_request": REQUEST,
        "request_sha256": hashlib.sha256(REQUEST.encode()).hexdigest(),
        "commit": COMMIT, "binding": binding, "operator_sha256": sha(__file__),
        "engineering_tests": "SKIPPED_BY_EXPLICIT_USER_REQUEST",
        "backup_restore_and_runtime_verification": "REQUIRED",
        "paper_only": True, "project": h.PROJECT, "scope": str(BASE),
    }
    claim = BASE / "ops" / ("authorization-" + TASK + ".json")
    with claim.open("x") as handle:
        json.dump(authorization, handle, indent=2)
        handle.flush(); os.fsync(handle.fileno())
    claim.chmod(0o600)
    write(DIRECTORY / "authorization.json", authorization)
    write(DIRECTORY / "original-controls.json", original)
    write(DIRECTORY / "previous-containers.json", h.inventory())
    for name in ("compose", "backup.py"):
        (DIRECTORY / ("previous-" + name)).write_bytes((BASE / "ops" / name).read_bytes())
    write(DIRECTORY / "original-ledgers.json", json.loads(h.dc("exec", "-T", "backend", "python", "-c", h.LEDGERS)))
    report("PAUSING_NEW_SPOT_ENTRIES")
    h.dc("exec", "-T", "backend", "python", "-c", CONTROLS, json.dumps(original), "pause")
    deadline = time.monotonic() + 3600
    while True:
        try:
            h.financial_state(require_flat=True)
            break
        except ValueError:
            if time.monotonic() >= deadline:
                raise RuntimeError("Deferred cutover expired; original protections retained")
            report("WAITING_FOR_EXISTING_POSITIONS_TO_CLOSE")
            time.sleep(15)
    backup(h, images, "before")


def activate(h, images):
    proof(h, "before", INCOMING / "before-restore.json")
    h.financial_state(require_flat=True)
    h.require_perpetuals_flat()
    if (DIRECTORY / "cutover-started.json").exists():
        raise ValueError("Cutover already attempted; preserve diagnostics and inspect")
    services = {name: {"image": images["frontend" if name == "frontend" else "app"]}
                for name in (*h.CORE, h.LAB, "migrate", "research-init")}
    services["backend"]["environment"] = {"PAPER_PERPETUALS_ENABLED": "true"}
    services[h.LAB]["environment"] = {"ENVIRONMENT": "staging", "PAPER_PERPETUALS_ENABLED": "true"}
    overrides = DIRECTORY / "images.json"
    write(overrides, {"services": services})
    command = ["env", "PAPER_PERPETUALS_DATABASE_NAME=autotrader_aruba_staging", "docker", "compose",
        "--project-directory", str(RELEASE), "-p", h.PROJECT, "--profile", "research", "--profile", "perpetuals",
        "--env-file", str(BASE / "config/.env.staging"), "-f", str(RELEASE / "docker-compose.yml"),
        "-f", str(BASE / "config/compose.staging.yml"), "-f", str(overrides)]
    h.check_config(command)
    configured = json.loads(h.run([*command, "config", "--format", "json"]))["services"]
    env = configured[h.LAB]["environment"]
    if (configured[h.LAB].get("ports") or configured[h.LAB].get("volumes")
            or env["DATABASE_URL"] != configured["backend"]["environment"]["DATABASE_URL"]
            or env["LIVE_TRADING_ENABLED"] != "false" or env["PAPER_TRADING_ENABLED"] != "true"):
        raise ValueError("Perpetuals worker scope mismatch")
    write(DIRECTORY / "cutover-started.json", {"commit": COMMIT, "images": images})
    report("REPLACING_APPROVED_APPLICATION_IMAGES")
    h.dc("stop", "worker", "research-worker", "backend")
    temporary = BASE / "ops/compose.v496-user.tmp"
    with temporary.open("x") as handle:
        handle.write("#!/bin/sh\nexec " + shlex.join(command) + ' "$@"\n')
    temporary.chmod(0o700)
    os.replace(temporary, BASE / "ops/compose")
    h.dc("up", "-d", "--wait", "--wait-timeout", "240", "--no-build", "--no-deps", *h.CORE, h.LAB)
    before = json.loads((DIRECTORY / "previous-containers.json").read_text())["services"]
    after = h.inventory()["services"]
    for name in ("postgres", "redis"):
        if any(before[name][key] != after[name][key] for key in ("image", "volumes")):
            raise ValueError("Existing infrastructure image or volume changed")
    for attempt in range(18):
        try:
            verified = h.verify(images, require_flat=True)
            break
        except Exception:
            if attempt == 17:
                raise
            report("WAITING_FOR_RUNTIME_HEALTH", attempt=attempt + 1)
            time.sleep(10)
    write(DIRECTORY / "paused-runtime.json", verified)
    backup(h, images, "after")


def finish(h, images):
    before = proof(h, "before", INCOMING / "before-restore.json")
    after = proof(h, "after", INCOMING / "after-restore.json")
    write(DIRECTORY / "financial-preservation.json", h.compare_financial_backups(before, after))
    records = json.loads(Path(after["manifest"]).read_text())["databases"]
    official = next(r for r in records if r["database"] == "autotrader_aruba_staging")
    if not h.PERP_TABLES.issubset(official["financial_seal"]):
        raise ValueError("Perpetuals history was not backup/restore verified")
    old = json.loads((DIRECTORY / "original-ledgers.json").read_text())
    new = json.loads(h.dc("exec", "-T", "backend", "python", "-c", h.LEDGERS))
    write(DIRECTORY / "shadow-preservation.json", h.same_controls(old, new))
    h.verify(images, require_flat=True)
    report("RESUMING_PAPER_TRADING")
    original = json.loads((DIRECTORY / "original-controls.json").read_text())
    h.dc("exec", "-T", "backend", "python", "-c", CONTROLS, json.dumps(original), "resume")
    for attempt in range(5):
        try:
            post_entries(True)
            break
        except Exception:
            if attempt == 4:
                raise
            time.sleep(3)
    result = h.verify(images, require_flat=False)
    current = h.financial_state(require_flat=False)
    if {k: p["control"] for k, p in current.items()} != {k: p["control"] for k, p in original.items()}:
        raise ValueError("Previous spot entry control states were not restored")
    lab = h.api("/api/perpetuals")
    if not lab["entries_enabled"] or not lab["data_fresh"]:
        raise ValueError("Perpetuals paper trading not running")
    result.update(commit=COMMIT, task=TASK, engineering_tests="SKIPPED_BY_USER",
                  perpetuals_entries_enabled=True, portfolios=current,
                  before_backup=before["manifest"], after_backup=after["manifest"])
    write(DIRECTORY / "verified-running.json", result)
    temp = BASE / "ops/backup.v496-user.tmp"
    temp.write_text("import runpy\nrunpy.run_path(" + repr(str(RELEASE / "deploy/staging_backup.py")) + ",run_name='__main__')\n")
    temp.chmod(0o600);os.replace(temp, BASE / "ops/backup.py")
    report("RUNNING", commit=COMMIT, perpetuals=lab["feed_status"], entries_enabled=True,
           primary_cash=current["personal"]["cash"], evidence=str(DIRECTORY))


def local_restore(folder):
    local = Path(__file__).resolve().parents[1]
    release = local / "deploy/releases" / COMMIT / "source"
    sys.path.insert(0, str(release / "deploy"))
    import staging_backup as backup_module
    manifest = folder / "backup-set.json"
    record = json.loads(manifest.read_text())
    assert record["application_commit"] == COMMIT and len(record["databases"]) == 17
    for row in record["databases"]:
        if Path(row["file"]).name != row["file"] or sha(folder / row["file"]) != row["sha256"]:
            raise ValueError("Backup dump hash mismatch")
    image = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}",
                                     "autotrader-app:" + COMMIT], text=True).strip()
    report("LOCAL_ISOLATED_RESTORE", folder=str(folder))
    result = {"status": "PASS", "commit": COMMIT, "backup_manifest_sha256": sha(manifest),
              "app_config_id": json.loads((release.parent / "binding.json").read_text())["app"],
              "dump_hashes": {r["file"]: r["sha256"] for r in record["databases"]},
              "engineering_tests": "SKIPPED_BY_USER"}
    backup_module.restore_clone(folder, record["databases"], image, manifest, result)
    write(folder / "isolated-restore.json", result)
    report("LOCAL_RESTORE_VERIFIED", databases=17, proof=str(folder / "isolated-restore.json"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "activate", "finish", "local-restore"])
    parser.add_argument("--approved-commit", required=True)
    parser.add_argument("--skip-engineering-tests", action="store_true", required=True)
    parser.add_argument("--folder", type=Path)
    args = parser.parse_args()
    if args.approved_commit != COMMIT:
        raise ValueError("Exact user-approved application commit required")
    os.umask(0o077)
    if args.phase == "local-restore":
        if not args.folder:
            raise ValueError("Local backup folder required")
        local_restore(args.folder.resolve())
        return
    sys.path.insert(0, str(RELEASE / "deploy"))
    import staging_v496 as h
    h.verify_source_release(RELEASE, RELEASE / "release-manifest.json", COMMIT)
    manifest = json.loads((RELEASE / "release-manifest.json").read_text())
    binding = json.loads((INCOMING / "binding.json").read_text())
    images = h.bound_images(manifest, INCOMING)
    lock = (BASE / "ops/v49-release.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if args.phase != "prepare":
        authorization = json.loads((DIRECTORY / "authorization.json").read_text())
        if authorization["operator_sha256"] != sha(__file__) or authorization["binding"] != binding:
            raise ValueError("Deployment authorization identity changed")
        if (DIRECTORY / "activation-failed.json").exists():
            raise ValueError("A failed deployment needs separately approved recovery")
    try:
        {"prepare": lambda: prepare(h, images, binding), "activate": lambda: activate(h, images),
         "finish": lambda: finish(h, images)}[args.phase]()
    except Exception as error:
        if DIRECTORY.exists():
            write(DIRECTORY / "activation-failed.json", {"phase": args.phase,
                "error": type(error).__name__, "message": str(error), "automatic_database_restore": False})
        raise


if __name__ == "__main__":
    main()
