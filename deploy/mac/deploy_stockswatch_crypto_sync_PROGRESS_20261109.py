#!/usr/bin/env python3
"""Visible-progress, SHA-pinned Aruba upgrade for StocksWatch + AlpacaCrypto.

Run from macOS: python3 ~/Downloads/deploy_stockswatch_crypto_sync_20261109.py
Never sends broker orders, changes execution enablement, or migrates the ledger.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = "Mohammad-khataeii/AutoTrader"
RELEASE = "7a29ecfd1b1a306fa0f550e76ba1fcab194bdcea"
BLOBS = {
    "frontend/src/TradingOperations.css": "3a923f2a6ad5cd3776cae048b9e792d6d350e94f",
    "frontend/src/TradingOperations.tsx": "35ac87dbc8b524b755a6002da94cc3174791b1e7",
    "frontend/src/StocksWatch.tsx": "779dc7bb9cc73b8684a5a1023b822b169a3cdb9f",
    "stockswatch/alpaca_crypto.py": "1873d307b3fc9ec19c9b63a301c3ff1f184e480f",
    "stockswatch/alpaca_crypto_paper.py": "4ae088809e18a35f012ae0dcfbd1b5f4ebdd9f8f",
    "stockswatch/crypto_continuation.py": "0fe960a2c7c6547455f06745993d711a8968a309",
    "stockswatch/crypto_strategy_replay.py": "ad7bc52e1e18963db9cd9fec8117712f5bc49259",
    "stockswatch/app.py": "0ceee579fc1e2e11d147aa6d7cd26eb2bb3aa67a",
    "stockswatch/catalog_intelligence.py": "1fd461a54043830823e61bb803a1555f35c8fe16",
    "stockswatch/asset_catalog.py": "56bc887f427db32609ce33e984ff28287799099a",
    "frontend/Dockerfile": "8b65d5297cc2a6c62cd87faf7146b1f371a40f6c",
    "frontend/nginx.conf": "a1f331956d24b5a0b3ddb68b7dca41a1a31b03ad",
    "frontend/package.json": "da43f8cafafdd49a02e482a55553765761086850",
    "tests/test_crypto_continuation_replay.py": "d51616b10d5ddd36fbfc101cec50a32e09fa7b2e",
    "tests/test_catalog_intelligence.py": "0790abc57258a5ee63f40700007ed7f6d1b4fb56",
}

# Run as root through SSH stdin; no /root shell profile or path assumptions.
REMOTE = r"""#!/usr/bin/env python3
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

stage, release = sys.argv[1:]
if not re.fullmatch(r'/tmp/stockswatch-sync\.[A-Za-z0-9]{6,20}', stage):
    raise SystemExit('DEFERRED: unrecognized uploaded staging directory')
if not re.fullmatch(r'[0-9a-f]{40}', release):
    raise SystemExit('DEFERRED: unrecognized pinned release')
project = 'autotrader-aruba-stockswatch'
short = release[:12]
store = Path('/opt/personal-plan/staging') / ('stockswatch-catalog-crypto-'+short)
pkg = None
pybin = '/opt/stockswatch/venv/bin/python'


def monitored_run(args, *, timeout=120, input=None):
    # Bounded subprocess with heartbeat; never print command args or secrets.
    marker=str(args[0]).rsplit('/',1)[-1]
    done=threading.Event()
    since=time.monotonic()
    def heartbeat():
        while not done.wait(15):
            print('RUNNING: '+marker+' operation continues; elapsed='+
                  str(int(time.monotonic()-since))+'s',flush=True)
    observer=threading.Thread(target=heartbeat,daemon=True)
    observer.start()
    try:
        return subprocess.run(args,input=input,stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,text=True,timeout=timeout)
    finally:
        done.set()
        observer.join(timeout=1)


def command(*args, input=None, timeout=100, quiet=False):
    p=monitored_run(args,input=input,timeout=timeout)
    if p.returncode:
        # Never dump resolved Compose config, Docker env, or broker credentials.
        # Offline unit failures are safe to display in abbreviated form.
        if len(args)>3 and args[0]=='docker' and args[1]=='run':
            print('OFFLINE_TEST_ERROR:',(p.stderr or p.stdout)[-1800:])
        raise RuntimeError('command_failed_' + str(args[0]).split('/')[-1] + '_' +
                           str(args[1]).replace(' ', '_')[:35] + '_' + str(p.returncode))
    return p.stdout.strip()


