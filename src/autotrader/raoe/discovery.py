"""Broad public summary screen; no per-instrument books for rejected markets."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from autotrader.domain import TradingPair, utc_now
from autotrader.opportunity.regime import number

D = Decimal
PEGGED = {'USDC','USDT','DAI','EURC','EURCV','EUROC','PYUSD','TUSD','FDUSD','USDD','USDP','RLUSD'}


def screen(pairs: list[TradingPair], tickers: list[dict[str, Any]],
           prior: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    now = utc_now().timestamp()
    previous = {r['symbol']:r for r in (prior or {}).get('rows',[])}
    quotes = {str(t.get('symbol','')).replace('/','-'):t for t in tickers}
    rows = []
    for pair in pairs:
        if pair.quote_asset!='EUR': continue
        t, old = quotes.get(pair.symbol,{}), previous.get(pair.symbol,{})
        bid, ask, high, low, volume = [number(t.get(k)) for k in ('bid','ask','high_24h','low_24h','quote_volume_24h')]
        reason = None
        mid = (bid+ask)/2 if bid and ask else None
        spread = (ask-bid)/mid*10000 if mid and ask and bid else None
        amplitude = (high-low)/mid if high and low and mid else None
        if pair.base_asset in PEGGED: reason='PEGGED_ASSET_DIRECTIONAL_EXCLUSION'
        elif pair.status.lower()!='active' or pair.price_step<=0 or pair.quantity_step<=0: reason='INVALID_INSTRUMENT'
        elif not all(v is not None and v>0 for v in (bid,ask,high,low,volume)) or ask<=bid or high<low: reason='MISSING_OR_INVALID_SUMMARY'  # type: ignore[operator]
        elif spread is not None and (spread>25 or volume is not None and volume<100000): reason='EXPENSIVE_OR_THIN'
        old_mid = number(old.get('price'))
        movement = mid/old_mid-1 if mid and old_mid else None
        # Keep an actual earlier summary reference rather than overwriting it
        # on cache reuse. Movement is descriptive, never a return forecast.
        last_detail = float(old.get('last_detail_at',0))
        age = min(1800,max(0,now-last_detail))/1800
        liquidity = min(D(1),(volume or D(0))/1000000)
        score = (min(D(3),(amplitude or D(0))*10000/(36+(spread or D(25))))*liquidity
            + min(D(1),max(D(0),movement or D(0))*100)*liquidity+D(str(age))) if not reason else D(0)
        rows.append({'symbol':pair.symbol,'price':str(mid) if mid else None,
            'movement_since_summary':str(movement) if movement is not None else None,
            'spread_bps':str(spread) if spread is not None else None,
            'quote_volume_24h':str(volume) if volume is not None else None,
            'range_24h':str(amplitude) if amplitude is not None else None,
            'score':str(score),'last_detail_at':last_detail,'status':'REJECTED' if reason else 'UNSCANNED',
            'reason':reason,'summary_at':utc_now().isoformat(),
            'liquidity_evidence':'24h turnover proxy; full executable depth requires detailed validation'})
    return sorted(rows,key=lambda r:(bool(r['reason']),-D(r['score']),r['symbol']))


async def discover(service: Any, pairs: list[TradingPair], limit: int) -> list[TradingPair]:
    import json

    from autotrader.persistence.models import SystemStateModel
    from autotrader.persistence.repository import _json
    prior = service._discovery_state
    if service.state_store:
        async with service.state_store.session_factory() as session:
            record = await session.get(SystemStateModel,'raoe_discovery')
            if record: prior=json.loads(record.payload_json)
    rows = screen(pairs,await service.client.get_tickers(),prior)
    candidates = [r for r in rows if not r['reason'] and r['symbol'] not in {'BTC-EUR','ETH-EUR'}]
    selected = candidates[:max(0,limit-1)]
    # One slot goes to the least recently inspected eligible market. This
    # guarantees coverage rather than indefinitely repeating the top ticker.
    remaining = [r for r in candidates if r not in selected]
    if remaining and limit>0: selected.append(min(remaining,key=lambda r:(r['last_detail_at'],-D(r['score']),r['symbol'])))
    names = {'BTC-EUR','ETH-EUR',*[r['symbol'] for r in selected]}
    for row in rows:
        if row['symbol'] in names:
            row.update(status='WATCHING',last_detail_at=utc_now().timestamp())
    body = {'observed_at':utc_now().isoformat(),'rows':rows,'supported_eur':len(rows),
        'selected':sorted(names),'detail_budget':limit,'benchmark_extra_slots':2}
    service._discovery_state=body
    if service.state_store:
        async with service.state_store.session_factory() as session,session.begin():
            await service.state_store._lock_account(session)
            record = await session.get(SystemStateModel,'raoe_discovery')
            if record: record.payload_json,record.updated_at=_json(body),utc_now()
            else: session.add(SystemStateModel(key='raoe_discovery',state='OBSERVED',reason='broad_eur_summary_screen',payload_json=_json(body)))
            key='raoe_discovery:'+str(int(utc_now().timestamp())//300)
            if not await session.get(SystemStateModel,key):
                session.add(SystemStateModel(key=key,state='OBSERVED',reason='durable_discovery_exclusions',payload_json=_json(body)))
    return sorted([p for p in pairs if p.symbol in names and p.quote_asset=='EUR'],key=lambda p:(p.symbol not in {'BTC-EUR','ETH-EUR'},p.symbol))
