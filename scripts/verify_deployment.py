"""Executable proof F: running services, authenticated controls and volume restart.

Use only with an explicitly selected Compose project. Never removes volumes.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import httpx


def main()->None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--env-file',required=True,type=Path)
    parser.add_argument('--project',required=True)
    parser.add_argument('--restart',action='store_true')
    args=parser.parse_args()
    values=dict(line.split('=',1) for line in args.env_file.read_text(encoding='utf-8').splitlines() if '=' in line and not line.startswith('#'))
    url=f"http://127.0.0.1:{values.get('API_PORT','8000')}"
    client=httpx.Client(base_url=url,auth=(values.get('DASHBOARD_USERNAME','admin'),values['DASHBOARD_PASSWORD']),timeout=10)
    deadline=time.monotonic()+180
    while True:
        try:
            health=client.get('/api/system')
            if health.status_code==200 and health.json()['worker']=='ok':
                break
        except httpx.HTTPError:
            pass
        if time.monotonic()>deadline:
            raise RuntimeError('Deployment did not become operational within 180s')
        time.sleep(1)
    assert client.get('/readyz').json()['ready'] is True
    assert health.json()['postgresql']=='ok' and health.json()['redis']=='ok'
    assert health.json()['reconciliation']['problems']==[]
    assert client.get('/api/scanner').json()['status']!='WAITING_FOR_WORKER'
    assert httpx.get(url+'/api/overview').status_code==401
    assert httpx.post(url+'/api/controls/pause').status_code==401
    assert httpx.get(url+'/metrics').status_code==401
    assert client.get('/metrics').status_code==200
    assert client.post('/api/controls/pause').json()['control']=='PAUSED'
    before=client.get('/api/history').json()
    before_ids={e['ledger_event_id'] for e in before['journal']}
    assert sum(e['event_type']=='INITIAL_FUNDING' for e in before['journal'])==1
    if args.restart:
        result=subprocess.run(['docker','compose','-p',args.project,'--env-file',str(args.env_file),'restart'],check=False,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        deadline=time.monotonic()+120
        while True:
            try:
                overview=client.get('/api/overview')
                if overview.status_code==200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic()>deadline:
                raise RuntimeError('Restart did not become ready')
            time.sleep(1)
        assert overview.json()['portfolio']['control']=='PAUSED'
    after=client.get('/api/history').json()
    assert before_ids<={e['ledger_event_id'] for e in after['journal']}
    final=client.get('/api/system').json()
    assert final['reconciliation']['problems']==[]
    client.post('/api/controls/resume')
    result={'status':'PASSED','project':args.project,'volume_restart':args.restart,
        'journal_events_preserved':len(before_ids),'postgresql':final['postgresql'],'redis':final['redis'],
        'scanner':client.get('/api/scanner').json()['status'],'reconciliation':final['reconciliation'],
        'authentication':'PASSED','persistent_controls':'PASSED'}
    Path('docs/evidence/deployment-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