def dc(*args, timeout=120):
    return command('docker', *args, timeout=timeout)


def container(service):
    names=dc('ps','--format','{{.Names}}','--filter','label=com.docker.compose.project='+project,
             '--filter','label=com.docker.compose.service='+service).splitlines()
    if len(names)!=1:
        raise RuntimeError('expected_one_running_'+service)
    return names[0]


def inspect(name):
    return json.loads(dc('inspect',name))[0]


def broker_preflight(name):
    program='''from stockswatch.alpaca_crypto_paper import CryptoPaperClient
with CryptoPaperClient() as b:
    book=b.snapshot()
counts={"stock_positions":len(book["other_positions"]),
"stock_orders":len(book["other_open_orders"]),
"crypto_positions":len(book["positions"]),
"crypto_orders":len(book["orders"])}
print(counts)
if any(counts.values()):raise SystemExit(32)
'''
    try:
        print('PAPER_PREFLIGHT:', dc('exec','-i',name,pybin,'-c',program,timeout=70))
    except RuntimeError as exc:
        raise RuntimeError('BROKER_EXPOSURE_OR_VERIFICATION_FAILED; no services changed') from exc


def safe_extract(archive, dest):
    dest.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive,'r:gz') as t:
        for member in t.getmembers():
            n=Path(member.name)
            if (n.is_absolute() or '..' in n.parts or member.issym() or
                member.islnk() or member.isdev()):
                raise RuntimeError('payload_member_invalid')
        t.extractall(dest)


def check_routes_and_patch(current, expected):
    marker='@app.get("/api/stockswatch/status", dependencies=[Depends(authenticated)])'
    def block(s):
        start=s.find('@app.get("/api/stockswatch/catalog", dependencies=[Depends(authenticated)])')
        end=s.find(marker,start+1)
        if start<0 or end<0 or s.count(marker)!=1:
            raise RuntimeError('reviewed_api_route_markers_missing')
        return s[start:end]
    review=expected.read_text(encoding='utf-8')
    live=current.read_text(encoding='utf-8')
    addon=block(review)
    if live.count(marker)!=1:
        raise RuntimeError('existing_api_anchor_mismatch')
    start=live.find('@app.get("/api/stockswatch/catalog", dependencies=[Depends(authenticated)])')
    if start>=0:
        end=live.find(marker,start+1)
        if end<0:
            raise RuntimeError('existing_catalog_route_anchor_mismatch')
        live=live[:start]+addon+live[end:]
    else:
        live=live.replace(marker,addon+marker,1)
    if live.count('/api/stockswatch/catalog-evidence/{symbol}')!=1:
        raise RuntimeError('api_catalog_evidence_route_missing')
    ast.parse(live)
    current.write_text(live,encoding='utf-8')


def copy_running_source(name, source, target):
    dc('cp',name+':'+source,str(target))
    if not target.is_file():
        raise RuntimeError('running_api_source_unavailable')


def run_tests(image, data, db, src):
    mounts=[]
    for name in ('app.py','asset_catalog.py','catalog_intelligence.py',
                 'alpaca_crypto.py','alpaca_crypto_paper.py',
                 'crypto_continuation.py','crypto_strategy_replay.py'):
        mounts += ['--mount',f'type=bind,source={store / name},target={pkg / name},readonly']
    mounts += ['--mount',f'type=bind,source={src / "tests"},target=/opt/stockswatch-regression,readonly']
    base=['docker','run','--rm','--network','none','--read-only',
          '--tmpfs','/tmp:rw,nosuid,nodev,size=32m',
          '--mount',f'type=bind,source={data},target=/stockswatch-data,readonly',
          '--env','STOCKSWATCH_DB='+db,
          '--env','PYTHONDONTWRITEBYTECODE=1',
          *mounts,'--entrypoint',pybin,image]
    print('=== Offline regression checks (no network or broker orders) ===')
    for file in ('test_catalog_intelligence.py','test_crypto_continuation_replay.py'):
        result=command(*base,'-m','unittest','discover','-s',
                       '/opt/stockswatch-regression','-p',file,'-v',timeout=160)
        print('PASS:',file, result[-300:] if result else 'completed')
    print('=== Causal crypto replay with read-only historical ledger ===')
    print('REPLAY: analyzing completed crypto history, up to 480s; heartbeat every 15s',flush=True)
    result=monitored_run(base+['-m','stockswatch.crypto_strategy_replay','--json'],
                          timeout=480)
    reportfile=store/'crypto-replay.json'
    reportfile.write_text(result.stdout or '',encoding='utf-8')
    try:
        replay=json.loads(result.stdout)
    except (ValueError,TypeError):
        raise RuntimeError('replay_report_invalid; no cutover')
    if result.returncode not in (0,2):
        raise RuntimeError('crypto_replay_crashed; no cutover')
    if result.returncode==2 and replay.get('state')!='INSUFFICIENT_HISTORY':
        raise RuntimeError('crypto_replay_incomplete; no cutover')
    holdout=replay.get('candidate',{}).get('holdout',{})
    print('REPLAY:',{'state':replay.get('state'),
                     'eligible_symbols':replay.get('ready_symbols'),
                     'candidate_holdout_trades':holdout.get('trades'),
                     'profit_factor':holdout.get('profit_factor'),
                     'approved':replay.get('approved')})
    return replay.get('approved') is True


