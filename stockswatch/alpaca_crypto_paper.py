"""Strict Alpaca PAPER-ONLY crypto spot execution. No crypto shorts or leverage.

Separate Alpaca paper account is mandatory for any crypto order submission:
StocksWatch's existing stock account must remain completely untouched.
Default is observation-only. A pending/uncertain intent is never replayed.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, InvalidOperation

import httpx

from . import alpaca_crypto as ac
from .storage import connect, one, rows, utc

UTC=timezone.utc
ORIGIN="https://paper-api.alpaca.markets"
LOCK=threading.Lock()
TERMINAL={"filled","canceled","expired","rejected","replaced"}
CAP_PER_SYMBOL=Decimal("0.04")
CAP_CRYPTO_TOTAL=Decimal("0.12")
MAX_OPEN_POSITIONS=3
MAX_DAILY_LOSS=Decimal("0.02")
MAX_DRAWDOWN=Decimal("0.10")
RISK_PER_TRADE=Decimal("0.0035")
MIN_TRADE_USD=Decimal("25")


class CryptoPaperError(RuntimeError):
    """Stable fail-closed code only; no account secrets or response bodies."""


def money(value):
    try:d=Decimal(str(value))
    except (TypeError,ValueError,InvalidOperation):raise CryptoPaperError("crypto_invalid_money") from None
    if not d.is_finite():raise CryptoPaperError("crypto_non_finite_money")
    return d


def enabled():
    return os.getenv("ALPACA_CRYPTO_ALLOW_PAPER_ORDERS","0")=="1"


def _credentials():
    key=os.getenv("ALPACA_CRYPTO_PAPER_KEY","")
    secret=os.getenv("ALPACA_CRYPTO_PAPER_SECRET","")
    if not key or not secret:
        raise CryptoPaperError("crypto_dedicated_paper_credentials_missing")
    return {"APCA-API-KEY-ID":key,"APCA-API-SECRET-KEY":secret}


def expected_account():
    expected=os.getenv("ALPACA_CRYPTO_PAPER_ACCOUNT_ID","").strip()
    stocks=os.getenv("STOCKSWATCH_ALPACA_PAPER_ACCOUNT_ID","").strip()
    if not expected or not stocks or expected==stocks:
        raise CryptoPaperError("crypto_requires_distinct_paper_account")
    return expected


def _order_id(account,symbol,bar_at,side):
    return "acp1-"+hashlib.sha256(f"alpaca_crypto|{account}|{symbol}|{bar_at}|{side}".encode()).hexdigest()[:40]


class CryptoPaperClient:
    def __init__(self,transport=None):
        self.http=httpx.Client(base_url=ORIGIN,headers=_credentials(),
              timeout=httpx.Timeout(12,connect=5),trust_env=False,
              follow_redirects=False,transport=transport)

    def __enter__(self):return self
    def __exit__(self,*a):self.http.close()

    def request(self,method,path,**kwargs):
        if (not path.startswith("/v2/") or "//" in path or ".." in path
                or "?" in path or method not in ("GET","POST")):
            raise CryptoPaperError("crypto_paper_route_denied")
        if method=="POST" and path!="/v2/orders":
            raise CryptoPaperError("crypto_paper_post_denied")
        try:r=self.http.request(method,path,**kwargs)
        except httpx.TransportError:
            raise CryptoPaperError("crypto_paper_transport_uncertain" if method=="POST"
                                   else "crypto_paper_transport_unavailable") from None
        if r.status_code==404 and path=="/v2/orders:by_client_order_id" and method=="GET":
            return None
        if not r.is_success:
            raise CryptoPaperError("crypto_paper_post_uncertain" if method=="POST"
                                   else f"crypto_paper_read_http_{r.status_code}")
        if len(r.content)>3_000_000:
            raise CryptoPaperError("crypto_paper_response_excess")
        try:result=r.json()
        except ValueError:raise CryptoPaperError("crypto_paper_invalid_json") from None
        return result

    def account(self):
        account=self.request("GET","/v2/account")
        if not isinstance(account,dict) or not account.get("id"):
            raise CryptoPaperError("crypto_paper_account_invalid")
        expected=expected_account()
        if expected not in (account.get("id"),account.get("account_number")):
            raise CryptoPaperError("crypto_paper_account_mismatch")
        if account.get("currency")!="USD" or account.get("status")!="ACTIVE":
            raise CryptoPaperError("crypto_paper_account_not_active_usd")
        if account.get("account_blocked") is not False or account.get("trading_blocked") is not False:
            raise CryptoPaperError("crypto_paper_account_blocked")
        return account

    def assets(self):
        data=self.request("GET","/v2/assets",params={"status":"active","asset_class":"crypto"})
        if not isinstance(data,list) or not all(isinstance(x,dict) for x in data):
            raise CryptoPaperError("crypto_asset_list_invalid")
        return data

    def snapshot(self):
        account=self.account()
        positions=self.request("GET","/v2/positions")
        orders=self.request("GET","/v2/orders",params={"status":"open","limit":500,"nested":"false"})
        if not all(isinstance(x,list) and all(isinstance(y,dict) for y in x)
                   for x in (positions,orders)) or len(orders)>=500:
            raise CryptoPaperError("crypto_broker_book_incomplete")
        if any(not p.get("symbol") or p.get("side")!="long" or money(p.get("qty"))<=0 for p in positions):
            raise CryptoPaperError("crypto_broker_unclassified_position")
        if any(not o.get("id") or not o.get("symbol") or not o.get("status") for o in orders):
            raise CryptoPaperError("crypto_broker_order_incomplete")
        return {"account":account,"positions":positions,"orders":orders}

    def by_client_id(self,cid):
        if not re.fullmatch(r"acp1-[a-f0-9]{40}",cid):
            raise CryptoPaperError("crypto_client_id_invalid")
        return self.request("GET","/v2/orders:by_client_order_id",params={"client_order_id":cid})

    def submit(self,order):
        if not enabled():
            raise CryptoPaperError("crypto_paper_orders_disabled")
        if (not isinstance(order,dict) or
             set(order) not in ({"symbol","side","type","time_in_force","notional","client_order_id"},
                                {"symbol","side","type","time_in_force","qty","client_order_id"}) or
             order.get("symbol") not in ac.PAIRS or order.get("type")!="market" or
             order.get("time_in_force")!="gtc" or
             order.get("side") not in ("buy","sell") or
             not re.fullmatch(r"acp1-[a-f0-9]{40}",str(order.get("client_order_id") or ""))):
            raise CryptoPaperError("crypto_unsafe_order_payload")
        if order["side"]=="buy" and ("notional" not in order or money(order["notional"])<MIN_TRADE_USD):
            raise CryptoPaperError("crypto_unsafe_buy_notional")
        if order["side"]=="sell" and ("qty" not in order or money(order["qty"])<=0):
            raise CryptoPaperError("crypto_unsafe_sell_quantity")
        return self.request("POST","/v2/orders",json=order)


def verify_assets(client):
    assets=client.assets()
    by_symbol={a.get("symbol"):a for a in assets}
    now=utc()
    results=[]
    for symbol in ac.PAIRS:
        a=by_symbol.get(symbol,{})
        eligible=(a.get("class")=="crypto" and a.get("tradable") is True
             and a.get("status")=="active" and a.get("fractionable") is True
             and a.get("shortable") is False and a.get("marginable") is False)
        try:
            minimum=money(a.get("min_order_size"))
            increment=money(a.get("min_trade_increment"))
            tick=money(a.get("price_increment"))
            eligible=eligible and minimum>0 and increment>0 and tick>0
        except CryptoPaperError:
            minimum=increment=tick=None
            eligible=False
        results.append((int(eligible),now,
            "verified_spot_only" if eligible else "not_verified_as_eligible_spot",
            str(minimum) if minimum else None,str(increment) if increment else None,
            str(tick) if tick else None,symbol))
    with connect() as c:
        c.executemany("""UPDATE ac_assets SET eligible=?,checked_at=?,reason=?,
            min_order_size=?,min_trade_increment=?,price_increment=?
            WHERE symbol=?""",results)
    return sum(x[0] for x in results)


def _fresh_asset(symbol,now):
    x=one("SELECT * FROM ac_assets WHERE symbol=?",(symbol,))
    if not x or x["eligible"]!=1 or not x["checked_at"]:
        raise CryptoPaperError("crypto_asset_unverified")
    verified=datetime.fromisoformat(x["checked_at"])
    if not timedelta(0) <= now-verified <= timedelta(hours=12):
        raise CryptoPaperError("crypto_asset_verification_expired")
    return x


def _record_intent(account,symbol,side,bar_at,reason,notional=None,qty=None):
    cid=_order_id(account,symbol,bar_at,side)
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT 1 FROM ac_intents WHERE client_id=?",(cid,)).fetchone():
            c.rollback()
            return None
        c.execute("""INSERT INTO ac_intents
            (client_id,account_id,symbol,side,created_at,state,qty,notional,reason)
            VALUES(?,?,?,?,?,'PREPARED',?,?,?)""",
            (cid,account,symbol,side,utc(),qty,notional,reason))
        c.commit()
    return cid


def _submit_intent(client,account,symbol,side,bar_at,reason,*,notional=None,qty=None):
    cid=_record_intent(account,symbol,side,bar_at,reason,notional,qty)
    if cid is None:
        return "duplicate_intent_refused"
    payload={"symbol":symbol,"side":side,"type":"market","time_in_force":"gtc",
             "client_order_id":cid,
             **({"notional":notional} if side=="buy" else {"qty":qty})}
    try:
        response=client.submit(payload)
        if (not isinstance(response,dict) or response.get("client_order_id")!=cid
                or response.get("symbol") not in (symbol,symbol.replace("/",""))
                or response.get("side")!=side or not response.get("id")
                or response.get("status") not in
                     {"new","accepted","pending_new","partially_filled","filled"}):
            raise CryptoPaperError("crypto_post_response_unverified")
    except CryptoPaperError:
        with connect() as c:
            c.execute("""UPDATE ac_intents SET state='UNCERTAIN', last_checked=?
                WHERE client_id=?""",(utc(),cid))
        return "uncertain_intent_no_automatic_retry"
    with connect() as c:
        c.execute("""UPDATE ac_intents SET state='ACKNOWLEDGED',
            broker_order_id=?,broker_status=?,last_checked=? WHERE client_id=?""",
            (response["id"],response["status"],utc(),cid))
    return "paper_order_acknowledged"


def reconcile(client):
    uncertain=rows("SELECT * FROM ac_intents WHERE state IN ('PREPARED','UNCERTAIN') ORDER BY created_at")
    for item in uncertain[:10]:
        try:
            o=client.by_client_id(item["client_id"])
        except CryptoPaperError:
            continue
        if (isinstance(o,dict) and o.get("client_order_id")==item["client_id"]
            and o.get("symbol") in (item["symbol"],item["symbol"].replace("/",""))
            and o.get("side")==item["side"] and o.get("id")):
            with connect() as c:
                c.execute("""UPDATE ac_intents SET state='ACKNOWLEDGED',
                    broker_order_id=?,broker_status=?,last_checked=? WHERE client_id=?""",
                    (o["id"],o.get("status"),utc(),item["client_id"]))
    # A remaining uncertain intent is a hard block against any further submissions.
    return not bool(one("SELECT 1 FROM ac_intents WHERE state IN ('PREPARED','UNCERTAIN') LIMIT 1"))


def _owned(snapshot):
    owned={r["symbol"] for r in rows("""SELECT DISTINCT symbol FROM ac_intents
         WHERE side='buy' AND state='ACKNOWLEDGED'""")}
    for p in snapshot["positions"]:
        if p["symbol"] not in owned and p["symbol"].replace("USD","/USD") not in owned:
            raise CryptoPaperError("crypto_unowned_broker_position")
    for o in snapshot["orders"]:
        if not any(o.get("client_order_id")==r["client_id"] for r in rows(
            "SELECT client_id FROM ac_intents WHERE state='ACKNOWLEDGED'")):
            raise CryptoPaperError("crypto_unowned_open_order")
    return {p["symbol"].replace("USD","/USD"):p for p in snapshot["positions"]}


def _limits(snapshot,now):
    a=snapshot["account"]
    equity=money(a.get("equity")); last=money(a.get("last_equity"))
    buying=money(a.get("non_marginable_buying_power"))
    if min(equity,last,buying)<0 or equity<=0 or last<=0:
        raise CryptoPaperError("crypto_invalid_account_balances")
    with connect() as c:
        high=one("SELECT high_water FROM ac_state WHERE id=1")
        peak=max(equity,money(high["high_water"]) if high and high["high_water"] else equity)
        c.execute("UPDATE ac_state SET high_water=? WHERE id=1",(str(peak),))
    if (equity < last*(1-MAX_DAILY_LOSS) or equity<peak*(1-MAX_DRAWDOWN)):
        raise CryptoPaperError("crypto_account_drawdown_pause")
    return equity,buying


def run_paper_cycle(data,now=None):
    """Broker recon + software stop/target; no orders unless separately enabled and unpaused."""
    now=now or datetime.now(UTC)
    if not os.getenv("ALPACA_CRYPTO_PAPER_KEY") or not os.getenv("ALPACA_CRYPTO_PAPER_SECRET"):
        return "crypto_separate_paper_account_not_configured"
    with LOCK:
        try:
            with CryptoPaperClient() as client:
                snapshot=client.snapshot()
                account=snapshot["account"]["id"]
                with connect() as c:
                    c.execute("UPDATE ac_state SET configured_account=? WHERE id=1",(account,))
                if not enabled():
                    return "read_only_dedicated_paper_account"
                if bool((one("SELECT paused FROM ac_state WHERE id=1") or {}).get("paused",1)):
                    return "crypto_paper_orders_paused"
                if not reconcile(client):
                    return "unresolved_order_intents_block_trading"
                pos=_owned(snapshot)
                equity,buying=_limits(snapshot,now)
                managed=rows("SELECT * FROM ac_managed WHERE account_id=?",(account,))
                # Never risk exit or sell an unowned position.
                for m in managed:
                    symbol=m["symbol"]
                    position=pos.get(symbol)
                    if not position:continue
                    asset=_fresh_asset(symbol,now)
                    bid,ask,stamp=data.latest_bid(symbol)
                    side="sell" if bid<=float(m["stop"]) or bid>=float(m["target"]) else None
                    if not side:continue
                    increment=money(asset["min_trade_increment"])
                    qty=(money(position["qty"])//increment)*increment
                    if qty < money(asset["min_order_size"]):
                        continue
                    reason="software_stop_at_fresh_bid" if bid<=float(m["stop"]) else "software_target_at_fresh_bid"
                    return _submit_intent(client,account,symbol,side,stamp,reason,qty=format(qty,"f"))
                if any(p.get("side")!="long" for p in snapshot["positions"]):
                    raise CryptoPaperError("crypto_unrecognized_position_side")
                if len(pos)>=MAX_OPEN_POSITIONS or snapshot["orders"]:
                    return "crypto_position_or_open_order_limit"
                crypto_exposure=sum(abs(money(p.get("market_value"))) for p in pos.values())
                if crypto_exposure>=equity*CAP_CRYPTO_TOTAL:
                    return "crypto_total_exposure_cap"
                signals=ac.scan(now)
                for s in sorted(signals,key=lambda x:x["symbol"]):
                    if s["action"]!="BUY" or s["symbol"] in pos:continue
                    asset=_fresh_asset(s["symbol"],now)
                    bid,ask,stamp=data.latest_bid(s["symbol"])
                    if ask > float(s["price"])*1.02 or (ask-bid)/ask>0.015:
                        continue
                    loss_per_unit=money(ask)-money(s["stop"])
                    if loss_per_unit<=0:
                        continue
                    stop_fraction=loss_per_unit/money(ask)
                    budget=min(equity*CAP_PER_SYMBOL,
                               equity*CAP_CRYPTO_TOTAL-crypto_exposure,
                               buying*Decimal(".75"),
                               equity*RISK_PER_TRADE/stop_fraction)
                    budget=budget.quantize(Decimal(".01"),rounding=ROUND_DOWN)
                    if budget<MIN_TRADE_USD:continue
                    outcome=_submit_intent(client,account,s["symbol"],"buy",s["bar_at"],
                            s["reason"],notional=str(budget))
                    if outcome=="paper_order_acknowledged":
                        with connect() as c:
                            c.execute("""INSERT OR IGNORE INTO ac_managed
                                (symbol,account_id,entry_client_id,stop,target,entered_at)
                                VALUES(?,?,?,?,?,?)""",
                                (s["symbol"],account,_order_id(account,s["symbol"],s["bar_at"],"buy"),
                                 str(s["stop"]),str(s["target"]),utc()))
                    return outcome
                return "no_approved_spot_long_signal"
        except CryptoPaperError as exc:
            with connect() as c:
                c.execute("UPDATE ac_state SET last_error=? WHERE id=1",(str(exc),))
            return str(exc)


def set_paused(pause):
    if not pause and not enabled():
        raise CryptoPaperError("crypto_orders_not_enabled_on_server")
    with connect() as c:
        c.execute("UPDATE ac_state SET paused=? WHERE id=1",(int(pause),))
    return {"paused":pause,"mode":"ALPACA_CRYPTO_SPOT_PAPER"}
