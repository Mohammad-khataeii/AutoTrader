"""Optional licensed-feed adapters and conservative no-key EOD research fallback."""
from __future__ import annotations
import csv
import io
import math
import os
import re
from datetime import datetime,timezone,date,timedelta
from urllib.parse import urlencode
import httpx
from .storage import utc

MAX_CSV=8_000_000
SYMBOL_RE=re.compile(r'^[A-Z][A-Z0-9.]{0,9}$')

def validate_bars(records):
    out={}
    today=date.today()
    for r in records:
        try:
            dt=date.fromisoformat(str(r['day']))
            if not date(1990,1,1)<=dt<=today:continue
            vals=[float(r[k]) for k in ('o','h','l','c','v')]
            o,h,l,c,v=vals
            if not all(math.isfinite(x) for x in vals) or min(o,h,l,c)<=0 or v<0 or l>min(o,c,h) or h<max(o,c,l):continue
            out[dt.isoformat()]={'day':dt.isoformat(),'o':o,'h':h,'l':l,'c':c,'v':v}
        except (ValueError,TypeError,KeyError,OverflowError):continue
    return [out[k] for k in sorted(out)]

async def stooq(client:httpx.AsyncClient,symbol:str,from_day='2000-01-01'):
    if not SYMBOL_RE.fullmatch(symbol):raise ValueError('Invalid stock ticker')
    # Stooq is a personal-research fallback, NOT exchange-licensed live execution data.
    url='https://stooq.com/q/d/l/?'+urlencode({'s':symbol.lower()+'.us','d1':from_day.replace('-',''),'i':'d'})
    r=await client.get(url,headers={'Accept':'text/csv','User-Agent':'Mozilla/5.0 (compatible; StocksWatchPersonalPaper/1.0)'})
    if r.status_code in (403,429,503):raise RuntimeError('stooq_throttled_or_blocked')
    r.raise_for_status()
    if len(r.content)>MAX_CSV:raise RuntimeError('stooq_payload_too_large')
    body=r.text
    if not body.lstrip().startswith('Date,Open,High,Low,Close,Volume'):
        raise RuntimeError('stooq_invalid_csv_or_challenge')
    reader=csv.DictReader(io.StringIO(body))
    data=[{'day':x.get('Date'),'o':x.get('Open'),'h':x.get('High'),'l':x.get('Low'),
           'c':x.get('Close'),'v':x.get('Volume')} for x in reader]
    bars=validate_bars(data)
    if len(bars)<2:raise RuntimeError('stooq_no_valid_history')
    return bars,'stooq_unverified_eod','VENDOR_UNSPECIFIED'

async def alpaca(client:httpx.AsyncClient,symbol:str,from_day='2000-01-01'):
    key=os.getenv('STOCKSWATCH_ALPACA_KEY','')
    secret=os.getenv('STOCKSWATCH_ALPACA_SECRET','')
    if not (key and secret):raise RuntimeError('alpaca_credentials_not_configured')
    if not SYMBOL_RE.fullmatch(symbol):raise ValueError('Invalid stock ticker')
    # Free IEX market data can be incomplete; query RAW historical daily bars to avoid
    # retroactive split/dividend adjustments silently corrupting simulated fills.
    host='https://data.alpaca.markets'
    headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret}
    result=[];token=None
    for _ in range(10):
        args={'timeframe':'1Day','start':from_day+'T00:00:00Z','end':datetime.now(timezone.utc).isoformat(),
              'adjustment':'raw','feed':'iex','limit':10000}
        if token:args['page_token']=token
        r=await client.get(f'{host}/v2/stocks/{symbol}/bars',params=args,headers=headers)
        if r.status_code in (401,403):raise RuntimeError('alpaca_credentials_or_feed_denied')
        if r.status_code==429:raise RuntimeError('alpaca_rate_limited')
        r.raise_for_status();obj=r.json()
        for b in obj.get('bars') or []:
            result.append({'day':str(b['t'])[:10],'o':b['o'],'h':b['h'],'l':b['l'],'c':b['c'],'v':b['v']})
        token=obj.get('next_page_token')
        if not token:break
    else:raise RuntimeError('alpaca_pagination_truncated')
    clean=validate_bars(result)
    if len(clean)<2:raise RuntimeError('alpaca_no_valid_bars')
    return clean,'alpaca_iex_daily','RAW'

async def fetch_bars(client,symbol,from_day='2000-01-01'):
    provider=os.getenv('STOCKSWATCH_PRICE_PROVIDER','stooq').lower()
    if provider=='stooq':return await stooq(client,symbol,from_day)
    if provider=='alpaca':return await alpaca(client,symbol,from_day)
    raise RuntimeError('provider_not_supported')

async def sec_mapping(client,agent):
    if not agent or '@' not in agent:raise RuntimeError('sec_user_agent_missing')
    r=await client.get('https://www.sec.gov/files/company_tickers.json',headers={'User-Agent':agent,'Accept-Encoding':'gzip, deflate'})
    r.raise_for_status()
    if len(r.content)>5_000_000:raise ValueError('ticker_map_too_large')
    return {v['ticker'].upper():int(v['cik_str']) for v in r.json().values() if isinstance(v,dict) and v.get('ticker')}

async def sec_company(client,agent,cik):
    if not agent or '@' not in agent:raise RuntimeError('sec_user_agent_missing')
    headers={'User-Agent':agent,'Accept-Encoding':'gzip, deflate','Accept':'application/json'}
    a=await client.get(f'https://data.sec.gov/submissions/CIK{cik:010}.json',headers=headers)
    a.raise_for_status()
    if len(a.content)>10_000_000:raise ValueError('sec_submissions_too_large')
    b=await client.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010}.json',headers=headers)
    if b.status_code==404:fact={}
    else:
        b.raise_for_status()
        if len(b.content)>15_000_000:raise ValueError('sec_facts_too_large')
        fact=b.json()
    return a.json(),fact

