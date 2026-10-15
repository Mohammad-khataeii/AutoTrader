"""Summarize actual image reports without treating a completed scan as clearance."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def main()->None:
    images={
        'backend':'autotrader-v34-acceptance-backend',
        'frontend':'autotrader-v34-acceptance-frontend',
        'postgres':'autotrader-v34-postgres:16-alpine',
        'redis':'autotrader-v34-redis:7-alpine',
        'prometheus':'prom/prometheus:v3.15.0',
        'grafana':'autotrader-v34-grafana:13.2.4',
    }
    results={}
    for service,reference in images.items():
        file='container-release-cves.sarif' if service=='backend' else f'{service}-container-cves.sarif'
        report=json.loads((Path('docs/evidence')/file).read_text(encoding='utf-8'))
        findings=[]
        for run in report['runs']:
            for finding in run.get('results',[]):
                message=finding['message']['text']
                fields={key:re.search(r'^'+key+r'\s*:\s*(.+)$',message,re.MULTILINE) for key in ('Severity','Package','Fixed version')}
                severity=fields['Severity'].group(1).strip() if fields['Severity'] else finding.get('level','UNKNOWN')
                findings.append({'cve':finding['ruleId'],'severity':severity,
                    'package':fields['Package'].group(1).strip() if fields['Package'] else '',
                    'fixed_version':fields['Fixed version'].group(1).strip() if fields['Fixed version'] else '',
                    'paths':[location.get('physicalLocation',{}).get('artifactLocation',{}).get('uri','') for location in finding.get('locations',[])]})
        critical={f['cve'] for f in findings if f['severity']=='CRITICAL'}
        high={f['cve'] for f in findings if f['severity']=='HIGH'}
        identity=subprocess.check_output(['docker','image','inspect',reference,'--format','{{.Id}}']).decode().strip()
        results[service]={'image':reference,'image_id':identity,'report':file,
            'scope':'all severities' if service in {'backend','frontend'} else 'high and critical',
            'status':'FAILED' if high or critical else 'PASSED','unique_critical_cves':len(critical),
            'unique_high_cves':len(high),'findings':findings}
    result={'checked_at':datetime.now(UTC).isoformat(),
        'status':'FAILED' if any(r['status']=='FAILED' for r in results.values()) else 'PASSED',
        'meaning':'Unresolved scanner findings; exploitability/applicability is not inferred or suppressed.',
        'services':results}
    Path('docs/evidence/stack-security.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({name:{k:v for k,v in row.items() if k in {'status','unique_critical_cves','unique_high_cves'}} for name,row in results.items()},indent=2))


if __name__=='__main__':
    main()
