"""Standard-library, read-only collector streamed to Aruba; creates no remote files.

Only allowlisted database columns and Docker metadata are selected. No process
logs, environments, auth files, keys, shell history or credential stores are read.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any

PROJECT='autotrader-aruba-test'
OFFICIAL='autotrader_aruba_staging'
NAME=re.compile(r'autotrader_(?:aruba_staging|paper_[a-f0-9]{32}|shadow_[a-f0-9]{32})\Z')
SECRET=re.compile(r'password|secret|api.?key|access.?token|refresh.?token|authorization|private.?key|database_url|redis_url',re.IGNORECASE)


def sanitize(value: Any) -> Any:
    if isinstance(value,dict):
        return {k:('[REDACTED]' if SECRET.search(k) else sanitize(v)) for k,v in value.items()}
    if isinstance(value,list):return [sanitize(v) for v in value]
    if isinstance(value,str):
        if '-----BEGIN' in value or re.search(r'Bearer\s+\S+|(?:password|secret|token|api.?key)\s*[=:]\s*\S+',value,re.IGNORECASE):return '[REDACTED_SENSITIVE_TEXT]'
        value=re.sub(r'([a-z][a-z0-9+.-]*://)[^\s/@]+(?::[^\s/@]*)?@',r'\1[REDACTED]@',value,flags=re.IGNORECASE)
        try:
            parsed=json.loads(value)
            if isinstance(parsed,(dict,list)):return sanitize(parsed)
        except (ValueError,TypeError):pass
    return value


def run(args: list[str]) -> str:
    result=subprocess.run(args,capture_output=True,check=False)
    if result.returncode:raise RuntimeError('read_only_diagnostic_command_failed:'+args[0]+':'+str(sanitize(result.stderr.decode()))[-800:])
    return result.stdout.decode()


def query(container: str, database: str, sql: str) -> Any:
    if not NAME.fullmatch(database):raise ValueError('unregistered_database_name')
    result=run(['docker','exec',container,'psql','-U','autotrader','-d',database,'-qAt','-v','ON_ERROR_STOP=1','-c',
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET LOCAL statement_timeout='90s'; "+sql+'; COMMIT;'])
    return json.loads(result,parse_float=str)


def collect(hours: int) -> dict[str,Any]:
    if hours not in {12,24,48}:
        raise ValueError('supported_hours_are_12_24_48')
    raise RuntimeError('Whole-history aggregate export disabled: use scripts/v49_diagnostics.py, which streams the bounded collector.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--hours',type=int,choices=[12,24,48],default=24)
    args=parser.parse_args()
    print(json.dumps(collect(args.hours),separators=(',',':')))
