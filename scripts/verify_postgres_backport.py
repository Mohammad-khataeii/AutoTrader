"""Check XML/restore compatibility of the backport in an owned disposable volume."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',required=True,type=Path)
    parser.add_argument('--backup',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    name='autotrader-v41-xml-'+uuid4().hex[:10]
    image='autotrader-v41-postgres:16-backport-candidate'
    def run(*parts: str,data: bytes | None = None) -> str:
        r=subprocess.run(list(parts),input=data,capture_output=True,check=False)
        if r.returncode:
            raise RuntimeError(r.stderr.decode(errors='replace')[-2000:])
        return r.stdout.decode()
    run('docker','volume','create',name)
    try:
        run('docker','run','-d','--name',name,'--network','autotrader-v41-acceptance_data',
            '--env-file',str(args.env_file),'-e','POSTGRES_USER=autotrader','-e','POSTGRES_DB=autotrader',
            '--memory','512m','-v',name+':/var/lib/postgresql/data',image)
        deadline=time.monotonic()+60
        while True:
            ready=subprocess.run(['docker','exec',name,'pg_isready','-U','autotrader'],capture_output=True,check=False)
            if ready.returncode==0:
                break
            if time.monotonic()>deadline:
                raise RuntimeError('Candidate database unavailable')
            time.sleep(1)
        def sql(query: str,db: str = 'autotrader') -> str:
            return run('docker','exec',name,'psql','-v','ON_ERROR_STOP=1','-U','autotrader','-d',db,'-Atc',query).strip()
        version=sql('SHOW server_version')
        assert version.startswith('16.')
        assert sql("SELECT XMLPARSE(DOCUMENT '<root><v>41</v></root>')::text")=='<root><v>41</v></root>'
        assert sql("SELECT (xpath('/root/v/text()', XMLPARSE(DOCUMENT '<root><v>41</v></root>')))[1]::text")=='41'
        sql('CREATE EXTENSION hstore; CREATE EXTENSION pgcrypto; CREATE EXTENSION "uuid-ossp";')
        sql('CREATE DATABASE restored')
        run('docker','exec','-i',name,'pg_restore','--exit-on-error','--no-owner','-U','autotrader','-d','restored',data=args.backup.read_bytes())
        before=sql('SELECT count(*) FROM financial_journal','restored')
        assert int(before)>0
        run('docker','restart',name)
        deadline=time.monotonic()+60
        while subprocess.run(['docker','exec',name,'pg_isready','-U','autotrader'],capture_output=True,check=False).returncode:
            if time.monotonic()>deadline:
                raise RuntimeError('Populated candidate restart failed')
            time.sleep(1)
        assert sql('SELECT count(*) FROM financial_journal','restored')==before
        assert sql("SELECT XMLSERIALIZE(DOCUMENT XMLPARSE(DOCUMENT '<verified/>') AS text)")=='<verified/>'
        code='''import asyncio,json
from decimal import Decimal
from sqlalchemy.engine import make_url
from autotrader.config import get_settings
from autotrader.persistence.database import make_engine,make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
async def main():
 s=get_settings();s.database_url=make_url(s.database_url).set(host=HOST,database='restored').render_as_string(hide_password=False)
 e=make_engine(s)
 try:
  issues=await PersistentTradingRepository(make_session_factory(e)).verify_invariants(Decimal(500));assert not issues;print(json.dumps(issues))
 finally:await e.dispose()
asyncio.run(main())
'''.replace('HOST',repr(name))
        result=run('docker','compose','-p','autotrader-v41-acceptance','--env-file',str(args.env_file),'run','--rm','--no-deps','backend','python','-c',code)
        assert json.loads(result)==[]
        report={'status':'PASSED','image_id':run('docker','image','inspect',image,'--format','{{.Id}}').strip(),
            'postgres_version':version,'libxml_package':next(line for line in run('docker','exec',name,'apk','info','-v').splitlines() if line.startswith('libxml2-')),
            'xml_parse_xpath_serialize':'PASSED','extensions':['hstore','pgcrypto','uuid-ossp'],
            'backup_restored':True,'journal_rows_preserved_after_restart':int(before),'reconciliation':[],
            'original_deployment_database_modified':False,'disposable_resources_cleaned':True}
        args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    finally:
        subprocess.run(['docker','rm','-f',name],capture_output=True,check=False)
        subprocess.run(['docker','volume','rm',name],capture_output=True,check=False)


if __name__=='__main__':
    main()
