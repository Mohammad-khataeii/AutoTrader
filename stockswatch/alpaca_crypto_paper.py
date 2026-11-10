"""Strict Alpaca PAPER-ONLY crypto spot execution. No crypto shorts or leverage.

Shares the existing verified Alpaca stock PAPER account by default, while
maintaining an independent crypto order journal and strict asset-class
isolation. Only paper credentials are accepted; live trading is never used.
Default is observation-only. A pending/uncertain intent is never replayed.
"""
from __future__ import annotations

import hashlib
import json
import logging
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
log=logging.getLogger(__name__)
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
    """Reuse StocksWatch Alpaca *paper* credentials unless explicitly overridden.

    Never use market-data or real-money keys. A partial crypto override is
    configuration error, not permission to silently fall back.
    """
    key=os.getenv("ALPACA_CRYPTO_PAPER_KEY","").strip()
    secret=os.getenv("ALPACA_CRYPTO_PAPER_SECRET","").strip()
    if bool(key)!=bool(secret):
        raise CryptoPaperError("crypto_partial_paper_credentials")
    if not key:
        key=os.getenv("STOCKSWATCH_ALPACA_PAPER_KEY","").strip()
        secret=os.getenv("STOCKSWATCH_ALPACA_PAPER_SECRET","").strip()
    if not key or not secret:
        raise CryptoPaperError("crypto_paper_credentials_missing")
    return {"APCA-API-KEY-ID":key,"APCA-API-SECRET-KEY":secret}


