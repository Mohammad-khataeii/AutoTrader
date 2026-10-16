from __future__ import annotations

import asyncio

from autotrader.config import get_settings
from autotrader.persistence.database import check_schema, make_engine, make_session_factory
from autotrader.persistence.repository import PersistentTradingRepository


async def main()->None:
    engine=make_engine(get_settings())
    try:
        await check_schema(engine)
        state=await PersistentTradingRepository(make_session_factory(engine)).operational_health()
        reconciliation=state['reconciliation']
        if state['worker']!='ok' or not isinstance(reconciliation,dict) or reconciliation['problems']:
            raise SystemExit(1)
    finally:
        await engine.dispose()


if __name__=='__main__':
    asyncio.run(main())
