#!/usr/bin/env python3
"""Local-host operator tool for the two StocksWatch staging services."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

STAGING = "autotrader-aruba-test"
PROJECT = "autotrader-aruba-stockswatch"
TARGETS = ("stockswatch", "frontend")
DB = "/stockswatch-data/stockswatch.sqlite3"
BACKEND = "http://backend:8000"
PORT = "13000"
REQUIRED = {
    "STOCKSWATCH_ALPACA_KEY",
    "STOCKSWATCH_ALPACA_SECRET",
    "STOCKSWATCH_ALPACA_PAPER_KEY",
    "STOCKSWATCH_ALPACA_PAPER_SECRET",
    "STOCKSWATCH_ALPACA_PAPER_ACCOUNT_ID",
}
OPTIONAL = {
    "STOCKSWATCH_TICK_SECONDS",
    "STOCKSWATCH_LOG_LEVEL",
    "STOCKSWATCH_SEC_USER_AGENT",
    "STOCKSWATCH_GEMINI_ENABLED",
    "GEMINI_MODEL",
    "GEMINI_API_KEY",
    "REDIS_URL",
    "STOCKSWATCH_INITIAL_USD",
}


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def run(*cmd, timeout=120):
    # Docker/Compose errors may include secret env file contents. Keep command arguments
    # and stderr private; operators can inspect protected inputs when diagnosing failures.
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    require(result.returncode == 0, f"{cmd[0]}_{cmd[1]}_exit_{result.returncode}")
    return result.stdout.strip()


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def inspect(kind, identifier):
    return json.loads(run("docker", kind, "inspect", identifier))[0]


def containers(project):
    return run(
        "docker",
        "ps",
        "-aq",
        "--no-trunc",
        "--filter",
        f"label=com.docker.compose.project={project}",
    ).splitlines()


def labels(container):
    return container["Config"]["Labels"] or {}


def service(container):
    return labels(container).get("com.docker.compose.service")


def project(container):
    return labels(container).get("com.docker.compose.project")


def local_docker():
    require(
        not os.environ.get("DOCKER_HOST") and not os.environ.get("DOCKER_CONTEXT"),
        "unset_DOCKER_HOST_and_DOCKER_CONTEXT",
    )
    endpoint = run("docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
    require(endpoint == "unix:///var/run/docker.sock", "local_linux_docker_socket_required")
    run("docker", "compose", "version")
    require(
        run("docker", "info", "--format", "{{.OSType}}/{{.Architecture}}") == "linux/x86_64",
        "local_linux_amd64_engine_required",
    )


def topology():
    members = [inspect("container", cid) for cid in containers(STAGING)]
    selected = {}
    for name in (*TARGETS, "backend"):
        matches = [c for c in members if service(c) == name]
        require(
            len(matches) == 1 and matches[0]["State"]["Running"], f"expected_one_running_{name}"
        )
        selected[name] = matches[0]
    sw, fe, backend = (selected[name] for name in (*TARGETS, "backend"))
    mounts = sw["Mounts"]
    require(
        len(mounts) == 1
        and mounts[0]["Type"] == "bind"
        and mounts[0]["RW"]
        and mounts[0]["Destination"] == "/stockswatch-data"
        and mounts[0].get("Propagation") in ("", "rprivate")
        and not fe["Mounts"],
        "unexpected_stockswatch_or_frontend_mounts",
    )
    env = container_env(sw)
    require(env.get("STOCKSWATCH_DB", DB) == DB, "unexpected_sqlite_path")
    require(
        env.get("STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS", "0") != "1",
        "existing_broker_submission_must_be_disarmed",
    )
    bind = sw["HostConfig"].get("PortBindings")
    require(
        not bind
        and fe["HostConfig"].get("PortBindings")
        == {
            "80/tcp": [{"HostIp": "127.0.0.1", "HostPort": PORT}],
        },
        "expected_only_staging_loopback_frontend_port",
    )
    for name, container in (("stockswatch", sw), ("frontend", fe)):
        host = container["HostConfig"]
        require(
            not (
                host["Privileged"]
                or host.get("Devices")
                or host.get("CapAdd")
                or host.get("Links")
                or host.get("ExtraHosts")
                or host.get("NetworkMode") == "host"
            ),
            f"unsupported_{name}_runtime_overrides",
        )
        require(
            host["RestartPolicy"]["Name"] in ("no", "unless-stopped"),
            f"unexpected_{name}_restart_policy",
        )
        require(
            not container["Config"].get("Entrypoint")
            or container["Config"]["Entrypoint"]
            == inspect("image", container["Image"])["Config"].get("Entrypoint"),
            f"unsupported_{name}_entrypoint_override",
        )
    sw_nets, fe_nets, be_nets = (c["NetworkSettings"]["Networks"] for c in (sw, fe, backend))
    shared = set(sw_nets) & set(fe_nets) & set(be_nets)
    require(
        any(
            "backend" in (be_nets[n].get("Aliases") or [])
            and "stockswatch" in (sw_nets[n].get("Aliases") or [])
            for n in shared
        ),
        "cannot_prove_existing_stockswatch_backend_discovery",
    )
    net_ids = {}
    for name, settings in list(sw_nets.items()) + list(fe_nets.items()):
        network = inspect("network", name)
        require(
            network["Id"] == settings["NetworkID"]
            and network["Driver"] == "bridge"
            and (network["Labels"] or {}).get("com.docker.compose.project") == STAGING
            and not settings.get("IPAMConfig"),
            "unsupported_existing_network",
        )
        net_ids[name] = network["Id"]
    data = Path(mounts[0]["Source"]).resolve()
    require(
        data.is_relative_to("/opt/personal-plan/staging") and (data / Path(DB).name).is_file(),
        "existing_staging_ledger_required",
    )
    return (
        {
            "targets": {
                name: {"id": selected[name]["Id"], "image": selected[name]["Image"]}
                for name in TARGETS
            },
            "peers": {
                c["Id"]: [c["Image"], c["State"]["Running"]]
                for c in members
                if service(c) not in TARGETS
            },
            "net_ids": net_ids,
            "data": str(data),
        },
        sw,
        fe,
    )


def container_env(container):
    return dict(line.split("=", 1) for line in container["Config"].get("Env", []) if "=" in line)


def runtime_env(path, old):
    require(
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_uid == os.geteuid()
        and not path.stat().st_mode & 0o077,
        "private_operator_owned_credentials_file_required",
    )
    supplied = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        require(
            sep
            and key in REQUIRED | OPTIONAL
            and key not in supplied
            and value.strip() == value
            and value
            and value.isprintable(),
            "invalid_runtime_env_line",
        )
        supplied[key] = value
    require(REQUIRED <= supplied.keys(), "required_stockswatch_alpaca_configuration_missing")
    return {**{k: v for k, v in container_env(old).items() if k in OPTIONAL and v}, **supplied}


def compose_model(plan, sw, fe, state, orders=False):
    network_keys = {name: f"net{i}" for i, name in enumerate(plan["net_ids"])}
    configs = {}
    for name, container in (("stockswatch", sw), ("frontend", fe)):
        host = container["HostConfig"]
        config = {
            "image": plan["images"][name],
            "pull_policy": "never",
            "restart": "unless-stopped",
            "networks": {
                network_keys[net]: {"aliases": sorted(set(settings.get("Aliases") or []) | {name})}
                for net, settings in container["NetworkSettings"]["Networks"].items()
            },
        }
        for old, new in (
            ("SecurityOpt", "security_opt"),
            ("Memory", "mem_limit"),
            ("PidsLimit", "pids_limit"),
            ("ReadonlyRootfs", "read_only"),
        ):
            if host.get(old):
                config[new] = host[old]
        if host.get("NanoCpus"):
            config["cpus"] = host["NanoCpus"] / 1_000_000_000
        configs[name] = config
    configs["frontend"]["ports"] = [f"127.0.0.1:{PORT}:80"]
    configs["frontend"]["healthcheck"] = {
        "test": ["CMD", "wget", "-q", "--spider", "http://127.0.0.1/healthz"],
        "interval": "15s",
        "timeout": "5s",
        "retries": 3,
    }
    configs["stockswatch"].update(
        {
            "stop_grace_period": "180s",
            "env_file": [{"path": str(state / "runtime.env"), "format": "raw"}],
            "environment": {
                "STOCKSWATCH_DB": DB,
                "STOCKSWATCH_EXECUTION_BACKEND": "alpaca_paper",
                "STOCKSWATCH_ALLOW_INIT": "0",
                "STOCKSWATCH_PRICE_PROVIDER": "alpaca",
                "STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS": "1" if orders else "0",
            },
            "volumes": [
                {
                    "type": "bind",
                    "source": plan["data"],
                    "target": "/stockswatch-data",
                    "bind": {"create_host_path": False},
                }
            ],
            "healthcheck": {
                "test": [
                    "CMD",
                    "python",
                    "-c",
                    "from urllib.request import urlopen; urlopen('http://127.0.0.1:8900/healthz',timeout=3)",
                ],
                "interval": "10s",
                "timeout": "5s",
                "retries": 3,
                "start_period": "15s",
            },
        }
    )
    return {
        "services": configs,
        "networks": {key: {"external": True, "name": name} for name, key in network_keys.items()},
    }


def write(path, data):
    temp = path.with_suffix(path.suffix + ".new")
    with temp.open("x") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    temp.replace(path)


def compose(state, model, *args, timeout=120):
    return run(
        "docker",
        "compose",
        "--project-directory",
        str(state),
        "--env-file",
        str(state / "empty.env"),
        "-p",
        PROJECT,
        "-f",
        str(state / model),
        *args,
        timeout=timeout,
    )


def fingerprint(db):
    require(
        db.execute("PRAGMA integrity_check").fetchall() == [("ok",)],
        "sqlite_integrity_check_failed",
    )
    require(
        db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        == ("stocks-v1",),
        "unknown_stockswatch_sqlite_schema",
    )
    tables = ("portfolio", "positions", "pending_orders", "fills", "equity_curve")
    return {
        table: hashlib.sha256(
            repr(db.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()).encode()
        ).hexdigest()
        for table in tables
    }


def open_readonly(path):
    return closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=15))


def verified_ledger(db):
    account = db.execute("SELECT cash,initial_cash,realized FROM portfolio WHERE id=1").fetchone()
    net, realized = db.execute("""SELECT COALESCE(SUM(CASE side WHEN 'BUY'
        THEN -qty*price-fee ELSE qty*price-fee END),0), COALESCE(SUM(realized),0) FROM fills""").fetchone()
    actual = dict(db.execute("SELECT symbol,qty FROM positions"))
    expected = dict(
        db.execute("""SELECT symbol,SUM(CASE side WHEN 'BUY' THEN qty ELSE -qty END)
        FROM fills GROUP BY symbol HAVING SUM(CASE side WHEN 'BUY' THEN qty ELSE -qty END)!=0""")
    )
    orphan = db.execute("""SELECT 1 FROM fills f LEFT JOIN pending_orders o ON o.id=f.order_id
        WHERE o.id IS NULL OR o.state!='FILLED' OR o.symbol!=f.symbol OR o.side!=f.side
              OR o.fill_day IS NOT f.fill_day OR f.qty<=0 OR f.price<=0 OR f.fee<0
        UNION ALL SELECT 1 FROM pending_orders o LEFT JOIN fills f ON f.order_id=o.id
        WHERE o.state='FILLED' AND f.id IS NULL LIMIT 1""").fetchone()
    require(
        account
        and account[0] >= 0
        and abs(account[1] + net - account[0]) <= 0.005
        and abs(account[2] - realized) <= 0.005
        and actual == expected
        and not orphan,
        "legacy_ledger_reconciliation_failed",
    )
    return fingerprint(db)


def backup(data, destination):
    require(not destination.exists(), "backup_already_exists")
    with (
        open_readonly(Path(data) / Path(DB).name) as origin,
        closing(sqlite3.connect(destination)) as target,
    ):
        origin.execute("BEGIN")
        fingerprint_before = verified_ledger(origin)
        origin.backup(target)
    with open_readonly(destination) as restored:
        require(
            verified_ledger(restored) == fingerprint_before, "backup_financial_fingerprint_mismatch"
        )
    with destination.open("rb") as file:
        os.fsync(file.fileno())
    return {"sqlite_sha256": digest(destination), "financial_tables": fingerprint_before}


def scoped_containers(plan):
    result = {}
    for cid in containers(PROJECT):
        container = inspect("container", cid)
        name = service(container)
        require(
            name in TARGETS and name not in result and container["Image"] == plan["images"][name],
            "scoped_project_container_identity_changed",
        )
        result[name] = container
    return result


def verify_peers(plan):
    expected = plan["peers"]
    for cid, old in expected.items():
        obj = inspect("container", cid)
        require(
            project(obj) == STAGING and [obj["Image"], obj["State"]["Running"]] == old,
            "unrelated_staging_container_changed",
        )
    require(
        set(containers(STAGING)) == set(expected) | {p["id"] for p in plan["targets"].values()},
        "original_staging_membership_changed",
    )
    for name, net_id in plan["net_ids"].items():
        require(inspect("network", name)["Id"] == net_id, "external_network_identity_changed")
    for name, old in plan["targets"].items():
        obj = inspect("container", old["id"])
        require(
            project(obj) == STAGING and service(obj) == name and obj["Image"] == old["image"],
            "original_container_identity_changed",
        )


def prepare(args, state):
    require(
        not (state / "plan.json").exists() and not containers(PROJECT),
        "use_new_private_state_directory",
    )
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "deploy"))
    from release import verify_source_release

    manifest = root / "release-manifest.json"
    verify_source_release(root, manifest, args.commit)
    source_files = json.loads(manifest.read_text())["files"]
    require(
        str(Path(__file__).resolve().relative_to(root)) in source_files,
        "deployment_tool_missing_from_manifest",
    )
    plan, sw, fe = topology()
    require(
        shutil.disk_usage(state).free
        >= max(2 * 1024**3, 4 * (Path(plan["data"]) / Path(DB).name).stat().st_size),
        "insufficient_state_filesystem_space",
    )
    env = runtime_env(args.runtime_env, sw)
    require(
        all("\n" not in v and "\r" not in v for v in env.values()),
        "multiline_runtime_env_unsupported",
    )
    write(state / "runtime.env", "".join(f"{k}={v}\n" for k, v in sorted(env.items())))
    write(state / "empty.env", "")
    plan.update(commit=args.commit, manifest_sha256=digest(manifest), images={})
    plan["original_configuration"] = {
        service(c): {
            "name": c["Name"],
            "user": c["Config"].get("User"),
            "networks": {n: v.get("Aliases") for n, v in c["NetworkSettings"]["Networks"].items()},
            "mounts": c["Mounts"],
            "ports": c["HostConfig"].get("PortBindings"),
            "restart": c["HostConfig"]["RestartPolicy"]["Name"],
            "env_keys": sorted(container_env(c)),
        }
        for c in (sw, fe)
    }
    plan["initial_backup"] = backup(plan["data"], state / "before.sqlite3")
    # Build from a fresh manifest-only tree. Ignored/untracked files cannot enter the build contexts.
    build = state / "build-source"
    build.mkdir()
    for name, expected_hash in source_files.items():
        if name.startswith(("frontend/", "stockswatch/")) or name in {
            "deploy/stockswatch/Dockerfile",
            "deploy/stockswatch/requirements.txt",
            ".dockerignore",
        }:
            dest = build / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / name, dest)
            require(digest(dest) == expected_hash, "build_source_changed")
    base_id = plan["targets"]["stockswatch"]["image"]
    base_tag = f"autotrader-stockswatch-base:config-{base_id.removeprefix('sha256:')}"
    run("docker", "image", "tag", base_id, base_tag)
    require(inspect("image", base_tag)["Id"] == base_id, "base_image_identity_mismatch")
    version = json.loads((build / "frontend/package.json").read_text())["version"]
    for name, context, options in (
        (
            "stockswatch",
            build,
            [
                "-f",
                str(build / "deploy/stockswatch/Dockerfile"),
                "--build-arg",
                f"BASE_IMAGE={base_tag}",
            ],
        ),
        ("frontend", build / "frontend", ["--build-arg", f"RELEASE_VERSION={version}"]),
    ):
        tag = f"autotrader-stockswatch-release-{name}:{args.commit}-{time.time_ns()}"
        with (state / f"{name}-build.log").open("x") as log:
            result = subprocess.run(
                [
                    "docker",
                    "build",
                    "--platform",
                    "linux/amd64",
                    "--tag",
                    tag,
                    "--build-arg",
                    f"RELEASE_COMMIT={args.commit}",
                    *options,
                    str(context),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=1800,
                check=False,
            )
        require(result.returncode == 0, f"{name}_image_build_failed_see_protected_build_log")
        image = inspect("image", tag)
        require(
            image["Architecture"] == "amd64"
            and image["Os"] == "linux"
            and image["Config"]["Labels"].get("org.opencontainers.image.revision") == args.commit,
            "image_identity_mismatch",
        )
        plan["images"][name] = image["Id"]
    require(inspect("image", base_tag)["Id"] == base_id, "base_image_identity_changed_during_build")
    for model, orders in (("read-only.json", False), ("armed.json", True)):
        write(state / model, json.dumps(compose_model(plan, sw, fe, state, orders), indent=2))
        compose(state, model, "config", "--quiet")
        require(
            set(compose(state, model, "config", "--services").splitlines()) == set(TARGETS),
            "scoped_compose_contains_unexpected_services",
        )
    plan["files"] = {
        name: digest(state / name)
        for name in ("runtime.env", "read-only.json", "armed.json", "empty.env", "before.sqlite3")
    }
    verify_peers(plan)
    write(state / "plan.json", json.dumps(plan, indent=2))
    print(
        f"Prepared {args.commit} with verified SQLite snapshot and two pinned images. Review {state / 'plan.json'}."
    )


def load_plan(args, state):
    plan = json.loads((state / "plan.json").read_text())
    require(plan["commit"] == args.commit, "approved_commit_mismatch")
    for name, expected in plan["files"].items():
        require(digest(state / name) == expected, f"prepared_file_changed_{name}")
    for name, iid in plan["images"].items():
        image = inspect("image", iid)
        require(
            image["Id"] == iid
            and image["Config"]["Labels"].get("org.opencontainers.image.revision") == args.commit,
            f"candidate_image_changed_{name}",
        )
    verify_peers(plan)
    scoped_containers(plan)
    return plan


def verify_runtime(plan, orders):
    live = scoped_containers(plan)
    require(
        set(live) == set(TARGETS)
        and all(
            c["State"]["Running"] and c["State"]["Health"]["Status"] == "healthy"
            for c in live.values()
        ),
        "scoped_runtime_unhealthy",
    )
    require(
        container_env(live["stockswatch"]).get("STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS")
        == str(int(orders)),
        "runtime_order_switch_mismatch",
    )
    sw = live["stockswatch"]
    require(
        len(sw["Mounts"]) == 1 and sw["Mounts"][0]["Source"] == plan["data"],
        "runtime_ledger_mount_mismatch",
    )
    # Unauthenticated through the retained frontend route must reach StocksWatch and be denied.
    script = f"""from urllib.request import urlopen
