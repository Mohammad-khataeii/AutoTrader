"""Local source/secret/network checks; never prints configured secret values."""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'autotrader-[a-z0-9][a-z0-9-]{0,45}',args.project):
        parser.error('An isolated autotrader-* project is required')
    files=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z']).decode().split('\0')
    patterns=[re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
              re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b')]
    secrets=[]
    for source in (Path('.env'),args.env_file):
        if source.exists():
            for line in source.read_text(encoding='utf-8').splitlines():
                if '=' in line:
                    key,value=line.split('=',1)
                    if any(word in key for word in ('PASSWORD','API_KEY','BOT_TOKEN')) and len(value)>=20 and 'REPLACE' not in value:
                        secrets.append(value)
    findings=[]
    scanned=0
    for name in files:
        path=Path(name)
        if not path.is_file() or path.suffix.lower() in {'.db','.png','.jpg','.woff','.woff2'}:
            continue
        try:
            content=path.read_text(encoding='utf-8')
        except (UnicodeError,OSError):
            continue
        scanned+=1
        if any(value in content for value in secrets):
            findings.append({'file':name,'kind':'configured_secret'})
        if any(pattern.search(content) for pattern in patterns):
            findings.append({'file':name,'kind':'private_key_or_api_key_pattern'})
    assert not findings,findings
    exchange=ast.parse(Path('src/autotrader/market_data/revolut.py').read_text(encoding='utf-8'))
    calls=[node.func.attr for node in ast.walk(exchange) if isinstance(node,ast.Call)
           and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Attribute)
           and node.func.value.attr=='_client']
    assert calls and set(calls)<={'get','aclose'},calls
    container_lines=subprocess.check_output(['docker','ps','--filter','label=com.docker.compose.project='+args.project,'--format','json']).decode().splitlines()
    containers=[json.loads(line) for line in container_lines if line]
    assert containers,'No selected deployment containers found'
    published=[]
    for container in containers:
        ports=container['Ports']
        assert '0.0.0.0:' not in ports and '[::]:' not in ports,container['Names']
        published.append({'container':container['Names'],'ports':ports})
    result={'status':'PASSED','tracked_text_files_scanned':scanned,'secret_findings':findings,
            'exchange_http_methods':calls,'published_ports':published,
            'scope':'working contents of tracked source/evidence and isolated test deployment; not a remote penetration test'}
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
