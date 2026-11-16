#!/usr/bin/env python3
"""One-service Aruba PAPER-only crypto patch, with strict no-crypto-holdings cutover."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT = "autotrader-aruba-stockswatch"
DATA_TARGET = "/stockswatch-data"
DB_FILE = "stockswatch.sqlite3"
PYTHON = "/opt/stockswatch/venv/bin/python"
MODULE_ROOT = "/opt/stockswatch/stockswatch"
BASE_HASHES = {
    "alpaca_crypto.py": "a7466085a17ea983f70b7681e1a3dfe7d0f9685886f650e3bb597c4f1ea5db6c",
    "alpaca_crypto_paper.py": "11a9f707859c7f71169a7dc8152aa1ef8c4962bb16ed1412efed6c1d9afee26b",
}
FILES = [
    "stockswatch/alpaca_crypto.py",
    "stockswatch/alpaca_crypto_paper.py",
    "stockswatch/crypto_active_paper.py",
    "stockswatch/crypto_micro.py",
    "deploy/stockswatch/Dockerfile.crypto_micro",
    "deploy/stockswatch/crypto_micro_cutover.py",
]
BROKER_PROBE = """
import json,sqlite3
from pathlib import Path
from stockswatch.alpaca_crypto_paper import CryptoPaperClient
from stockswatch.storage import DB_PATH
from contextlib import closing
with CryptoPaperClient() as client:
    snap=client.snapshot()
with closing(sqlite3.connect(Path(DB_PATH).resolve().as_uri()+'?mode=ro',uri=True)) as c:
    c.execute('PRAGMA query_only=ON')
    c.execute('PRAGMA temp_store=MEMORY')
    paused=c.execute('SELECT paused FROM ac_state WHERE id=1').fetchone()[0]
    managed=c.execute('SELECT COUNT(*) FROM ac_managed').fetchone()[0]
    uncertain=c.execute("SELECT COUNT(*) FROM ac_intents WHERE state IN ('PREPARED','UNCERTAIN')").fetchone()[0]
    active=c.execute("SELECT COUNT(*) FROM ac_intents WHERE state='ACKNOWLEDGED' AND (broker_status IS NULL OR broker_status NOT IN ('filled','canceled','expired','rejected','replaced'))").fetchone()[0]
    micro=c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='ac_micro_audit'").fetchone()[0]
positions=[(p.get('symbol'),p.get('qty'),p.get('side')) for p in snap['other_positions']]
stock_orders=[(o.get('id'),o.get('symbol'),o.get('status')) for o in snap['other_open_orders']]
print(json.dumps({'crypto_positions':len(snap['positions']),
 'crypto_open_orders':len(snap['orders']),
 'managed':managed,'uncertain_intents':uncertain,'active_intents':active,
 'paused':paused,'micro_table_present':bool(micro),
 'stock_positions':positions,'stock_orders':stock_orders},sort_keys=True))
"""
DIGEST_PROBE = """
import hashlib,json
from pathlib import Path
r=Path('/opt/stockswatch/stockswatch')
print(json.dumps({n:hashlib.sha256((r/n).read_bytes()).hexdigest()
 for n in ('alpaca_crypto.py','alpaca_crypto_paper.py',
           'crypto_active_paper.py','crypto_micro.py') if (r/n).is_file()}))
