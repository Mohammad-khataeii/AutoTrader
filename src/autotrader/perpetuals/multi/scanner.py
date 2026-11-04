"""All-dashboard-asset contract mapping, cheap summary screen and fair detail rotation."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from autotrader.persistence.models import SystemStateModel, TradingPairModel
from autotrader.perpetuals.multi.policy import D

PEGGED={'USDT','USDC','DAI','EURC','EURCV','EUROC','PYUSD','FDUSD','TUSD','USDP','RLUSD'}


async def dashboard_assets(factory) -> dict[str,list[str]]:
    """Only identifiers cross domains. EUR quotes and spot indicators are never reused."""
    async with factory() as session:
        pairs=(await session.execute(select(TradingPairModel.symbol,TradingPairModel.base_asset))).all()
        record=await session.get(SystemStateModel,'raoe_discovery')
        discovery=json.loads(record.payload_json) if record else {}
    result={}
    for symbol,base in pairs:result.setdefault(base,[]).append(symbol)
    for row in discovery.get('rows',[]):
        symbol=row['symbol']
        # Existing discovery identifiers have explicit EUR quote suffixes.
        # No generic string replace, multiplier stripping or symbol guessing.
        if symbol.endswith('-EUR'):
            base=symbol[:-4]
            if symbol not in result.setdefault(base,[]):result[base].append(symbol)
    return result


def map_universe(assets: dict[str,list[str]], instruments: dict[str,dict[str,Any]]) -> tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    by_base={}
    for row in instruments.values():
        if (row.get('status')=='Trading' and row.get('contractType')=='LinearPerpetual'
                and row.get('quoteCoin')=='USDT' and row.get('settleCoin')=='USDT'
                and not row.get('isPreListing') and not row.get('marketRegion')):
            by_base.setdefault(row['baseCoin'],[]).append(row)
    mapped,rejected=[],[]
    for base,sources in sorted(assets.items()):
        matches=by_base.get(base,[])
        reason='pegged_asset_excluded' if base in PEGGED else 'no_exact_active_usdt_contract' if not matches else 'ambiguous_perpetual_mapping' if len(matches)>1 else None
        if reason:
            rejected.append({'base':base,'dashboard_symbols':sources,'reason':reason,'status':'UNSUPPORTED'})
        else:mapped.append({'base':base,'symbol':matches[0]['symbol'],'dashboard_symbols':sources})
    return mapped,rejected


def screen(mapped: list[dict[str,Any]], tickers: list[dict[str,Any]], now: int,
           previous: dict[str,Any], batch: int = 6) -> tuple[list[dict[str,Any]],list[dict[str,Any]],dict[str,Any]]:
    quotes={r['symbol']:r for r in tickers};rows=[]
    recent=previous.get('revisits',{});samples=previous.get('samples',{})
    next_samples={}
    for mapping in mapped:
        symbol=mapping['symbol'];row={**mapping,'status':'DEFERRED','reason':None}
        try:
            t=quotes[symbol]
            bid,ask,volume,high,low=(D(str(t[k])) for k in ('bid1Price','ask1Price','turnover24h','highPrice24h','lowPrice24h'))
            if not all(v.is_finite() and v>0 for v in (bid,ask,volume,high,low)) or ask<=bid or high<low:raise ValueError()
            mid=(bid+ask)/2;spread=(ask-bid)/mid;amplitude=(high-low)/mid
            if spread>D('.0015') or volume<D(1_000_000):raise ValueError('thin_or_expensive_summary')
            history=[r for r in samples.get(symbol,[]) if now-1800_000<=r['at']<=now]
            if not history or now-history[-1]['at']>=50_000:history.append({'at':now,'mid':str(mid),'volume24h':str(volume)})
            history=history[-31:];next_samples[symbol]=history
            observed_range=(max(D(r['mid']) for r in history)-min(D(r['mid']) for r in history))/mid if len(history)>1 else None
            # Range/turnover are breadth proxies, never an inference from the largest gain.
            liquidity=min(volume/D(10_000_000),D(2));tightness=max(D(0),1-spread/D('.0015'))
            movement=min((observed_range if observed_range is not None else amplitude/D(12))/D('.005'),D(2))
            previous_volume=D(history[-2]['volume24h']) if len(history)>1 else None
            volume_change=volume/previous_volume-1 if previous_volume and previous_volume>0 else None
            volume_priority=min(D('.25'),max(D(0),volume_change or D(0)))
            score=liquidity+tightness+movement+volume_priority
            row.update(price=mid,spread_pct=spread*100,turnover_usdt=volume,score=score,
                rolling_24h_turnover_change_pct=volume_change*100 if volume_change is not None else None,
                volume_change_source='Rolling 24h turnover proxy, not executed short-window volume',
                observed_summary_range_pct=observed_range*100 if observed_range is not None else None,
                volatility_source='TIMED_PERPETUAL_SUMMARIES' if observed_range is not None else '24H_RANGE_BROAD_SCREEN_PROXY',
                last_detail_at=int(recent.get(symbol,0)))
        except (KeyError,ValueError,ArithmeticError):
            row.update(status='REJECTED',reason='missing_invalid_thin_or_expensive_summary',score=D(0),last_detail_at=0)
        rows.append(row)
    eligible=sorted([r for r in rows if r['status']!='REJECTED'],key=lambda r:(-r['score'],r['symbol']))
    # Reserve half the bounded slots for least recently visited eligible markets.
    fair=sorted(eligible,key=lambda r:(r['last_detail_at'],r['symbol']))[:max(1,batch//2)]
    chosen=list(fair)
    chosen.extend(r for r in eligible if r not in chosen)
    chosen=chosen[:batch]
    for row in chosen:row.update(status='DETAIL_SELECTED',selection='FAIR_REVISIT' if row in fair else 'SUMMARY_PRIORITY')
    return chosen,rows,{'revisits':{r['symbol']:int(recent.get(r['symbol'],0)) for r in rows},'samples':next_samples}
