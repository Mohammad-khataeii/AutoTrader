"""Host-Docker resource regression: >512 MiB data must not become one SQL value."""
import json
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4


def test_large_audit_stream_under_postgres_memory_cap():
    sys.path.insert(0,str(Path('scripts').resolve()))
    from v491_diagnostic_remote import stream_query
    token='autotrader-v491-audit-test-'+uuid4().hex[:8];volume=token+'-data';database='autotrader_shadow_'+uuid4().hex
    def run(args):return subprocess.run(args,capture_output=True,check=True).stdout
    run(['docker','volume','create','--label','autotrader.v491.resource-test=true',volume])
    started=False
    try:
        run(['docker','run','-d','--name',token,'--label','autotrader.v491.resource-test=true','--network','none','--memory','512m','-v',volume+':/var/lib/postgresql/data','-e','POSTGRES_USER=autotrader','-e','POSTGRES_DB=postgres','-e','POSTGRES_HOST_AUTH_METHOD=trust','postgres:16-alpine']);started=True
        for _ in range(90):
            if subprocess.run(['docker','exec',token,'pg_isready','-U','autotrader'],capture_output=True,check=False).returncode==0:break
            time.sleep(.25)
        else:raise AssertionError('Isolated resource-test database unavailable')
        run(['docker','exec',token,'createdb','-U','autotrader',database])
        sql="CREATE TABLE audit_probe(id integer PRIMARY KEY,payload text);ALTER TABLE audit_probe ALTER COLUMN payload SET STORAGE EXTERNAL;INSERT INTO audit_probe SELECT g,repeat(md5(g::text),32768) FROM generate_series(1,600) g"
        run(['docker','exec',token,'psql','-qAt','-v','ON_ERROR_STOP=1','-U','autotrader','-d',database,'-c',sql])
        rows=0;total=0
        for record in stream_query(token,database,'SELECT row_to_json(t) FROM (SELECT id,payload FROM audit_probe ORDER BY id)t'):
            rows+=1;total+=len(record['payload']);assert record['id']==rows
        assert rows==600 and total==600*1024**2
        state=json.loads(run(['docker','inspect','--format','{{json .State}}',token]))
        assert state['Running'] and not state['OOMKilled']
        assert int(run(['docker','inspect','--format','{{.HostConfig.Memory}}',token]))==512*1024**2
    finally:
        if started:subprocess.run(['docker','rm','-f',token],capture_output=True,check=True)
        subprocess.run(['docker','volume','rm',volume],capture_output=True,check=True)
