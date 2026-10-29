"""Local coordinator for a bounded, read-only Aruba audit stream."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import os
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


def summarize(path: Path) -> tuple[dict,str]:
    header=None;complete=None;counts=Counter();hourly=defaultdict(Counter);omissions=Counter()
    with gzip.open(path,'rt') as source:
        for line in source:
            r=json.loads(line,parse_float=str)
            if r.get('type')=='header':header=r;continue
            if r.get('type')=='complete':complete=r;continue
            if r.get('section'):
                section=r['section'];counts[section]+=1;v=r['row']
                if isinstance(v,dict) and isinstance(v.get('payload_json'),dict) and v['payload_json'].get('payload_omitted'):
                    omissions[r['database']+':'+section]+=1
                if header and r['database']==header['registry']['primary']['database_name']:
                    stamp=str(v.get('created_at') or v.get('updated_at') or '')[:13]
                    if stamp:hourly[stamp][section]+=1
    if not header or not complete or complete.get('status')!='PASS':raise ValueError('incomplete_audit_stream')
    if header.get('project')!='autotrader-aruba-test' or header.get('read_only') is not True:raise ValueError('unexpected_audit_scope')
    manifest={'status':'PASS','schema':header['schema'],'observed_at':header['observed_at'],'since':header['since'],'until':header['until'],'hours':header['hours'],'databases':len(complete['counts']),'counts':dict(counts),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'remote_mutations':False,'payload_omissions':dict(omissions),'completeness':'PARTIAL_EXPLICIT_STATE_PAYLOADS' if omissions else 'FULL_STREAM','limits':header['cutoff_limit']}
    lines=['# Read-only hourly audit','',f"Window: {header['since']} through {header['until']}",'','Each database has a separate repeatable-read snapshot. Recorded decisions are not independent market episodes.','']
    for hour,values in sorted(hourly.items()):lines.append(f"- {hour}:00 UTC: "+', '.join(f'{k}={v}' for k,v in sorted(values.items())))
    lines.extend(['',f'Explicit payload omissions: {dict(omissions)}. These records must not be treated as complete evidence.','No credentials or full environments were read; no remote files or database mutations were created.'])
    return manifest,'\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--hours',type=int,choices=[12,24,48],default=12);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--input',type=Path)
    args=parser.parse_args();os.umask(0o077);args.output.mkdir(mode=0o700,exist_ok=False)
    path=args.output/'diagnostic.jsonl.gz'
    if args.input:
        # Read legacy local bundles without issuing the unsafe remote query.
        with gzip.open(args.input,'rt') as f:first=json.loads(f.readline())
        if 'databases' in first:
            from v49_diagnostics import hourly
            (args.output/'hourly-summary.md').write_text(hourly(first));print(json.dumps({'status':'PASS','legacy_local_summary':True,'remote_mutations':False}));return
        path.write_bytes(args.input.read_bytes())
    else:
        source=Path(__file__).with_name('v491_diagnostic_remote.py').read_bytes()
        with path.with_suffix('.gz.part').open('wb') as target:
            result=subprocess.run(['ssh','-T','aruba-vps','python3','-','--hours',str(args.hours)],input=source,stdout=target,stderr=subprocess.PIPE,check=False)
        if result.returncode:
            from v491_diagnostic_remote import sanitize
            (args.output/'collector-error.txt').write_text(str(sanitize(result.stderr.decode())))
            raise RuntimeError('Read-only stream failed; incomplete private artifact retained')
        path.with_suffix('.gz.part').rename(path)
    manifest,summary=summarize(path);(args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');(args.output/'hourly-summary.md').write_text(summary)
    print(json.dumps({'status':'PASS','local_output':str(args.output.resolve()),'databases':manifest['databases'],'remote_mutations':False,'completeness':manifest['completeness']}))


if __name__=='__main__':main()
