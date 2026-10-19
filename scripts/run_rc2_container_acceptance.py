"""Run the actual AMD64 candidate in an owned, internal-only synthetic cluster."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='autotrader-v45-rc2:amd64')
    parser.add_argument('--output', type=Path, default=Path('docs/evidence/v4_5_rc2/amd64-lifecycles.json'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    token = 'autotrader-rc2-engine-' + uuid4().hex[:12]
    network, postgres = token + '-net', token + '-pg'
    success = False
    def run(command):
        return subprocess.check_output(command, stderr=subprocess.PIPE)
    run(['docker', 'network', 'create', '--internal', '--label', 'autotrader.rc2.acceptance='+token, network])
    try:
        run(['docker', 'run', '-d', '--name', postgres, '--network', network, '--network-alias', 'acceptance-postgres',
            '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_DB=postgres', '-e', 'POSTGRES_USER=autotrader',
            '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', 'postgres:16-alpine'])
        for _ in range(60):
            if subprocess.run(['docker', 'exec', postgres, 'pg_isready', '-U', 'autotrader'], capture_output=True, check=False).returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError('owned_acceptance_postgres_unavailable')
        result = run(['docker', 'run', '--rm', '--platform', 'linux/amd64', '--network', network, '--read-only', '--tmpfs', '/tmp',
            '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'LIVE_TRADING_ENABLED=false', '-e', 'AUTOTRADER_SYNTHETIC_ACCEPTANCE=1',
            '-e', 'DATABASE_URL=postgresql+asyncpg://autotrader@acceptance-postgres:5432/postgres',
            '-v', str(root/'scripts/rc2_container_acceptance.py')+':/acceptance/main.py:ro',
            '-v', str(root/'tests')+':/acceptance/tests:ro', args.image, 'python', '/acceptance/main.py'])
        report = json.loads(result)
        report['image_id'] = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', args.image]).decode().strip()
        report['network_internal'] = json.loads(run(['docker', 'network', 'inspect', network]))[0]['Internal']
        assert report['status'] == 'PASS' and report['architecture'] == 'x86_64' and len(report['accounts']) == 12 and report['network_internal']
        args.output.write_text(json.dumps(report, indent=2)+'\n')
        success = True
        print('PASS: 12 original V42, original V44 and new V45 synthetic lifecycles inside AMD64 candidate')
    except subprocess.CalledProcessError as exc:
        Path('.tools/rc2-container-failure.log').write_bytes(exc.stderr or b'')
        print('Owned diagnostic cluster retained: '+postgres+' / '+network)
        raise
    finally:
        if success:
            run(['docker', 'rm', '-f', postgres])
            run(['docker', 'network', 'rm', network])


if __name__ == '__main__':
    main()
