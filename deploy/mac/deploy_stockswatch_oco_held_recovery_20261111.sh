#!/usr/bin/env bash
# StocksWatch paper-only OCO held-leg recovery (Nov 11, 2026).
# Replaces ONLY stockswatch/alpaca_paper.py and stockswatch/profit_oco.py.
# No broker POST/PATCH/DELETE; no changes to DB pause, cash, or orders.
set -Eeuo pipefail

COMMIT="fcf1698edd49c33e2d733b4c8de7af4480e41955"
REPO="Mohammad-khataeii/AutoTrader"
SSH_HOST="${STOCKSWATCH_SSH_ALIAS:-aruba-vps}"
PROJECT="autotrader-aruba-stockswatch"
WORK="$(mktemp -d)"
REMOTE=""
cleanup() {
  rm -rf "$WORK"
  if [ -n "$REMOTE" ]; then ssh -T "$SSH_HOST" "rm -rf '$REMOTE'" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

for program in curl git ssh scp tar; do
  command -v "$program" >/dev/null || { echo "Missing local command: $program"; exit 1; }
done
mkdir -p "$WORK/stockswatch"
echo "== Fetching pinned, reviewed stock-only OCO release =="
curl -fLSs --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 65 \
  "https://raw.githubusercontent.com/$REPO/$COMMIT/stockswatch/profit_oco.py" \
  -o "$WORK/stockswatch/profit_oco.py"
curl -fLSs --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 65 \
  "https://raw.githubusercontent.com/$REPO/$COMMIT/stockswatch/alpaca_paper.py" \
  -o "$WORK/stockswatch/alpaca_paper.py"
test "$(git hash-object "$WORK/stockswatch/profit_oco.py")" = "82d4e0ba5bd1b7f5ce494805cf1ba35548535f6c" \
  || { echo "OCO source Git blob SHA mismatch"; exit 1; }
test "$(git hash-object "$WORK/stockswatch/alpaca_paper.py")" = "6527bfa6074b2b49ae82eef5d9c1c68b2f8dadd3" \
  || { echo "Broker source Git blob SHA mismatch"; exit 1; }
tar -C "$WORK" -czf "$WORK/release.tgz" \
  stockswatch/profit_oco.py stockswatch/alpaca_paper.py

REMOTE="$(ssh -T "$SSH_HOST" 'mktemp -d /tmp/stockswatch-oco-held-20261111-XXXXXX' | tr -d '\r')"
case "$REMOTE" in /tmp/stockswatch-oco-held-20261111-*) ;; *) echo "Unsafe remote staging path"; exit 1;; esac
scp -q "$WORK/release.tgz" "$SSH_HOST:$REMOTE/release.tgz"

echo "== Read-only preflight, isolated candidate, scoped rollout =="
ssh -T "$SSH_HOST" "sudo -n python3 - '$REMOTE' '$PROJECT' '$COMMIT'" <<'REMOTE_PY'
import os, sys, json, sqlite3, subprocess, tarfile, shutil, hashlib, time, re
from pathlib import Path
from datetime import datetime, time as ClockTime
from zoneinfo import ZoneInfo

staging_tmp=Path(sys.argv[1])
project=sys.argv[2]
release=sys.argv[3]
targets={
    "profit_oco.py":"/opt/stockswatch/stockswatch/profit_oco.py",
    "alpaca_paper.py":"/opt/stockswatch/stockswatch/alpaca_paper.py",
}
python="/opt/stockswatch/venv/bin/python"
stage=Path("/opt/personal-plan/staging/integrations")/(
    "stockswatch-oco-held-"+release[:12]+"-"+datetime.now().strftime("%Y%m%dT%H%M%S"))
stage.mkdir(parents=True,exist_ok=False)
cutover=False
base_args=None
old_container=None
peer_ids={}

def run(*args,timeout=80):
    result=subprocess.run(list(args),text=True,capture_output=True,timeout=timeout)
    if result.returncode:
        # No stdout or stderr from Docker is exposed: it may contain secrets.
        raise RuntimeError("command_failed_"+Path(args[0]).name+"_"+str(result.returncode))
    return result.stdout.strip()

def inspect(cid):
    data=json.loads(run("docker","inspect",cid))
    if len(data)!=1:raise RuntimeError("docker_inspect_ambiguous")
    return data[0]