print('=== 1. Current Docker topology ===')
sw=container('stockswatch')
fe=container('frontend')
swc=inspect(sw)
fec=inspect(fe)
if not swc['State']['Running'] or not fec['State']['Running']:
    raise SystemExit('DEFERRED: existing services are not both running')
labels=swc['Config'].get('Labels') or {}
workdir=labels.get('com.docker.compose.project.working_dir','')
filenames=labels.get('com.docker.compose.project.config_files','').split(',')
if not workdir.startswith('/') or not Path(workdir).is_dir():
    raise SystemExit('DEFERRED: unable to verify existing compose working directory')
if not filenames or any(not f.startswith('/') or not Path(f).is_file() for f in filenames):
    raise SystemExit('DEFERRED: unable to verify active compose configuration')
if (fec['Config'].get('Labels') or {}).get('com.docker.compose.project.working_dir')!=workdir:
    raise SystemExit('DEFERRED: frontend and stockswatch have different compose provenance')
if not swc['HostConfig'].get('ReadonlyRootfs'):
    raise SystemExit('DEFERRED: expected read-only rootfs; runtime changed')
if not Path('/usr/bin/docker').exists():
    raise SystemExit('DEFERRED: docker CLI unavailable')
base=['docker','compose','--project-directory',workdir,'--project-name',project]
for f in filenames:
    base.extend(['-f',f])

stocks=dc('exec',sw,pybin,'-c','from stockswatch import alpaca_crypto as x; print(len(x.PAIRS),len(x.EXECUTION_PAIRS))')
if stocks.strip()!='70 33':
    raise SystemExit('DEFERRED: current crypto universe does not match 70 / 33')
pkgstr=dc('exec',sw,pybin,'-c','from stockswatch import alpaca_crypto as a;from pathlib import Path;print(Path(a.__file__).parent)')
if not re.fullmatch(r'/[A-Za-z0-9._/-]+/stockswatch',pkgstr):
    raise SystemExit('DEFERRED: unexpected StocksWatch package path')
pkg=Path(pkgstr)
db=dc('exec',sw,pybin,'-c','from stockswatch.storage import DB_PATH;print(DB_PATH)')
if not re.fullmatch(r'/stockswatch-data/[A-Za-z0-9._-]+\.sqlite3',db):
    raise SystemExit('DEFERRED: current financial ledger path not recognized')
data_paths=[m['Source'] for m in swc['Mounts'] if m['Destination']=='/stockswatch-data' and m['Type']=='bind']
if len(data_paths)!=1:
    raise SystemExit('DEFERRED: existing persistent paper ledger bind missing')
data=Path(data_paths[0])
if not (data/Path(db).name).is_file() or not (data/'stockswatch-catalog.sqlite3').is_file():
    raise SystemExit('DEFERRED: stock ledger or downloaded catalog database missing')
if shutil.disk_usage(data).free<3*1024**3:
    raise SystemExit('DEFERRED: at least 3GB free disk required')
version=(fec['Config'].get('Labels') or {}).get('org.opencontainers.image.version')
if version not in (None,'4.9.10-rc.1'):
    raise SystemExit('DEFERRED: frontend version has changed unexpectedly: '+str(version))

print('=== 2. Verify account has no open positions or orders ===')
broker_preflight(sw)

