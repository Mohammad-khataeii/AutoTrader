"""Verify a binary PostgreSQL backup by restoring an isolated Compose database.

Only the selected project's worker is stopped; existing databases/volumes are
never deleted. The restored database and private dump remain for inspection.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True, type=Path)
    parser.add_argument('--project', required=True)
    args = parser.parse_args()
    compose = ['docker', 'compose', '-p', args.project, '--env-file', str(args.env_file)]

    def run(command: list[str], *, data: bytes | None = None) -> bytes:
        result = subprocess.run(command, input=data, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace'))
        return result.stdout

    postgres = run([*compose, 'ps', '-q', 'postgres']).decode().strip()
    backend = run([*compose, 'ps', '-q', 'backend']).decode().strip()
    if not postgres or not backend:
        raise RuntimeError('Selected project must have a running PostgreSQL and backend')
    database = 'autotrader_restore_' + uuid4().hex[:12]
    query = "SELECT json_build_object('journal_events',(SELECT count(*) FROM financial_journal),'fills',(SELECT count(*) FROM fills),'positions',(SELECT count(*) FROM positions),'journal_cash',(SELECT sum(cash_delta)::text FROM financial_journal),'schema',(SELECT version_num FROM alembic_version));"
    # Names are discovered from this project, never from another checkout.
    run([*compose, 'stop', 'worker'])
    try:
        original = json.loads(run(['docker', 'exec', postgres, 'psql', '-U', 'autotrader', '-d', 'autotrader', '-Atc', query]))
        backup = run(['docker', 'exec', postgres, 'pg_dump', '-U', 'autotrader', '-Fc', 'autotrader'])
        output = Path('.tools') / f'{database}.dump'
        output.parent.mkdir(exist_ok=True)
        output.write_bytes(backup)
        output.chmod(0o600)
        run(['docker', 'exec', postgres, 'createdb', '-U', 'autotrader', database])
        run(['docker', 'exec', '-i', postgres, 'pg_restore', '-U', 'autotrader', '--no-owner', '-d', database], data=backup)
        restored = json.loads(run(['docker', 'exec', postgres, 'psql', '-U', 'autotrader', '-d', database, '-Atc', query]))
        assert restored == original, (original, restored)
        code = """import asyncio,json
from decimal import Decimal
from sqlalchemy.engine import make_url
from autotrader.config import get_settings
from autotrader.persistence.database import make_engine,make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository
async def check():
    settings=get_settings()
    settings.database_url=make_url(settings.database_url).set(database=RESTORE_DB).render_as_string(hide_password=False)
    engine=make_engine(settings)
    try:
        repo=PersistentTradingRepository(make_session_factory(engine))
        issues=await repo.verify_invariants(Decimal(500))
        print(json.dumps(issues))
    finally:
        await engine.dispose()
asyncio.run(check())
""".replace('RESTORE_DB', repr(database))
        issues = json.loads(run(['docker', 'exec', backend, 'python', '-c', code]))
        assert issues == [], issues
        evidence = {'status': 'PASSED', 'project': args.project, 'restore_database': database,
                    'backup_bytes': len(backup), 'original': original, 'restored': restored,
                    'reconciliation': issues, 'existing_volumes_deleted': False}
        Path('docs/evidence/backup-restore.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        print(json.dumps(evidence, indent=2))
    finally:
        run([*compose, 'start', 'worker'])


if __name__ == '__main__':
    main()
