"""Run the real process/PG suite inside the selected runtime's Linux image.

For Dockerfile.tests only. Mount the repository at /verification and attach the
selected isolated deployment's data network. Supply its generated env file;
the password is used in memory and is never printed.
"""
from __future__ import annotations

import os
import sys
from urllib.parse import quote


def main()->None:
    if not sys.platform.startswith('linux') or os.getenv('ENVIRONMENT')!='test':
        raise RuntimeError('This harness requires an explicitly isolated Linux test container.')
    env=dict(os.environ)
    password=quote(env['POSTGRES_PASSWORD'],safe='')
    env['AUTOTRADER_TEST_PG_ADMIN_URL']=f'postgresql://autotrader:{password}@postgres:5432/postgres'
    env['DATABASE_URL']='sqlite+aiosqlite:////tmp/autotrader-tests.db'
    env['AUTOTRADER_MIGRATIONS_ROOT']='/verification'
    env['PYTHONPATH']='/verification/tests'
    env['DASHBOARD_PASSWORD']='change-me'
    # Prefer the installed runtime package. Each test gets a disposable database.
    os.execvpe(sys.executable,[sys.executable,'-m','pytest','-q','-s',
        '--junitxml=docs/evidence/linux-regression.xml',*sys.argv[1:]],env)


if __name__=='__main__':
    main()