def container_id():
    ids=run("docker","ps","-q",
        "--filter","label=com.docker.compose.project="+project,
        "--filter","label=com.docker.compose.service=stockswatch").splitlines()
    if len(ids)!=1:raise RuntimeError("stockswatch_running_service_not_unique")
    return ids[0]

def docker_compose(args,*cmd,timeout=90):
    return run("docker","compose",*args,*cmd,timeout=timeout)

def peer_snapshot():
    result={}
    ids=run("docker","ps","-q","--filter","label=com.docker.compose.project="+project)
    for cid in ids.splitlines():
        item=inspect(cid)
        svc=item["Config"]["Labels"].get("com.docker.compose.service")
        if svc!="stockswatch":
            result[svc]=cid
    return result

def assert_off_session():
    ny=datetime.now(ZoneInfo("America/New_York"))
    # Includes the conservative last 15min after close; does not assume
    # that a weekend/holiday is a market trading session.
    if ny.weekday()<5 and ClockTime(9,20)<=ny.time()<ClockTime(16,15):
        raise RuntimeError("MARKET_SESSION_ACTIVE__run_after_16_15_New_York_time")

def host_db(loaded):
    db_inside=dict(v.split("=",1) for v in loaded["Config"]["Env"]
                   if "=" in v).get("STOCKSWATCH_DB","/stockswatch-data/stockswatch.sqlite3")
    matches=[]
    for mount in loaded.get("Mounts",[]):
        dest=mount.get("Destination","").rstrip("/")
        if db_inside==dest or db_inside.startswith(dest+"/"):
            matches.append((len(dest),mount,os.path.relpath(db_inside,dest)))
    if not matches:raise RuntimeError("sqlite_mount_not_identified")
    _,mount,relative=max(matches,key=lambda a:a[0])
    if mount.get("Type") not in ("bind","volume"):
        raise RuntimeError("sqlite_mount_unsupported")
    filename=Path(mount["Source"])/relative
    if not filename.is_file():raise RuntimeError("sqlite_host_ledger_missing")
    return filename

