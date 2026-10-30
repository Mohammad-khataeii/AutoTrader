"""Bounded read-only Aruba exports; verified pages, no remote files or credentials."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

BASE = Path(__file__).parent


def request(body: str, target: Path) -> list[dict[str, Any]]:
    source = (BASE/'v491_diagnostic_remote.py').read_text().replace("if __name__=='__main__':", 'if False:')
    source += "\nout=gzip.GzipFile(fileobj=sys.stdout.buffer,mode='wb',mtime=0)\ndef emit(v):out.write((json.dumps(sanitize(v),separators=(',',':'))+'\\n').encode())\n"
    source += "pg=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+PROJECT,'--filter','label=com.docker.compose.service=postgres']).decode().strip()\n"+body+"\nemit({'type':'complete','status':'PASS'});out.close()\n"
    for attempt in range(3):
        with target.open('xb') as f:
            result = subprocess.run(['ssh','-T','-o','ControlMaster=no','-o','ControlPath=none','-o','ServerAliveInterval=10','aruba-vps','python3','-'],input=source.encode(),stdout=f,stderr=subprocess.PIPE,check=False)
        try:
            with gzip.open(target,'rt') as f: rows=[json.loads(line,parse_float=str) for line in f]
            if result.returncode or rows[-1]!={'type':'complete','status':'PASS'}:raise ValueError('incomplete_readonly_page')
            return rows[:-1]
        except (OSError,EOFError,ValueError,IndexError):
            target.rename(target.with_suffix(target.suffix+f'.failed-{attempt}'))
    raise RuntimeError('read_only_export_failed_no_remote_mutation')


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    os.umask(0o077);root=args.output;root.mkdir(parents=True,exist_ok=False)
    registry=request("emit(next(stream_query(pg,OFFICIAL,\"SELECT json_build_object('primary',(SELECT payload_json::json FROM system_state WHERE key='personal_paper_v47'),'shadows',(SELECT json_agg(json_build_object('database_name',database_name,'manifest',manifest_json::json,'state',state)) FROM shadow_experiments))\")))",root/'registry.jsonl.gz')[0]
    db=registry['primary']['database_name'];now=datetime.now(UTC);since=(now-timedelta(hours=48)).isoformat();until=now.isoformat();cursor=['1970-01-01T00:00:00+00:00',''];count=0
    header={'type':'header','registry':registry,'since':since,'until':until,'read_only':True,'remote_files_created':False,'complete_sections':['signals','candles','financial']}
    (root/'header.json').write_text(json.dumps(header,indent=2)+'\n')
    with gzip.open(root/'signals.jsonl.gz','wt') as out:
        out.write(json.dumps(header)+'\n')
        for page in range(1000):
            sql=f"SELECT row_to_json(t) FROM (SELECT signal_id,strategy_id,symbol,created_at,payload_json FROM strategy_signals WHERE created_at>='{since}' AND created_at<='{until}' AND (created_at,signal_id)>('{cursor[0]}','{cursor[1]}') ORDER BY created_at,signal_id LIMIT 100)t"
            rows=request(f"for row in stream_query(pg,{db!r},{sql!r}):emit(row)",root/f'signals-{page:04}.jsonl.gz')
            for row in rows:out.write(json.dumps(row,separators=(',',':'))+'\n')
            count+=len(rows)
            if not rows:break
            cursor=[rows[-1]['created_at'],rows[-1]['signal_id']]
            if page%10==0:print(json.dumps({'signal_pages':page+1,'signals':count}),flush=True)
        else:raise RuntimeError('bounded_signal_page_capacity')
    sql="SELECT row_to_json(t) FROM (SELECT symbol,timeframe,timestamp,open,high,low,close,volume,source FROM market_candles WHERE timeframe='5m' AND timestamp>='2026-10-23T00:00:00+00:00' AND timestamp<='"+until+"' AND source LIKE 'revolut-x%' ORDER BY symbol,timestamp,id)t"
    request(f"for row in stream_query(pg,{db!r},{sql!r}):emit(row)",root/'candles.jsonl.gz')
    names=['autotrader_aruba_staging',db,*[r['database_name'] for r in registry['shadows']]];assert len(set(names))==17
    body='names='+repr(names)+"\nfor name in names:\n for table in ('orders','fills','positions','exit_plans','exit_targets','exit_intents','financial_journal','accounts'):\n  for row in stream_query(pg,name,'SELECT row_to_json(t) FROM '+table+' t ORDER BY created_at'):emit({'database':name,'section':table,'row':row})\n"
    request(body,root/'financial.jsonl.gz')
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.gz') if '.failed-' not in p.name}
    (root/'export-manifest.json').write_text(json.dumps({'status':'PASS','signals':count,'databases':17,'files':files,'read_only':True,'remote_files_created':False},indent=2)+'\n')
    print(json.dumps({'status':'PASS','signals':count,'databases':17}),flush=True)


if __name__=='__main__':main()