print('=== 3. Extract exact pinned files and preserve running API ===')
store.mkdir(parents=True,exist_ok=True)
src=store/'source'
safe_extract(Path(stage)/'payload.tgz',src)
for name in ('asset_catalog.py','catalog_intelligence.py','alpaca_crypto.py',
             'alpaca_crypto_paper.py','crypto_continuation.py',
             'crypto_strategy_replay.py'):
    shutil.copy2(src/'stockswatch'/name,store/name)
    os.chmod(store/name,0o644)
copy_running_source(sw,str(pkg/'app.py'),store/'app.py')
check_routes_and_patch(store/'app.py',src/'stockswatch'/'app.py')
compile((store/'app.py').read_text(),str(store/'app.py'),'exec')
for name in ('asset_catalog.py','catalog_intelligence.py','alpaca_crypto.py',
             'alpaca_crypto_paper.py','crypto_continuation.py','crypto_strategy_replay.py'):
    compile((store/name).read_text(),str(store/name),'exec')

swimg=swc['Image'];feimg=fec['Image']
if not (re.fullmatch(r'sha256:[0-9a-f]{64}',swimg) and
        re.fullmatch(r'sha256:[0-9a-f]{64}',feimg)):
    raise SystemExit('DEFERRED: unable to pin existing immutable images')
swtag='local/stockswatch-universe-baseline:'+short
fetag='local/stockswatch-universe-frontend-rollback:'+short
newtag='local/stockswatch-universe-frontend:'+short
dc('tag',swimg,swtag)
dc('tag',feimg,fetag)

approved=run_tests(swtag,data,db,src)

print('=== 4. Build the full revised frontend image ===')
# Build only, no running services altered until successful verification.
try:
    outcome=command('docker','build','--pull=false',
                    '--build-arg','RELEASE_VERSION=4.9.10-rc.1',
                    '--build-arg','RELEASE_COMMIT='+release,
                    '-t',newtag,'-f',str(src/'frontend'/'Dockerfile'),
                    str(src/'frontend'),timeout=900)
except Exception as exc:
    raise SystemExit('DEFERRED: frontend build failed (no service changed): '+str(exc))
if dc('image','inspect','-f','{{index .Config.Labels "org.opencontainers.image.revision"}}',newtag)!=release:
    raise SystemExit('DEFERRED: frontend image provenance mismatch')

print('=== 5. Validate Compose mounts; preserve OCO and crypto files ===')
volumes=[]
for name in ('app.py','asset_catalog.py','catalog_intelligence.py',
             'alpaca_crypto.py','alpaca_crypto_paper.py','crypto_continuation.py',
             'crypto_strategy_replay.py'):
    volumes.append({'type':'bind','source':str(store/name),
                    'target':str(pkg/name),'read_only':True})
override=store/'compose.stockswatch-crypto-catalogue.json'
override.write_text(json.dumps({'services':{
    'stockswatch':{'image':swtag,'pull_policy':'never','volumes':volumes},
    'frontend':{'image':newtag,'pull_policy':'never'}
}},indent=2),encoding='utf-8')
full=base+['-f',str(override)]
resolved=json.loads(command(*full,'config','--format','json',timeout=70))['services']
sc=resolved.get('stockswatch') or {}
fc=resolved.get('frontend') or {}
if sc.get('read_only') is not True:
    raise SystemExit('DEFERRED: rootfs read-only setting lost')
newvols=sc.get('volumes') or []
newtarget={x.get('target'):x for x in newvols}
if '/stockswatch-data' not in newtarget:
    raise SystemExit('DEFERRED: persistent paper ledger mount missing')
for x in volumes:
    v=newtarget.get(x['target'],{})
    if v.get('source')!=x['source'] or v.get('read_only') is not True:
        raise SystemExit('DEFERRED: intended read-only source overlay missing')
for old in swc['Mounts']:
    dest=old['Destination']
    if dest.startswith('/opt/stockswatch/') or dest=='/stockswatch-data':
        if dest not in newtarget:
            raise SystemExit('DEFERRED: previously mounted stock/crypto file was lost: '+dest)
for old in fec['Mounts']:
    if not any(x.get('target')==old['Destination'] for x in fc.get('volumes',[])):
        raise SystemExit('DEFERRED: frontend mount changed unexpectedly')
print('PASS: source mounts, stock ledger, existing OCO mounts and read-only rootfs retained')

print('=== 6. Final GET-only broker check immediately before cutover ===')
broker_preflight(sw)

print('=== 7. Recreate only shared StocksWatch service and its frontend ===')
try:
    command(*full,'up','-d','--no-deps','--no-build','--force-recreate',
            'stockswatch','frontend',timeout=240)
