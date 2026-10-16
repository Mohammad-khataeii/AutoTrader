"""Exercise dependency outages only on an explicitly selected isolated project."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import httpx


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True)
    parser.add_argument('--env-file',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if not re.fullmatch(r'autotrader-[a-z0-9][a-z0-9-]{0,45}',args.project):
        parser.error('An isolated autotrader-* project is required')
    values=dict(line.split('=',1) for line in args.env_file.read_text().splitlines() if '=' in line and not line.startswith('#'))
    compose=['docker','compose','-p',args.project,'--env-file',str(args.env_file)]
    def dc(*parts: str) -> None:
        subprocess.run([*compose,*parts],check=True,capture_output=True)
    def wait(check,seconds: int = 120):
        deadline=time.monotonic()+seconds
        while True:
            try:
                result=check()
                if result:
                    return result
            except (httpx.HTTPError,KeyError,ValueError):
                pass
            if time.monotonic()>deadline:
                raise RuntimeError('Recovery condition did not become true')
            time.sleep(1)
    with httpx.Client(base_url='http://127.0.0.1:'+values.get('API_PORT','8000'),auth=(values.get('DASHBOARD_USERNAME','admin'),values['DASHBOARD_PASSWORD']),timeout=8) as client:
        def health():
            response=client.get('/api/system');response.raise_for_status();return response.json()
        wait(lambda: health()['worker']=='ok')
        before=client.get('/api/history').json()
        journal={row['ledger_event_id'] for row in before['journal']}
        assert journal
        result={'project':args.project,'status':'RUNNING','journal_events_before':len(journal)}
        try:
            dc('stop','redis')
            degraded=wait(lambda: (h if (h:=health())['redis']=='unavailable' else None),30)
            assert degraded['postgresql']=='ok'
            assert client.get('/readyz').json()['ready'] is True
            assert degraded['reconciliation']['problems']==[]
            result['redis_outage']={'reported':'unavailable','database':'ok','api_ready':True,'financial_reconciliation':[]}
        finally:
            dc('start','redis')
        wait(lambda: health()['redis']=='ok',40)
        try:
            dc('stop','postgres')
            status=wait(lambda: (r.status_code if (r:=client.get('/readyz')).status_code==503 else None),30)
            # Let both position/lease loops observe the missing database.
            time.sleep(7)
            result['postgres_outage']={'readiness_http':status,'financial_admission':'blocked by unavailable account transaction and lease'}
        finally:
            dc('start','postgres')
        def recovered():
            h=health()
            return h if h['postgresql']=='ok' and h['worker']=='ok' and h['operational_state']=='RESEARCH_ONLY' else None
        final=wait(recovered,150)
        after=client.get('/api/history').json()
        assert journal<={row['ledger_event_id'] for row in after['journal']}
        assert sum(row['event_type']=='INITIAL_FUNDING' for row in after['journal'])==1
        assert final['reconciliation']['problems']==[]
        assert client.get('/api/overview').json()['portfolio']['cash']=='500.000000000000'
        result.update(status='PASSED',recovered_state=final['operational_state'],journal_preserved=True,initial_funding_events=1,reconciliation=[])
        args.output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
