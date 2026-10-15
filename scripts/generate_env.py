"""Generate local deployment secrets without printing or overwriting them."""
from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path


def main()->None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='.env')
    parser.add_argument('--test-ports',action='store_true')
    args=parser.parse_args()
    target=Path(args.output).resolve()
    if target.exists():
        raise SystemExit('Refusing to overwrite an existing environment file.')
    target.parent.mkdir(parents=True,exist_ok=True)
    password=secrets.token_hex(24)
    secret=target.parent/(target.stem+'-dashboard-password')
    if secret.exists():
        raise SystemExit('Refusing to overwrite a metrics secret file.')
    values={'ENVIRONMENT':'production','DASHBOARD_USERNAME':'admin','DASHBOARD_PASSWORD':password,
        'POSTGRES_PASSWORD':secrets.token_hex(24),'GRAFANA_ADMIN_PASSWORD':secrets.token_hex(24),
        'AI_PROVIDER':'mock','PROM_PASSWORD_FILE':secret.as_posix()}
    if args.test_ports:
        values.update(API_PORT='18000',FRONTEND_PORT='13000',PROMETHEUS_PORT='19090',GRAFANA_PORT='13001',SCANNER_MAX_PAIRS='3')
    target.write_text(''.join(f'{k}={v}\n' for k,v in values.items()),encoding='utf-8')
    secret.write_text(password,encoding='utf-8')
    os.chmod(target,0o600)
    os.chmod(secret,0o600)
    print('Environment and metrics secret created. Values were not printed.')


if __name__=='__main__':
    main()