from urllib.error import HTTPError
import json
assert json.load(urlopen('http://127.0.0.1:8900/healthz', timeout=5))['mode'] == 'alpaca_paper'
assert urlopen('{BACKEND}/healthz', timeout=5).status == 200
try:
    urlopen('http://frontend/api/stockswatch/status', timeout=10)
except HTTPError as error:
    assert error.code == 401 and 'StocksWatch session cookie' in error.read().decode()
else:
    raise RuntimeError('StocksWatch route lacks session gate')
"""
    run("docker", "exec", sw["Id"], "python", "-c", script)
    from urllib.request import urlopen

    try:
        with urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=5) as response:
            require(response.status == 200, "loopback_frontend_unhealthy")
    except OSError:
        raise RuntimeError("loopback_frontend_unreachable") from None
    verify_peers(plan)


def wait_runtime(plan, orders):
    deadline = time.monotonic() + 70
    while True:
        try:
            verify_runtime(plan, orders)
            return
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)


def rollback(plan):
    require(
        not inspect("container", plan["targets"]["stockswatch"]["id"])["State"]["Running"],
        "original_stockswatch_still_running_no_cutover_to_roll_back",
    )
    live = scoped_containers(plan)
    for name in TARGETS:
        if name in live and live[name]["State"]["Running"]:
            run(
                "docker",
                "stop",
                "--time",
                "180" if name == "stockswatch" else "20",
                live[name]["Id"],
                timeout=200,
            )
    original_front = plan["targets"]["frontend"]["id"]
    if not inspect("container", original_front)["State"]["Running"]:
        run("docker", "start", original_front)
    verify_peers(plan)
    print(
        "Original frontend restored. StocksWatch remains stopped. Verify any Alpaca orders in Alpaca Paper."
    )


def cutover_backup(state):
    record = json.loads((state / "cutover.json").read_text())
    backup_path = state / "cutover.sqlite3"
    require(digest(backup_path) == record["sqlite_sha256"], "cutover_backup_hash_mismatch")
    with open_readonly(backup_path) as db:
        require(
            verified_ledger(db) == record["financial_tables"],
            "cutover_backup_reconciliation_failed",
        )
    return record


def configure(state, plan, operator_file):
    original = inspect("container", plan["targets"]["stockswatch"]["id"])
    require(
        not original["State"]["Running"]
        and not any(c["State"]["Running"] for c in scoped_containers(plan).values()),
        "rollback_and_reconcile_broker_before_reconfiguring",
    )
    cutover_backup(state)
    env = runtime_env(operator_file, original)
    require(
        all("\n" not in v and "\r" not in v for v in env.values()),
        "multiline_runtime_env_unsupported",
    )
    runtime = state / "runtime.env"
    previous = state / f"runtime.previous-{time.time_ns()}.env"
    write(previous, runtime.read_text())
    try:
        write(runtime, "".join(f"{k}={v}\n" for k, v in sorted(env.items())))
        compose(state, "read-only.json", "config", "--quiet")
        plan["files"]["runtime.env"] = digest(runtime)
        write(state / "plan.json", json.dumps(plan, indent=2))
    except Exception:
        write(runtime, previous.read_text())
        raise
    print("Private runtime configuration updated. Reapply the same images in read-only mode.")


def apply(state, plan):
    live = scoped_containers(plan)
    require(
        not any(c["State"]["Running"] for c in live.values()), "scoped_containers_already_running"
    )
    require(
        inspect("container", plan["targets"]["frontend"]["id"])["State"]["Running"],
        "original_frontend_must_be_running",
    )
    original_stock = inspect("container", plan["targets"]["stockswatch"]["id"])
    retry = (state / "cutover.json").exists()
    require(
        original_stock["State"]["Running"] != retry and (retry or not live),
        "original_stockswatch_cutover_state_changed",
    )
    if not retry:
        run("docker", "stop", "--time", "90", original_stock["Id"], timeout=110)
    try:
        if retry:
            value = cutover_backup(state)
            with open_readonly(Path(plan["data"]) / Path(DB).name) as db:
                require(
                    verified_ledger(db) == value["financial_tables"],
                    "legacy_financial_rows_changed_since_cutover",
                )
        else:
            value = backup(plan["data"], state / "cutover.sqlite3")
            write(state / "cutover.json", json.dumps(value, indent=2))
        run("docker", "stop", "--time", "20", plan["targets"]["frontend"]["id"])
        compose(
            state,
            "read-only.json",
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--pull",
            "never",
            *TARGETS,
        )
        wait_runtime(plan, False)
        with open_readonly(Path(plan["data"]) / Path(DB).name) as db:
            require(
                verified_ledger(db) == value["financial_tables"],
                "legacy_financial_rows_changed_at_cutover",
            )
    except Exception:
        rollback(plan)
        raise
    print(
        "Scoped read-only runtime is healthy. Verify the authenticated account and scanner before arming."
    )


def switch(state, plan, orders):
    require(
        (state / "cutover.json").is_file()
        and all(
            not inspect("container", t["id"])["State"]["Running"] for t in plan["targets"].values()
        ),
        "active_scoped_cutover_required",
    )
    live = scoped_containers(plan)
    require(set(live) == set(TARGETS), "active_scoped_cutover_required")
    if orders:
        verify_runtime(plan, False)
        with open_readonly(Path(plan["data"]) / Path(DB).name) as db:
            require(
                db.execute(
                    "SELECT paused,linked_account IS NOT NULL FROM sw_alpaca_state"
                ).fetchone()
                == (1, 1),
                "pause_and_verify_linked_account_in_dashboard_first",
            )
            require(
                db.execute("""SELECT COUNT(*) FROM sw_alpaca_intents
                WHERE state IN ('PREPARED','UNKNOWN','ACKNOWLEDGED')""").fetchone()
                == (0,),
                "unresolved_or_open_managed_intent",
            )
    model = "armed.json" if orders else "read-only.json"
    try:
        compose(
            state,
            model,
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--pull",
            "never",
            "stockswatch",
            timeout=210,
        )
        wait_runtime(plan, orders)
    except Exception:
        live = scoped_containers(plan)
        if live.get("stockswatch", {}).get("State", {}).get("Running"):
            run("docker", "stop", "--time", "180", live["stockswatch"]["Id"], timeout=200)
        raise
    print(
        "Paper switch updated. Confirm dashboard state. Accepted broker orders continue at Alpaca."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("preflight", "prepare", "apply", "configure", "arm", "disarm", "rollback"),
    )
    parser.add_argument("--state", type=Path)
    parser.add_argument("--commit")
    parser.add_argument("--runtime-env", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    local_docker()
    if args.action == "preflight":
        plan, sw, _ = topology()
        with open_readonly(Path(plan["data"]) / Path(DB).name) as db:
            verified_ledger(db)
        run(
            "docker",
            "exec",
            sw["Id"],
            "python",
            "-c",
            f"from urllib.request import urlopen; assert urlopen('{BACKEND}/healthz', timeout=5).status==200",
        )
        print(json.dumps(plan, indent=2))
        return
    require(
        args.state and args.commit and re.fullmatch(r"[a-f0-9]{40}", args.commit),
        "private_state_directory_and_full_commit_required",
    )
    state = args.state.absolute()
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(
        not state.is_symlink()
        and state.stat().st_uid == os.geteuid()
        and stat.S_IMODE(state.stat().st_mode) == 0o700,
        "state_directory_must_be_private",
    )
    with (state / "operator.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "prepare":
            require(args.runtime_env, "private_runtime_env_required")
            prepare(args, state)
        else:
            plan = load_plan(args, state)
            if args.action == "apply":
                apply(state, plan)
            elif args.action == "rollback":
                rollback(plan)
            elif args.action == "configure":
                require(args.runtime_env, "private_runtime_env_required")
                configure(state, plan, args.runtime_env)
            else:
                switch(state, plan, args.action == "arm")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
        # Avoid rendering exception arguments from tools that can include private config.
        print(
            f"StocksWatch operation stopped ({exc if type(exc) is RuntimeError else type(exc).__name__}).",
            file=sys.stderr,
        )
        sys.exit(1)
