"""Explicit pilot start and reproducible JSON/CSV export from persistent state."""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
from datetime import date
from pathlib import Path
from typing import Any

from autotrader.config import get_settings
from autotrader.persistence.database import check_schema, make_engine, make_session_factory
from autotrader.persistence.pilot import pilot_configuration
from autotrader.persistence.repository import PersistentTradingRepository
from autotrader.research.data import atomic_write


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['list','start','report'])
    parser.add_argument('--pilot-id')
    parser.add_argument('--request-id')
    parser.add_argument('--day',type=date.fromisoformat)
    parser.add_argument('--format',choices=['json','csv'],default='json')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    async def execute() -> Any:
        settings=get_settings()
        engine=make_engine(settings)
        try:
            await check_schema(engine)  # Never migrates an existing user database.
            repo=PersistentTradingRepository(make_session_factory(engine))
            if args.action=='list':
                return await repo.pilots()
            if args.action=='start':
                if not args.request_id:
                    parser.error('An explicit --request-id is required.')
                return await repo.start_pilot(args.request_id,pilot_configuration(settings),test_environment=settings.environment=='test')
            if not args.pilot_id:
                parser.error('--pilot-id is required.')
            return await repo.pilot_report(args.pilot_id,args.day)
        finally:
            await engine.dispose()
    result=asyncio.run(execute())
    if args.format=='csv':
        rows=result if isinstance(result,list) else [result]
        stream=io.StringIO()
        if rows:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows:
                writer.writerow({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in row.items()})
        payload=stream.getvalue().encode()
    else:
        payload=(json.dumps(result,indent=2)+'\n').encode()
    if args.output:
        atomic_write(args.output,payload)
        print('Pilot export written: '+str(args.output.resolve()))
    else:
        print(payload.decode(),end='')


if __name__=='__main__':
    main()