def sqlite_preflight(database):
    connection=sqlite3.connect(database.as_uri()+"?mode=ro",uri=True,timeout=30)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA temp_store=MEMORY")
        names={r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        required={"sw_alpaca_state","sw_protection","ac_managed","ac_intents","sw_alpaca_intents"}
        if not required.issubset(names):
            raise RuntimeError("expected_stock_and_crypto_tables_missing")
        if connection.execute("SELECT COUNT(*) FROM ac_managed").fetchone()[0]:
            raise RuntimeError("crypto_has_software_only_stop_positions__restart_refused")
        if connection.execute(
             "SELECT COUNT(*) FROM ac_intents WHERE state IN ('PREPARED','UNCERTAIN')").fetchone()[0]:
            raise RuntimeError("crypto_order_intent_unresolved__restart_refused")
        if connection.execute(
             "SELECT COUNT(*) FROM sw_alpaca_intents WHERE state IN ('PREPARED','UNKNOWN')").fetchone()[0]:
            raise RuntimeError("stock_order_intent_unresolved__restart_refused")
        pause=connection.execute("SELECT paused FROM sw_alpaca_state WHERE id=1").fetchone()
        if not pause:raise RuntimeError("stock_pause_state_missing")
        rows=connection.execute(
             "SELECT symbol,state,last_error FROM sw_protection ORDER BY symbol").fetchall()
        print("PASS: ledger, order intent state, crypto software-stop safety")
        print("Stock entry pause preserved:",bool(pause[0]))
        print("Local OCO states:",[(r[0],r[1]) for r in rows])
    finally:connection.close()

def backup_sqlite(database):
    free=shutil.disk_usage(stage).free
    size=database.stat().st_size
    if free<max(50_000_000,2*size+20_000_000):
        raise RuntimeError("insufficient_disk_for_transactional_backup")
    destination=stage/"stockswatch-before.sqlite3"
    s=sqlite3.connect(database.as_uri()+"?mode=ro",uri=True,timeout=45)
    d=sqlite3.connect(str(destination),timeout=45)
    try:
        s.backup(d,pages=256,sleep=0.10)
        answer=d.execute("PRAGMA integrity_check").fetchone()
        if answer!=( "ok",):raise RuntimeError("backup_integrity_check_failed")
    finally:
        d.close()
        s.close()
    os.chmod(destination,0o600)
    print("PASS: SQLite online backup and integrity check")

def load_release():
    expected=set("stockswatch/"+name for name in targets)
    with tarfile.open(staging_tmp/"release.tgz","r:gz") as tar:
        members=tar.getmembers()
        if {m.name for m in members}!=expected or any(
                not m.isfile() or m.size>250_000 for m in members):
            raise RuntimeError("release_member_whitelist_failed")
        for member in members:
            name=Path(member.name).name
            stream=tar.extractfile(member)
            if stream is None:raise RuntimeError("release_member_unreadable")
            body=stream.read()
            dest=stage/name
            dest.write_bytes(body)
            os.chmod(dest,0o644)
    return {name:hashlib.sha256((stage/name).read_bytes()).hexdigest() for name in targets}

def smoke(image):
    args=["docker","run","--rm","--network","none","--read-only",
          "--tmpfs","/tmp:rw,nosuid,noexec,size=16m",
          "-e","PYTHONDONTWRITEBYTECODE=1"]
    for name,target in targets.items():
        args+=["--mount","type=bind,src="+str(stage/name)+",dst="+target+",readonly"]
    script='''
from stockswatch import profit_oco, alpaca_paper
from decimal import Decimal
assert profit_oco.__file__=="/opt/stockswatch/stockswatch/profit_oco.py"
assert alpaca_paper.__file__=="/opt/stockswatch/stockswatch/alpaca_paper.py"
r={"client_id":"swg1-test","symbol":"AAPL","target":"405.98",
   "qty":"33","root_order_id":"root-12345678"}
o={"id":"root-12345678","client_order_id":"swg1-test",
   "symbol":"AAPL","side":"sell","order_class":"oco","type":"limit",
   "time_in_force":"gtc","status":"new","limit_price":"405.98",
   "qty":"33","legs":[{"id":"stop-12345678","symbol":"AAPL",
   "side":"sell","type":"stop","status":"held",
   "qty":"33","stop_price":"329.12"}]}
leg, stop=profit_oco._validate_pair(o,r)
assert leg=="stop-12345678" and stop==Decimal("329.12")
o["legs"][0]["qty"]="32"
try: profit_oco._validate_pair(o,r)
except profit_oco.ProtectionError: pass
else: raise AssertionError("incomplete_stop_coverage_accepted")
print("HELD_OCO_IMPORT_AND_VALIDATION_OK")
'''
    result=run(*args,"--entrypoint",python,image,"-c",script,timeout=85)
    if "HELD_OCO_IMPORT_AND_VALIDATION_OK" not in result:
        raise RuntimeError("isolated_held_stop_smoke_failed")
    print("PASS: isolated candidate imports and held-OCO verification")

def compose_files(labels):
    label=labels.get("com.docker.compose.project.config_files","")
    names=[p.strip() for p in re.split("[,;]",label) if p.strip()]
    if len(names)==1 and not Path(names[0]).is_file() and ":" in label:
        names=[p for p in label.split(":") if p]
    if not names or not all(Path(p).is_file() for p in names):
        raise RuntimeError("active_compose_files_unavailable")
    directory=labels.get("com.docker.compose.project.working_dir") or str(Path(names[0]).parent)
    if not Path(directory).is_dir():
        raise RuntimeError("compose_project_directory_unavailable")
    args=["--project-name",project,"--project-directory",directory]
    for p in names: args.extend(["-f",p])
    return args

def check_compose(base,added):
    before=json.loads(docker_compose(base,"config","--format","json"))
    after=json.loads(docker_compose(added,"config","--format","json"))
    a,b=before.get("services",{}),after.get("services",{})
    if set(a)!=set(b) or "stockswatch" not in a:
        raise RuntimeError("compose_service_scope_changed")
    if any(a[k]!=b[k] for k in a if k!="stockswatch"):
        raise RuntimeError("compose_peer_service_config_changed")
    original=dict(a["stockswatch"]); updated=dict(b["stockswatch"])
    original.pop("volumes",None);updated.pop("volumes",None)
    if original!=updated:raise RuntimeError("stockswatch_non_volume_config_changed")
    volumes=b["stockswatch"].get("volumes",[])
    for name,target in targets.items():
        matches=[v for v in volumes if v.get("target")==target]
        if len(matches)!=1 or matches[0].get("source")!=str(stage/name):
            raise RuntimeError("source_overlay_not_applied_"+name)
    print("PASS: Compose unchanged for all other services and settings")

def rollback():
    if base_args is None:return
    try:
        docker_compose(base_args,"up","-d","--no-deps","--no-build",
                       "--pull","never","stockswatch",timeout=200)
        print("Rollback to previous Compose configuration requested.")
    except Exception:
        print("WARNING: ROLLBACK_FAILED. Operator must inspect server Compose state.")

try:
    assert_off_session()
    old_container=container_id()
    old=inspect(old_container)
    labels=old["Config"].get("Labels") or {}
    if labels.get("com.docker.compose.project")!=project:
        raise RuntimeError("wrong_compose_project")
    env=dict(v.split("=",1) for v in old["Config"]["Env"] if "=" in v)
    if (env.get("STOCKSWATCH_EXECUTION_BACKEND")!="alpaca_paper"
        or env.get("STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS")!="1"
        or env.get("STOCKSWATCH_PROTECTION_ALLOW_PAPER_ORDERS")!="1"):
        raise RuntimeError("paper_only_oco_permission_preflight_failed")
    run("docker","exec",old_container,python,"-c",
        "from stockswatch import profit_oco, alpaca_paper; assert profit_oco and alpaca_paper")
    peer_ids=peer_snapshot()
    database=host_db(old)
    sqlite_preflight(database)
    sums=load_release()
    print("Source SHA256 verified on VPS:",{k:v[:12] for k,v in sums.items()})
    smoke(old["Image"])
    backup_sqlite(database)
    base_args=compose_files(labels)
    overlay=stage/"oco-held-override.json"
    model={"services":{"stockswatch":{"volumes":[
        {"type":"bind","source":str(stage/name),"target":target,
         "read_only":True,"bind":{"create_host_path":False}}
        for name,target in targets.items()]}}}
    overlay.write_text(json.dumps(model,indent=2)+"\n")
    added=base_args+["-f",str(overlay)]
    check_compose(base_args,added)
    assert_off_session()
    print("== Switching only StocksWatch service; no broker orders changed by deployer ==")
    cutover=True
    docker_compose(added,"up","-d","--no-deps","--no-build",
                   "--pull","never","stockswatch",timeout=240)
    new_container=container_id()
    if new_container==old_container:
        raise RuntimeError("expected_new_compose_container_missing")
    # Check imports and original in-container code bytes, not Docker success alone.
    check_script='''
import hashlib
from stockswatch import profit_oco, alpaca_paper
expected=__import__("json").loads(__import__("os").environ["STOCKSWATCH_OCO_TEST_EXPECTED"])
for module in (profit_oco, alpaca_paper):
    got=hashlib.sha256(open(module.__file__,"rb").read()).hexdigest()
    if got!=expected[module.__file__.rsplit("/",1)[-1]]:
        raise RuntimeError("deployed_file_hash_mismatch")
print("VERIFIED_NEW_OCO_MODULES")
'''
    # Do not expose credentials or alter existing runtime environment.
    check_script=check_script.replace(
        '__import__("os").environ["STOCKSWATCH_OCO_TEST_EXPECTED"]',
        repr(json.dumps(sums)))
    out=run("docker","exec",new_container,python,"-c",check_script,timeout=60)
    if "VERIFIED_NEW_OCO_MODULES" not in out:
        raise RuntimeError("new_container_source_verification_failed")
    if peer_snapshot()!=peer_ids:
        raise RuntimeError("peer_container_identity_changed")
    print("SUCCESS: new OCO code loaded; all peer containers unchanged.")
    print("Release stage:",str(stage))
    print("Existing DB pause and broker orders were not modified by deployer.")
    print("AAPL/ABBV re-verification requires next regular US equity CORE session.")
    print("ACN/AMGN remain UNPROTECTED until separately broker-verified.")
except Exception as exc:
    print("DEPLOYMENT FAILED:",str(exc))
    if cutover:rollback()
    raise SystemExit(1)
REMOTE_PY