def expected_account():
    # Alpaca supports equities and crypto in one paper account. An explicit
    # alternate account must still match the broker; no forced second account.
    expected=(os.getenv("ALPACA_CRYPTO_PAPER_ACCOUNT_ID","").strip()
              or os.getenv("STOCKSWATCH_ALPACA_PAPER_ACCOUNT_ID","").strip())
    if not expected:
        raise CryptoPaperError("crypto_paper_expected_account_missing")
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
        # Never silently migrate existing crypto intents to another account.
        # Sharing the already-verified STOCK account is explicitly allowed.
        prior=one("SELECT configured_account FROM ac_state WHERE id=1")
        if prior and prior.get("configured_account") and prior["configured_account"]!=account["id"]:
            raise CryptoPaperError("crypto_existing_account_conflict")
        if one("SELECT 1 FROM ac_intents WHERE account_id!=? LIMIT 1",(account["id"],)):
            raise CryptoPaperError("crypto_existing_intents_account_conflict")
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
        all_positions=self.request("GET","/v2/positions")
        all_orders=self.request("GET","/v2/orders",params={"status":"open","limit":500,"nested":"false"})
        if not all(isinstance(x,list) and all(isinstance(y,dict) for y in x)
                   for x in (all_positions,all_orders)) or len(all_orders)>=500:
            raise CryptoPaperError("crypto_broker_book_incomplete")
        # One Alpaca Paper account can hold stock and crypto assets. Partition
        # the account's broker book by Alpaca-reported asset_class; never treat
        # AAPL/ABBV or their pending SELLs as crypto inventory.
        from .universe import ASSETS
        stock_symbols={a[0] for a in ASSETS}
        crypto_symbols=set(ac.PAIRS)|{s.replace("/","") for s in ac.PAIRS}
        def asset_kind(item):
            cls=item.get("asset_class")
            if cls in ("crypto","us_equity"):
                return cls
            symbol=item.get("symbol")
            if symbol in crypto_symbols:
                return "crypto"
            if symbol in stock_symbols:
                return "us_equity"
            # Unknown instrument types must not be silently hidden.
            raise CryptoPaperError("crypto_shared_account_unknown_asset_class")
        positions=[];other_positions=[];orders=[];other_orders=[]
        for p in all_positions:
            (positions if asset_kind(p)=="crypto" else other_positions).append(p)
        for o in all_orders:
            if not o.get("id") or not o.get("symbol") or not o.get("status"):
                raise CryptoPaperError("crypto_broker_order_incomplete")
            (orders if asset_kind(o)=="crypto" else other_orders).append(o)
        if any(not p.get("symbol") or p.get("side")!="long" or money(p.get("qty"))<=0 for p in positions):
            raise CryptoPaperError("crypto_broker_unclassified_position")
        return {"account":account,"positions":positions,"orders":orders,
                "other_positions":other_positions,"other_open_orders":other_orders}

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
             order.get("symbol") not in ac.EXECUTION_PAIRS or order.get("type")!="market" or
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
        eligible=(symbol in ac.EXECUTION_PAIRS and a.get("class")=="crypto" and a.get("tradable") is True
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
            "verified_spot_only" if eligible else ("research_only_non_usd_quote" if symbol in ac.RESEARCH_ONLY_PAIRS else "not_verified_as_eligible_spot"),
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


def refresh_known_orders(client, snapshot):
    """Broker order states are evidence; a local ACK is not a broker fill."""
    candidates=rows("""SELECT client_id,symbol,side,broker_status FROM ac_intents
          WHERE state='ACKNOWLEDGED' AND (broker_status IS NULL OR
             broker_status NOT IN ('filled','canceled','expired','rejected','replaced'))
          ORDER BY created_at DESC LIMIT 8""")
    for item in candidates:
        try:
            order=client.by_client_id(item["client_id"])
        except CryptoPaperError:
            continue
        if not isinstance(order,dict) or order.get("client_order_id")!=item["client_id"] or (
           order.get("symbol") not in (item["symbol"],item["symbol"].replace("/",""))
           or order.get("side")!=item["side"] or not order.get("id")):
            continue
        status=order.get("status")
        if status in TERMINAL|{"new","accepted","pending_new","partially_filled"}:
            with connect() as c:
                c.execute("""UPDATE ac_intents SET broker_status=?,last_checked=?
                    WHERE client_id=? AND state='ACKNOWLEDGED'""",
                    (status,utc(),item["client_id"]))
    # Never discard a stop until a filled, owned SELL and an independently
    # observed missing broker position agree. Canceled orders are not exits.
    current={_canonical(p["symbol"]) for p in snapshot["positions"]}
    for row in rows("""SELECT m.symbol,m.entry_client_id,m.entered_at FROM ac_managed m
         WHERE m.account_id=?""",(snapshot["account"]["id"],)):
        if row["symbol"] in current:
            continue
        sold=one("""SELECT 1 FROM ac_intents WHERE account_id=? AND symbol=?
            AND side='sell' AND state='ACKNOWLEDGED' AND broker_status='filled'
            AND created_at>=? LIMIT 1""",
            (snapshot["account"]["id"],row["symbol"],row["entered_at"]))
        rejected=one("""SELECT 1 FROM ac_intents WHERE client_id=?
             AND broker_status IN ('canceled','expired','rejected') LIMIT 1""",
            (row["entry_client_id"],))
        if sold or rejected:
            with connect() as c:
                c.execute("DELETE FROM ac_managed WHERE symbol=? AND entry_client_id=?",
                          (row["symbol"],row["entry_client_id"]))


def _canonical(symbol):
    if not isinstance(symbol,str):
        raise CryptoPaperError('crypto_broker_symbol_invalid')
    normalized = symbol if '/' in symbol else (
        symbol[:-3]+'/USD' if symbol.endswith('USD') else symbol)
    if normalized not in ac.EXECUTION_PAIRS:
        raise CryptoPaperError('crypto_broker_symbol_unlisted')
    return normalized


def _owned(snapshot):
    owned={r["symbol"] for r in rows("""SELECT DISTINCT symbol FROM ac_intents
         WHERE side='buy' AND state='ACKNOWLEDGED'""")}
    for p in snapshot["positions"]:
        if _canonical(p["symbol"]) not in owned:
            raise CryptoPaperError("crypto_unowned_broker_position")
    for o in snapshot["orders"]:
        if not any(o.get("client_order_id")==r["client_id"] for r in rows(
            "SELECT client_id FROM ac_intents WHERE state='ACKNOWLEDGED'")):
            raise CryptoPaperError("crypto_unowned_open_order")
    return {_canonical(p["symbol"]):p for p in snapshot["positions"]}


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


def _run_paper_cycle_once(data,now=None):
    """Broker recon + software stop/target; no orders unless separately enabled and unpaused."""
    now=now or datetime.now(UTC)
    # The same paper account used for stocks is valid for crypto; the client
    # resolves the credentials and verifies account identity before any action.
    with LOCK:
        try:
            with CryptoPaperClient() as client:
                snapshot=client.snapshot()
                account=snapshot["account"]["id"]
                with connect() as c:
                    c.execute("UPDATE ac_state SET configured_account=? WHERE id=1",(account,))
                    # Broker account truth is read-only and never reused as the stock ledger.
                    summary={k:snapshot["account"].get(k) for k in
                       ("currency","status","equity","cash","buying_power",
                        "non_marginable_buying_power","last_equity")}
                    positions=[{k:p.get(k) for k in
                       ("symbol","qty","side","market_value","cost_basis","unrealized_pl")}
                       for p in snapshot["positions"]]
                    c.execute("""INSERT INTO ac_broker_snapshot
                      (id,observed_at,account_json,positions_json,open_order_count)
                      VALUES(1,?,?,?,?)
                      ON CONFLICT(id) DO UPDATE SET observed_at=excluded.observed_at,
                       account_json=excluded.account_json,
                       positions_json=excluded.positions_json,
                       open_order_count=excluded.open_order_count""",
                       (utc(),json.dumps(summary),json.dumps(positions),len(snapshot["orders"])))
                if not enabled():
                    return "read_only_shared_paper_account"
                refresh_known_orders(client,snapshot)
                if not reconcile(client):
                    return "unresolved_order_intents_block_trading"
                pos=_owned(snapshot)
                # Never duplicate paper submissions while any broker order is open.
                if snapshot["orders"]:
                    return "broker_open_order_book_not_empty"
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
                    # Prevent repeated exit submissions when the broker position lags.
                    prior=one("""SELECT 1 FROM ac_intents WHERE symbol=? AND side='sell'
                          AND state='ACKNOWLEDGED' AND created_at>=? LIMIT 1""",
                          (symbol,m["entered_at"]))
                    if prior:continue
                    increment=money(asset["min_trade_increment"])
                    qty=(money(position["qty"])//increment)*increment
                    if qty < money(asset["min_order_size"]):
                        continue
                    reason="software_stop_at_fresh_bid" if bid<=float(m["stop"]) else "software_target_at_fresh_bid"
                    return _submit_intent(client,account,symbol,side,stamp,reason,qty=format(qty,"f"))
                # Pausing blocks entries but does not disable protection on
                # existing AlpacaCrypto-owned LONG positions.
                if bool((one("SELECT paused FROM ac_state WHERE id=1") or {}).get("paused",1)):
                    return "crypto_new_entries_paused"
                # Pending US-equity SELL-to-close orders do not reserve cash
                # for new crypto BUYs. Permit those existing stock exits while
                # blocking unknown sides, pending stock BUYs and unmatched qty.
                # Never cancel or modify the separate StocksWatch order book.
                stock_positions={p.get("symbol"):p for p in snapshot["other_positions"]}
                sell_qty={}
                for order in snapshot["other_open_orders"]:
                    symbol=order.get("symbol")
                    if order.get("side")!="sell" or symbol not in stock_positions:
                        return "crypto_shared_account_stock_orders_pending"
                    position=stock_positions[symbol]
                    if (position.get("side")!="long"
                            or position.get("asset_class")!="us_equity"
                            or not order.get("id") or not order.get("status")):
                        return "crypto_shared_account_stock_orders_unverified"
                    try:
                        outstanding=money(order.get("qty"))-money(order.get("filled_qty"))
                        held=money(position.get("qty"))
                    except CryptoPaperError:
                        return "crypto_shared_account_stock_orders_unverified"
                    if outstanding<=0 or held<=0:
                        return "crypto_shared_account_stock_orders_unverified"
                    sell_qty[symbol]=sell_qty.get(symbol,Decimal(0))+outstanding
                    if sell_qty[symbol]>held:
                        return "crypto_shared_account_stock_sells_exceed_holdings"
                equity,buying=_limits(snapshot,now)
                if any(p.get("side")!="long" for p in snapshot["positions"]):
                    raise CryptoPaperError("crypto_unrecognized_position_side")
                if len(pos)>=MAX_OPEN_POSITIONS or snapshot["orders"]:
                    return "crypto_position_or_open_order_limit"
                crypto_exposure=sum(abs(money(p.get("market_value"))) for p in pos.values())
                if crypto_exposure>=equity*CAP_CRYPTO_TOTAL:
                    return "crypto_total_exposure_cap"
                # A new hour must not be traded using the previous hour as
                # though it were the latest completed candle. Catch up only
                # missing crypto bars, at most once per 90 seconds.
                try:
                    refresh=ac.ensure_latest_completed_hourly(data,now)
                except ac.CryptoDataError as exc:
                    return "crypto_hourly_refresh_"+str(exc)
                # Missing data in a different USD pair must not veto a
                # fresh, independently verified candidate. signal() rejects
                # each incomplete or stale pair before producing BUY.
                if refresh not in (
                        "crypto_hourly_current", "crypto_hourly_caught_up",
                        "crypto_latest_completed_hourly_not_published",
                        "crypto_latest_hourly_retry_cooldown"):
                    return refresh
                signals=ac.scan(now)
                from .crypto_trade_safety import depth_limited_notional
                last_blocked = None
                for s in sorted(signals,key=lambda x:x["symbol"]):
                    if s["action"]!="BUY" or s["symbol"] in pos:continue
                    asset=_fresh_asset(s["symbol"],now)
                    try:
                        quote=data.latest_entry_quote(s["symbol"])
                    except ac.CryptoDataError as exc:
                        last_blocked = "crypto_entry_quote_missing_or_invalid"
                        ac.record_admission(s["symbol"],s["bar_at"],last_blocked,
                                            {"quote_status":str(exc)},now)
                        continue
                    bid,ask,stamp=quote["bid"],quote["ask"],quote["observed_at"]
                    quote_stats={"bid":bid,"ask":ask,
                                 "bid_size":quote["bid_size"],"ask_size":quote["ask_size"],
                                 "spread_pct":round(100*(ask-bid)/ask,4)}
                    if ask > float(s["price"])*1.02 or (ask-bid)/ask>0.015:
                        last_blocked="crypto_entry_spread_or_stale_signal"
                        ac.record_admission(s["symbol"],s["bar_at"],last_blocked,quote_stats,now)
                        continue
                    loss_per_unit=money(ask)-money(s["stop"])
                    if loss_per_unit<=0:
                        last_blocked="crypto_entry_stop_above_market"
                        ac.record_admission(s["symbol"],s["bar_at"],last_blocked,quote_stats,now)
                        continue
                    stop_fraction=loss_per_unit/money(ask)
                    budget=min(equity*CAP_PER_SYMBOL,
                               equity*CAP_CRYPTO_TOTAL-crypto_exposure,
                               buying*Decimal(".75"),
                               equity*RISK_PER_TRADE/stop_fraction)
                    budget=budget.quantize(Decimal(".01"),rounding=ROUND_DOWN)
                    if budget<MIN_TRADE_USD:
                        last_blocked="crypto_entry_portfolio_budget_below_minimum"
                        ac.record_admission(s["symbol"],s["bar_at"],last_blocked,quote_stats,now)
                        continue
                    # Prevent a paper market order larger than 20% of either
                    # currently displayed quote side. No synthetic order depth.
                    budget,depth_status=depth_limited_notional(
                        budget,ask,bid,quote["ask_size"],quote["bid_size"],
                        min_usd=str(MIN_TRADE_USD))
                    if budget is None:
                        last_blocked=depth_status
                        ac.record_admission(s["symbol"],s["bar_at"],last_blocked,quote_stats,now)
                        continue
                    quote_stats["approved_notional_usd"]=str(budget)
                    quote_stats["depth_decision"]=depth_status
                    ac.record_admission(s["symbol"],s["bar_at"],
                                        "crypto_entry_admitted",quote_stats,now)
                    outcome=_submit_intent(client,account,s["symbol"],"buy",s["bar_at"],
                            s["reason"],notional=str(budget))
                    try:
                        ac.record_admission(s["symbol"],s["bar_at"],outcome,quote_stats,now)
                    except ac.CryptoDataError:
                        log.warning("Crypto paper admission outcome not journaled")
                    if outcome=="paper_order_acknowledged":
                        with connect() as c:
                            c.execute("""INSERT INTO ac_managed
                                (symbol,account_id,entry_client_id,stop,target,entered_at)
                                VALUES(?,?,?,?,?,?)
                                ON CONFLICT(symbol) DO UPDATE SET account_id=excluded.account_id,
                                  entry_client_id=excluded.entry_client_id,stop=excluded.stop,
                                  target=excluded.target,entered_at=excluded.entered_at""",
                                (s["symbol"],account,_order_id(account,s["symbol"],s["bar_at"],"buy"),
                                 str(s["stop"]),str(s["target"]),utc()))
                    return outcome
                return (last_blocked or "no_approved_spot_long_signal")
        except CryptoPaperError as exc:
            with connect() as c:
                c.execute("UPDATE ac_state SET last_error=? WHERE id=1",(str(exc),))
            return str(exc)


def run_paper_cycle(data,now=None):
    """Record every crypto paper-cycle outcome without affecting stock cycles.

    Journal failures are non-fatal after a broker mutation; re-running a
    broker action to retry audit logging would risk duplicate orders.
    """
    now=now or datetime.now(UTC)
    try:
        outcome=_run_paper_cycle_once(data,now)
    except Exception as exc:
        try:
            ac.record_execution_outcome("crypto_cycle_exception_"+type(exc).__name__,now)
        except Exception:
            log.warning("AlpacaCrypto execution audit write failed after worker error")
        raise
    try:
        ac.record_execution_outcome(outcome,now)
    except Exception:
        log.warning("AlpacaCrypto execution audit write failed after broker cycle")
    return outcome


def set_paused(pause):
    if not pause and not enabled():
        raise CryptoPaperError("crypto_orders_not_enabled_on_server")
    with connect() as c:
        c.execute("UPDATE ac_state SET paused=? WHERE id=1",(int(pause),))
    return {"paused":pause,"mode":"ALPACA_CRYPTO_SPOT_PAPER"}


def read_only_order_journal():
    """Authenticated UI evidence from crypto-owned orders in Alpaca PAPER.

    Never submits, cancels or changes an order; never returns credentials.
    Only order IDs originating in this crypto strategy's durable intent table
    are displayed, even when the Alpaca account also holds stocks. A missing or unverifiable account is NOT a zero-order book.
    """
    try:
        with CryptoPaperClient() as client:
            snapshot = client.snapshot()
            account_id = snapshot["account"]["id"]
            known = {
                row["client_id"]: row for row in rows(
                    """SELECT client_id,account_id,symbol,side FROM ac_intents
                       WHERE account_id=? ORDER BY created_at DESC LIMIT 200""",
                    (account_id,),
                )
            }
            closed = client.request("GET", "/v2/orders", params={
                "status": "closed", "limit": 100, "direction": "desc",
                "nested": "false",
            })
            if not isinstance(closed,list) or any(not isinstance(o,dict) for o in closed):
                raise CryptoPaperError("crypto_closed_order_book_invalid")
            order_rows = []
            seen = set()
            for order in list(snapshot["orders"]) + closed:
                cid = order.get("client_order_id")
                intent = known.get(cid)
                if not intent or cid in seen:
                    continue
                symbol = order.get("symbol")
                if (symbol not in (intent["symbol"], intent["symbol"].replace("/", ""))
                        or order.get("side") != intent["side"] or not order.get("id")):
                    continue
                seen.add(cid)
                order_rows.append({
                    "client_order_id": cid,
                    "symbol": intent["symbol"],
                    "side": order.get("side"),
                    "state": order.get("status"),
                    "type": order.get("type"),
                    "qty": order.get("qty"),
                    "notional": order.get("notional"),
                    "filled_qty": order.get("filled_qty"),
                    "filled_avg_price": order.get("filled_avg_price"),
                    "limit_price": order.get("limit_price"),
                    "stop_price": order.get("stop_price"),
                    "submitted_at": order.get("submitted_at"),
                    "filled_at": order.get("filled_at"),
                    "created_at": order.get("created_at"),
                    "id": order.get("id"),
                })
            return {"available": True, "reason": None, "as_of": utc(),
                    "orders": order_rows, "open_broker_orders": len(snapshot["orders"]),
                    "owned_orders_in_window": len(order_rows)}
    except CryptoPaperError as exc:
        return {"available": False, "reason": str(exc), "as_of": utc(),
                "orders": [], "open_broker_orders": None}