except Exception as exc:
    # Preserve original Compose configs; do not clear any pending orders.
    rollback=store/'rollback.images.json'
    rollback.write_text(json.dumps({'services':{
        'stockswatch':{'image':swtag,'pull_policy':'never'},
        'frontend':{'image':fetag,'pull_policy':'never'}
    }}),encoding='utf-8')
    try:
        command(*base,'-f',str(rollback),'up','-d','--no-deps','--no-build',
                '--force-recreate','stockswatch','frontend',timeout=240)
    except Exception:
        pass
    raise SystemExit('FAIL: cutover failed, rollback attempted; inspect Docker status: '+str(exc))

print('=== 8. Verify running 70-crypto / 14k-stock-backed research endpoints ===')
name=container('stockswatch')
front=container('frontend')
if inspect(front)['Image']!=dc('image','inspect','-f','{{.Id}}',newtag):
    raise SystemExit('FAIL: frontend candidate image not active')
check='''from stockswatch import alpaca_crypto as ac, catalog_intelligence as ci, asset_catalog
from stockswatch.app import app
assert len(ac.PAIRS)==70 and len(ac.EXECUTION_PAIRS)==33
assert any(r.path=="/api/stockswatch/catalog" for r in app.routes)
assert any(r.path=="/api/stockswatch/catalog-evidence/{symbol}" for r in app.routes)
assert any(r.path=="/api/stockswatch/catalog-top" for r in app.routes)
assert asset_catalog.report()["active"]>102
print("PASS: 70 crypto pairs; 33 USD candidates; asset catalogue",asset_catalog.report()["active"])
'''
print(dc('exec',name,pybin,'-c',check,timeout=75))
# Approval comes ONLY from the offline replay; no paper order flags altered.
flag=data/'alpaca-crypto-continuation-enabled'
if approved:
    flag.write_text('alpaca-crypto-continuation-v1\n',encoding='utf-8')
    print('CRYPTO: replay-qualified continuation entries ENABLED for existing paper-only execution')
else:
    if flag.exists():flag.unlink()
    print('CRYPTO: continuation entries NOT APPROVED by replay; original breakout strategy active')

print('=== 9. Start separate paced STOCK research/SEC/AI queue ===')
wrapper=store/'run-stock-intelligence.sh'
wrapper.write_text('''#!/usr/bin/env bash
set -euo pipefail
PROJECT='autotrader-aruba-stockswatch'
C=$(docker ps --format '{{.Names}}' --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=stockswatch')
[[ -n "$C" && "$C" != *$'\\n'* ]] || exit 2
exec docker exec "$C" /opt/stockswatch/venv/bin/python -m stockswatch.catalog_intelligence
''',encoding='utf-8')
os.chmod(wrapper,0o755)
service=Path('/etc/systemd/system/stockswatch-catalog-intelligence.service')
timer=Path('/etc/systemd/system/stockswatch-catalog-intelligence.timer')
service.write_text('''[Unit]
Description=Paced read-only-broker Alpaca stock catalogue research, SEC and budget-capped AI
Wants=docker.service
After=docker.service
[Service]
Type=oneshot
ExecStart=/usr/bin/flock -n /run/stockswatch-catalog-intelligence.lock /usr/bin/timeout 240 '''+str(wrapper)+'''
TimeoutStartSec=270
''',encoding='utf-8')
timer.write_text('''[Unit]
Description=Paced full-stock-universe market intelligence worker
[Timer]
OnBootSec=3min
OnUnitInactiveSec=5min
Unit=stockswatch-catalog-intelligence.service
[Install]
WantedBy=timers.target
''',encoding='utf-8')
command('systemctl','daemon-reload')
command('systemctl','enable','--now','stockswatch-catalog-intelligence.timer')
# Startup is bounded. If remote SEC/Gemini is unavailable, per-source state
# stays explicit; existing stock and crypto trading continue unaffected.
try:
    command('systemctl','start','stockswatch-catalog-intelligence.service',timeout=250)
    print(dc('exec',name,pybin,'-c',
             'from stockswatch.catalog_intelligence import report;'
             'import json;print(json.dumps(report(),sort_keys=True))',timeout=40))
except Exception as exc:
    print('RESEARCH_WORKER: scheduled, initial attempt deferred:',type(exc).__name__)