"""


def need(cond, message):
    if not cond:
        raise RuntimeError(message)


def run(*args, timeout=120):
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout,check=False)
    need(p.returncode==0, f"command_failed_{args[0].split('/')[-1]}_{p.returncode}")
    return p.stdout.strip()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(container):
    return json.loads(run("docker","inspect",container))[0]


def scoped(service):
    ids=run("docker","ps","-q","--no-trunc",
            "--filter",f"label=com.docker.compose.project={PROJECT}",
            "--filter",f"label=com.docker.compose.service={service}").splitlines()
    need(len(ids)==1, f"one_running_{service}_required")
    return inspect(ids[0])


def env(container):
    return dict(x.split("=",1) for x in container["Config"]["Env"])


def compose(stock):
    l=stock["Config"]["Labels"]
    work=Path(l["com.docker.compose.project.working_dir"])
    need(work.is_dir() and work.resolve().is_relative_to(Path("/opt/personal-plan/staging")),
         "unexpected_compose_working_directory")
    files=l["com.docker.compose.project.config_files"].split(",")
    need(files and all(Path(f).is_file() and Path(f).is_absolute() for f in files),
         "missing_compose_source")
    base=["docker","compose","--project-directory",str(work),"-p",PROJECT]
    for f in files:base.extend(("-f",f))
    config=json.loads(run(*base,"config","--format","json"))
    need(set(config.get("services",{}))=={"stockswatch","frontend"},
         "unexpected_compose_services")
    return base,config


def market_closed():
    ny=datetime.now(ZoneInfo("America/New_York"))
    if ny.weekday()<5:
        mins=ny.hour*60+ny.minute
        need(not (9*60+10 <= mins < 16*60+15),
             "stock_session_window: deploy before 09:10 or after 16:15 New_York")
    return ny.isoformat()


def snapshot(stock):
    return json.loads(run("docker","exec",stock["Id"],PYTHON,"-c",BROKER_PROBE,timeout=90))


def preflight(state, revision):
    need(re.fullmatch(r"[0-9a-f]{40}",revision) is not None,"invalid_commit_sha")
    need(os.getenv("DOCKER_HOST") is None and os.getenv("DOCKER_CONTEXT") is None,
         "local_docker_only")
    need(run("docker","info","--format","{{.OSType}}/{{.Architecture}}") == "linux/x86_64",
         "aruba_linux_amd64_required")
    print("New York time:",market_closed(),flush=True)
    stock=scoped("stockswatch")
    front=scoped("frontend")
    need(stock["HostConfig"].get("ReadonlyRootfs"),"stockswatch_not_readonly")
    need(stock["State"].get("Health",{}).get("Status")=="healthy",
         "stockswatch_not_healthy")
    need(front["State"].get("Health",{}).get("Status")=="healthy","frontend_unhealthy")
    e=env(stock)
    need(e.get("STOCKSWATCH_EXECUTION_BACKEND")=="alpaca_paper",
         "not_paper_stock_backend")
    need(e.get("ALPACA_CRYPTO_ENABLED")=="1" and
         e.get("ALPACA_CRYPTO_ALLOW_PAPER_ORDERS")=="1" and
         e.get("LIVE_TRADING_ENABLED","false").lower() not in ("1","true","yes"),
         "not_paper_only_crypto")
    need(e.get("STOCKSWATCH_DB",DATA_TARGET+"/"+DB_FILE)==DATA_TARGET+"/"+DB_FILE,
         "unexpected_ledger_path")
    mounts=[m for m in stock["Mounts"] if m["Destination"]==DATA_TARGET]
    need(len(mounts)==1 and mounts[0]["Type"]=="bind" and mounts[0]["RW"],
         "unverified_ledger_bind")
    data=Path(mounts[0]["Source"])
    need(data.is_dir() and (data/DB_FILE).is_file() and
         data.resolve().is_relative_to(Path("/opt/personal-plan/staging")),
         "unrecognized_ledger_location")
    base,old=compose(stock)
    need(old["services"]["stockswatch"].get("environment",{}).get("ALPACA_CRYPTO_MICRO_MODE") in
         (None,"research","off","paper"),"unexpected_micro_setting")
    found=json.loads(run("docker","exec",stock["Id"],PYTHON,"-c",DIGEST_PROBE))
    need(all(found.get(name)==digest for name,digest in BASE_HASHES.items()),
         "runtime_source_hash_changed_since_forensic_export")
    broker=snapshot(stock)
    need(broker["crypto_positions"]==broker["crypto_open_orders"]==0 and
         broker["managed"]==broker["uncertain_intents"]==broker["active_intents"]==0,
         "crypto_not_flat_or_order_reconciliation_pending: software_exits_must_remain_running")
    need(broker["paused"]==0,"crypto_entries_currently_paused_no_override")
    need(shutil.disk_usage(state).free>=750*1024**2,"insufficient_disk_for_build_backup")
    need(state.is_dir() and state.resolve().is_relative_to(
         Path("/opt/personal-plan/staging/integrations")),"untrusted_release_directory")
    hashes=json.loads((state/"manifest.json").read_text())
    need(hashes.get("commit")==revision and
         set(hashes.get("files",{}))==set(FILES),"release_manifest_incomplete")
    for p in FILES:
        need(sha(state/p)==hashes["files"][p],"release_file_hash_mismatch:"+p)
    print("PASS: exact running code baseline, crypto broker flat, database owned, "
          "paper-only mode, pinned source and closed equities session",flush=True)
    print("Stocks currently held:",len(broker["stock_positions"]),
          "stock orders:",len(broker["stock_orders"]),flush=True)
    return stock,front,data,base,old,broker


def online_backup(source,destination):
    with sqlite3.connect(f"file:{source}?mode=ro",uri=True,timeout=15) as orig:
        orig.execute("PRAGMA busy_timeout=10000")
        with sqlite3.connect(destination,timeout=15) as out:
            orig.backup(out,pages=1000,sleep=.1)
            need(out.execute("PRAGMA integrity_check").fetchone()[0]=="ok",
                 "invalid_sqlite_backup")
            count=out.execute("SELECT COUNT(*) FROM ac_intents").fetchone()[0]
            return count


def wait_health(before_front,image_id):
    for _ in range(45):
        try:
            live=scoped("stockswatch")
            if (live["Image"]==image_id and
                live["State"].get("Health",{}).get("Status")=="healthy" and
                scoped("frontend")["Id"]==before_front["Id"]):
                return live
        except RuntimeError:
            pass
        time.sleep(3)
    raise RuntimeError("candidate_health_not_verified")


def deploy(state,revision):
    import fcntl
    with (state/".deploy.lock").open("a") as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        stock,front,data,base,model,book=preflight(state,revision)
        orig=stock["Image"]
        base_tag="local/stockswatch-crypto-micro-base:"+revision[:12]
        tag="local/stockswatch-crypto-micro:"+revision[:12]
        run("docker","tag",orig,base_tag)
        run("docker","build","--network","none","--pull=false","-f",
            str(state/"deploy/stockswatch/Dockerfile.crypto_micro"),
            "--build-arg","BASE_IMAGE="+base_tag,
            "--build-arg","RELEASE_SHA="+revision,
            "-t",tag,str(state),timeout=900)
        image_id=run("docker","image","inspect","-f","{{.Id}}",tag)
        candidate=json.loads(run("docker","run","--rm","--network","none",
            "--read-only",tag,PYTHON,"-c",DIGEST_PROBE,timeout=60))
        expected=json.loads((state/"manifest.json").read_text())["files"]
        for key in ("alpaca_crypto.py","alpaca_crypto_paper.py",
                    "crypto_active_paper.py","crypto_micro.py"):
            need(candidate.get(key)==expected["stockswatch/"+key],
                 "candidate_module_hash_does_not_match_pinned_source")
        # No credential reads or external calls in build/smoke.
        run("docker","run","--rm","--network","none","--read-only",tag,PYTHON,
            "-c","from stockswatch.crypto_micro import evaluate,mode; "
                 "from stockswatch.alpaca_crypto_paper import CryptoPaperClient; "
                 "assert mode() in ('off','research','paper')",timeout=60)
        override=state/"crypto-micro.override.yml"
        override.write_text(
            'services:\n  stockswatch:\n'
            '    image: "'+tag+'"\n'
            '    environment:\n      ALPACA_CRYPTO_MICRO_MODE: paper\n'
            '    volumes: !override\n'
            '      - type: bind\n'
            '        source: "'+str(data)+'"\n'
            '        target: /stockswatch-data\n'
            '        bind:\n          create_host_path: false\n')
        alt=[*base,"-f",str(override)]
        cfg=json.loads(run(*alt,"config","--format","json"))
        prior=model["services"]["stockswatch"]
        after=cfg["services"]["stockswatch"]
        need(set(cfg["services"])=={"stockswatch","frontend"},
             "candidate_changes_compose_topology")
        ignored={"image","volumes","environment"}
        need(all(after.get(k)==v for k,v in prior.items() if k not in ignored),
             "candidate_changes_stock_environment_or_process")
        oldenv=prior.get("environment",{})
        newenv=after.get("environment",{})
        need({k:v for k,v in newenv.items() if k!="ALPACA_CRYPTO_MICRO_MODE"}==
             {k:v for k,v in oldenv.items() if k!="ALPACA_CRYPTO_MICRO_MODE"} and
             newenv["ALPACA_CRYPTO_MICRO_MODE"]=="paper","candidate_environment_drift")
        need(len(after["volumes"])==1 and
             after["volumes"][0]["source"]==str(data) and
             after["volumes"][0]["target"]==DATA_TARGET,
             "candidate_financial_ledger_mount_drift")
        backup=state/"before-crypto-micro.sqlite3"
        online_backup(data/DB_FILE,backup)
        (state/"release-receipt.json").write_text(json.dumps({
          "commit":revision,"old_image":orig,"new_image":image_id,
          "old_container":stock["Id"],"original_broker_book":book,
          "backup":str(backup)},indent=2))
        freshstock=scoped("stockswatch")
        need(freshstock["Id"]==stock["Id"],"running_container_changed")
        need(snapshot(freshstock)==book,"paper_broker_book_changed_before_cutover")
        market_closed()
        stopped=False
        try:
            run(*base,"stop","-t","120","stockswatch",timeout=160)
            stopped=True
            current=inspect(stock["Id"])
            need(not current["State"]["Running"],"old_writer_still_running")
            # Never restore an old DB over an actively changing ledger.
            cutover=state/"after-stop.sqlite3"
            online_backup(data/DB_FILE,cutover)
            run(*alt,"up","-d","--no-deps","--no-build","--pull","never",
                "stockswatch",timeout=180)
            live=wait_health(front,image_id)
            need(env(live).get("ALPACA_CRYPTO_MICRO_MODE")=="paper" and
                 env(live).get("LIVE_TRADING_ENABLED","false").lower() not in
                     ("true","1","yes"),"candidate_not_paper_only")
            hashes=json.loads(run("docker","exec",live["Id"],PYTHON,"-c",DIGEST_PROBE))
            need(hashes==candidate,"runtime_source_hash_mismatch")
            need(any(x["Destination"]==DATA_TARGET and x["Source"]==str(data)
                     for x in live["Mounts"]),"runtime_db_mount_changed")
            need(scoped("frontend")["Id"]==front["Id"],"frontend_recreated")
            print("SUCCESS: crypto micro PAPER mode deployed at",revision,flush=True)
            print("Previous StocksWatch image:",orig,flush=True)
            print("Rollback copy and SQLite backups kept in",state,flush=True)
        except Exception:
            print("Candidate cutover failed; attempting safe old-service recovery",
                  file=sys.stderr,flush=True)
            if stopped:
                try:
                    running=run("docker","ps","-q","--no-trunc",
                        "--filter",f"label=com.docker.compose.project={PROJECT}",
                        "--filter","label=com.docker.compose.service=stockswatch").splitlines()
                    # A stopped original container is safe to restart; a
                    # running candidate must prove its crypto positions are
                    # flat before returning to the old software-stop worker.
                    can_rollback=True
                    if len(running)==1:
                        current=inspect(running[0])
                        nowbook=snapshot(current)
                        can_rollback=(nowbook["crypto_positions"]==0 and
                                      nowbook["crypto_open_orders"]==0 and
                                      nowbook["managed"]==0 and
                                      nowbook["uncertain_intents"]==0)
                    elif running:
                        can_rollback=False
                    if can_rollback:
                        run(*base,"up","-d","--no-deps","--no-build",
                            "--pull","never","stockswatch",timeout=180)
                        need(scoped("stockswatch")["Image"]==orig,
                             "rollback_image_mismatch")
                        print("Previous StocksWatch service restored; no ledger overwrites",
                              file=sys.stderr,flush=True)
                    else:
                        print("MANUAL REVIEW REQUIRED: crypto position/intents exist; "
                              "candidate left to manage its software exits.",
                              file=sys.stderr,flush=True)
                except Exception as exc:
                    print("Automatic recovery deferred:",type(exc).__name__,
                          file=sys.stderr,flush=True)
            raise


def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=("--preflight","--deploy"))
    p.add_argument("state")
    p.add_argument("revision")
    args=p.parse_args()
    os.umask(0o077)
    try:
        if args.mode=="--preflight":
            preflight(Path(args.state),args.revision)
        else:
            deploy(Path(args.state),args.revision)
    except Exception as exc:
        p.exit(1,"DEFERRED: "+str(exc)+"\n")


if __name__=="__main__":
    main()
