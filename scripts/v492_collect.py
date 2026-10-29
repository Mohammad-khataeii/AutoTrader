"""Read-only focused ledger/candle export. Remote stdout only; no remote files.

Financial tables are complete; heavy whole-history states/signals are excluded.
Entry evidence lives in original orders. Snapshots differ across databases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

REMOTE = r'''
pg=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+PROJECT,'--filter','label=com.docker.compose.service=postgres']).decode().strip()
assert re.fullmatch('[a-f0-9]+',pg)
registry=next(stream_query(pg,OFFICIAL,"SELECT json_build_object('primary',(SELECT payload_json::json FROM system_state WHERE key='personal_paper_v47'),'active',(SELECT payload_json::json FROM system_state WHERE key='personal_paper_active_profile'),'shadows',(SELECT json_agg(json_build_object('database_name',database_name,'state',state,'manifest',manifest_json::json,'created_at',created_at)) FROM shadow_experiments))"))
names=[OFFICIAL,registry['primary']['database_name'],*[r['database_name'] for r in registry['shadows']]]
assert len(set(names))==len(names)==17
out=gzip.GzipFile(fileobj=sys.stdout.buffer,mode='wb',mtime=0)
def emit(r):out.write((json.dumps(sanitize(r),separators=(',',':'))+'\n').encode());out.flush()
emit({'type':'header','registry':registry,'at':datetime.now(timezone.utc).isoformat(),'read_only':True,'project':PROJECT,'remote_files_created':False})
for name in names:
 for table in ('orders','fills','positions','exit_plans','exit_targets','exit_intents','financial_journal','accounts'):
  for row in stream_query(pg,name,'SELECT row_to_json(t) FROM '+table+' t ORDER BY created_at'):
   emit({'database':name,'section':table,'row':row})
 if name==registry['primary']['database_name']:
  for row in stream_query(pg,name,"SELECT row_to_json(t) FROM (SELECT * FROM system_state WHERE state='EXIT_ASSESSMENT' OR key IN ('position_monitor','paper_scan','worker') ORDER BY key)t"):
   emit({'database':name,'section':'states','row':row})
 emit({'type':'database_complete','database':name})
emit({'type':'complete','status':'PASS'});out.close()
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import os
    os.umask(0o077)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name('v491_diagnostic_remote.py').read_text()
    source = source.replace("if __name__=='__main__':", "if False:")+'\n'+REMOTE
    with args.output.open('xb') as out:
        r = subprocess.run(['ssh', '-T', 'aruba-vps', 'python3', '-'], input=source.encode(), stdout=out, stderr=subprocess.PIPE, check=False)
    if r.returncode:
        from v491_diagnostic_remote import sanitize
        raise RuntimeError(str(sanitize(r.stderr.decode()))[-1500:])
    import gzip
    with gzip.open(args.output, 'rt') as f:
        last = None
        for line in f:
            last = json.loads(line)
    if last != {'type': 'complete', 'status': 'PASS'}:
        raise ValueError('incomplete_export')
    print(json.dumps({'status': 'PASS', 'read_only': True, 'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