notes=store/'deployment.json'
notes.write_text(json.dumps({'release':release,'compose_original':filenames,
    'compose_override':str(override),'baseline_stock_image':swimg,
    'baseline_frontend_image':feimg,'paper_orders_unchanged':True,
    'replay_approved':approved,'catalogue_data':str(data)},indent=2))
print('SUCCESS: deployed pinned release',release)
print('VIEW: StocksWatch > Browse all Alpaca tickers; AlpacaCrypto > Scanner')
print('NOTES: 102 trading symbols remain the execution allowlist; added stock research is staged and paced.')
print('IMPORTANT: Future Compose deployments must retain this override:',override)
"""


def run(*args: str, **kwargs):
    kwargs.setdefault("check", True)
    return subprocess.run(args, **kwargs)


def safe_unpack(source: Path, folder: Path):
    with tarfile.open(source, "r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise RuntimeError("GitHub release archive is empty")
        for m in members:
            name = Path(m.name)
            if name.is_absolute() or ".." in name.parts or m.issym() or m.islnk() or m.isdev():
                raise RuntimeError("Unsafe GitHub tar archive member")
        archive.extractall(folder)


def main():
    if not shutil.which("git") or not shutil.which("curl") or not shutil.which("ssh") or not shutil.which("scp"):
        raise RuntimeError("Mac requires git, curl, ssh, and scp")
    print("=== Download immutable stock+crypto UI/research release ===", flush=True)
    with tempfile.TemporaryDirectory(prefix="stockswatch-sync-") as tmp:
        root=Path(tmp)
        tgz=root/"github.tgz"
        # Visible curl progress with a bounded timeout.
        run("curl", "-fL", "--progress-bar", "--show-error", "--retry", "3",
            "--retry-delay", "2", "--connect-timeout", "12", "--max-time", "120",
            f"https://api.github.com/repos/{REPO}/tarball/{RELEASE}", "-o", str(tgz))
        unpack=root/"unpack";unpack.mkdir()
        safe_unpack(tgz,unpack)
        roots=[d for d in unpack.iterdir() if d.is_dir() and (d/"frontend").is_dir()]
        if len(roots)!=1:
            raise RuntimeError("Unexpected GitHub source release structure")
        source=roots[0]
        for rel,blob in BLOBS.items():
            target=source/rel
            if not target.is_file() or target.is_symlink():
                raise RuntimeError("Missing or unsafe source: "+rel)
            actual=subprocess.check_output(["git","hash-object",str(target)],text=True).strip()
            if actual!=blob:
                raise RuntimeError("SHA mismatch: "+rel)
        print(f"PASS: {len(BLOBS)} reviewed immutable blobs verified at {RELEASE}",flush=True)
        payload=root/"payload.tgz"
        with tarfile.open(payload,"w:gz") as tar:
            tar.add(source/"frontend",arcname="frontend")
            (root/"chosen").mkdir()
            for rel in [p for p in BLOBS if p.startswith("stockswatch/") or p.startswith("tests/")]:
                tar.add(source/rel,arcname=rel)
        remote=run("ssh","-o","ConnectTimeout=15","aruba-vps",
                   "mktemp -d /tmp/stockswatch-sync.XXXXXXXX",capture_output=True,text=True).stdout.strip()
        if not re.fullmatch(r"/tmp/stockswatch-sync\.[A-Za-z0-9]{6,20}",remote):
            raise RuntimeError("Unexpected remote staging location")
        print('=== Uploading release to Aruba (SCP progress visible) ===',flush=True)
        run("scp","-o","ConnectTimeout=15","-o","ServerAliveInterval=30",
            str(payload),f"aruba-vps:{remote}/payload.tgz")
        print("PASS: staged reviewed frontend, API, stock research and crypto modules",flush=True)
        print("=== Running safe server preflight, offline tests, replay and deployment ===",flush=True)
        # Stream stage messages as soon as they are produced.
        result=subprocess.run(["ssh","-T","-o","ConnectTimeout=15",
                               "-o","ServerAliveInterval=30",
                               "-o","ServerAliveCountMax=30","aruba-vps",
                               "sudo","python3","-u","-",remote,RELEASE],
                              input=REMOTE,text=True)
        if result.returncode:
            raise SystemExit("Remote deployment deferred/failed (exit "+str(result.returncode)+"). Check the output above.")


if __name__=="__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print("FAILED: required transfer or verification command exited",exc.returncode,file=sys.stderr)
        sys.exit(3)
    except Exception as exc:
        print("FAILED:",str(exc),file=sys.stderr)
        sys.exit(3)