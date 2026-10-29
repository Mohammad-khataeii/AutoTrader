"""Verify final-postmaster readiness in a uniquely owned, network-isolated clone."""
import argparse
import hashlib
import importlib.util
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4


def main(output: Path) -> None:
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('restore_startup',root/'deploy/staging_backup.py')
    backup=importlib.util.module_from_spec(spec);spec.loader.exec_module(backup)
    token='autotrader-v491-startup-'+uuid4().hex[:8];volume=token+'-data'
    output.mkdir(mode=0o700,exist_ok=False)
    init=output/'bootstrap-delay.sql';init.write_text('SELECT pg_sleep(4);\n');init.chmod(0o644)
    def run(args):return subprocess.check_output(args,stderr=subprocess.STDOUT)
    run(['docker','volume','create','--label','autotrader.restore-startup='+token,volume])
    run(['docker','run','-d','--name',token,'--network','none','--memory','512m','--cpus','1',
         '--label','autotrader.restore-startup='+token,'-v',volume+':/var/lib/postgresql/data',
         '-v',str(init.resolve())+':/docker-entrypoint-initdb.d/hold.sql:ro',
         '-e','POSTGRES_USER=autotrader','-e','POSTGRES_DB=postgres','-e','POSTGRES_HOST_AUTH_METHOD=trust','postgres:16-alpine'])
    (output/'owned-resources.json').write_text(json.dumps({'container':token,'volume':volume,'network':'none','host_ports':[]},indent=2)+'\n')
    observed=False
    for _ in range(120):
        socket=subprocess.run(['docker','exec',token,'pg_isready','-U','autotrader','-d','postgres'],capture_output=True)
        tcp=subprocess.run(['docker','exec',token,'pg_isready','-h','127.0.0.1','-U','autotrader','-d','postgres'],capture_output=True)
        if socket.returncode==0 and tcp.returncode!=0:observed=True;break
        time.sleep(.05)
    assert observed,'temporary_bootstrap_phase_not_observed'
    start=time.monotonic();backup.wait_restore_postgres(token);elapsed=time.monotonic()-start
    pid=run(['docker','exec',token,'head','-n','1','/var/lib/postgresql/data/postmaster.pid']).decode().strip();assert pid=='1'
    run(['docker','exec',token,'createdb','-h','127.0.0.1','-U','autotrader','autotrader_acceptance_startup_proof'])
    assert run(['docker','exec',token,'psql','-h','127.0.0.1','-U','autotrader','-d','autotrader_acceptance_startup_proof','-qAt','-c','SELECT 1']).strip()==b'1'
    meta=json.loads(run(['docker','inspect',token]))[0];assert not meta['State']['OOMKilled'] and meta['Config']['Labels']['autotrader.restore-startup']==token
    result={'status':'PASS','bootstrap_socket_ready_while_tcp_unavailable':True,'new_helper_waited_for_final_tcp':True,
            'final_postmaster_pid':1,'createdb_after_final_readiness':'PASS','wait_seconds':elapsed,
            'memory_limit_bytes':512*1024**2,'cpu_limit':1,'network':'none','host_ports':[],
            'financial_data_used':False,'live_services_modified':False,
            'helper_sha256':hashlib.sha256((root/'deploy/staging_backup.py').read_bytes()).hexdigest(),
            'probe_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    run(['docker','rm','-f',token]);run(['docker','volume','rm',volume]);result['owned_resources_removed']=True
    (output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    main(parser.parse_args().output)