def parse_filings(symbol,cik,submissions):
    recent=(submissions.get('filings') or {}).get('recent') or {}
    out=[]
    forms=recent.get('form') or []
    for i,form in enumerate(forms[:300]):
        if form not in {'8-K','10-Q','10-K','6-K','20-F','8-K/A','10-Q/A','10-K/A'}:continue
        try:
            accession=recent['accessionNumber'][i]
            accepted=recent.get('acceptanceDateTime',[])[i]
            filename=recent['primaryDocument'][i]
            # SEC acceptance is the earliest public timestamp; filings may take minutes to disseminate.
            if not re.fullmatch(r'\d{10}-\d{2}-\d{6}',accession):continue
            available_at=datetime.fromisoformat(accepted.replace('Z','+00:00'))
            if available_at.tzinfo is None:
                from zoneinfo import ZoneInfo
                available_at=available_at.replace(tzinfo=ZoneInfo('America/New_York'))
            accepted_utc=available_at.astimezone(timezone.utc).isoformat()
            if available_at>datetime.now(timezone.utc):continue
            url=f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-","")}/{filename}'
            out.append({'id':symbol+':'+accession,'symbol':symbol,'form':form,'accepted_at':accepted_utc,
                        'accession':accession,'description':(recent.get('primaryDocDescription') or ['']*len(forms))[i][:150],
                        'url':url,'observed_at':utc()})
        except (KeyError,IndexError,TypeError,ValueError):continue
    return out

CONCEPTS=('Revenues','RevenueFromContractWithCustomerExcludingAssessedTax','SalesRevenueNet','NetIncomeLoss','EarningsPerShareDiluted','Assets','StockholdersEquity')

def parse_facts(symbol,cik,payload):
    out=[];facts=(payload.get('facts') or {}).get('us-gaap') or {}
    for tag in CONCEPTS:
        units=(facts.get(tag) or {}).get('units') or {}
        for unit,records in units.items():
            if unit not in ('USD','USD/shares'):continue
            for p in records[-200:]:
                try:
                    # Conservative day-end knowledge boundary prevents using fundamentals on filing day.
                    fd=date.fromisoformat(p['filed'])
                    from zoneinfo import ZoneInfo
                    from datetime import time
                    available=datetime.combine(fd,time(23,59,59),tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc).isoformat()
                    value=float(p['val'])
                    if not math.isfinite(value):continue
                    accession=p.get('accn','')
                    identifier=f'{symbol}:{tag}:{unit}:{p.get("start", "")}:{p["end"]}:{accession}'
                    out.append({'id':identifier,'symbol':symbol,'tag':tag,'unit':unit,'start_day':p.get('start'),
                                'end_day':p['end'],'filed_day':fd.isoformat(),'accepted_at':available,
                                'accession':accession,'value':value,
                                'source_url':f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010}.json','observed_at':utc()})
                except (ValueError,TypeError,KeyError):continue
    return out

async def fred_latest(client):
    """Fetch the latest valid observation of each series independently.

    FRED graph CSV is not the official versioned FRED API. This data is
    *current macro context only*, not historical event/vintage evidence.
    Failure or unusual responses never fabricate observations.
    """
    series_specs = (('DGS10', 80, 21), ('UNRATE', 240, 110), ('DFF', 80, 21))
    today = datetime.now(timezone.utc).date()
    out = []
    for index, (series, lookback_days, max_age) in enumerate(series_specs):
        start = (today - timedelta(days=lookback_days)).isoformat()
        response = await client.get(
            'https://fred.stlouisfed.org/graph/fredgraph.csv',
            params={'id': series, 'cosd': start},
            headers={'Accept': 'text/csv',
                     'User-Agent': 'StocksWatchPaperResearch/1.1'},
        )
        response.raise_for_status()
        if len(response.content) > 200_000:
            raise RuntimeError('fred_payload_too_large')
        content = response.text.lstrip('\ufeff')
        if not content or content.lstrip().startswith(('<', '{', '[', '<!')) or '\x00' in content:
            raise RuntimeError('fred_invalid_csv_or_challenge')
        try:
            reader = csv.reader(io.StringIO(content, newline=''), strict=True)
            header = next(reader, None)
            if not header or len(header) != 2 or header[0].strip().lower() not in ('date', 'observation_date') or header[1].strip() != series:
                raise RuntimeError('fred_invalid_csv_or_challenge')
            latest = None
            n = 0
            for fields in reader:
                if not fields:
                    continue
                n += 1
                if n > 2000 or len(fields) != 2:
                    raise RuntimeError('fred_csv_malformed')
                day = date.fromisoformat(fields[0].strip())
                if day > today:
                    continue
                raw = fields[1].strip()
                if raw in ('', '.'):
                    continue
                try:
                    value = float(raw)
                except ValueError:
                    continue
                if math.isfinite(value) and (latest is None or day > latest[0]):
                    latest = (day, value)
        except (csv.Error, ValueError) as exc:
            raise RuntimeError('fred_csv_malformed') from exc
        if latest is None:
            raise RuntimeError('fred_no_valid_observation')
        if (today - latest[0]).days > max_age:
            raise RuntimeError('fred_series_stale')
        out.append((series, latest[0].isoformat(), latest[1]))
    if len(out) != len(series_specs):
        raise RuntimeError('fred_incomplete')
    return out
