"""Mock-only OCO broker tests. Never contact Alpaca or change real paper orders."""
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from stockswatch import profit_oco, profit_lock, storage

UTC=timezone.utc


def _setup(monkeypatch,tmp_path):
    monkeypatch.setattr(storage,"DB_PATH",str(tmp_path/"profit.sqlite3"))
    storage.init()
    profit_oco.initialize()


class FakeClient:
    def __init__(self,uncertain=False):
        self.orders=[]
        self.uncertain=uncertain

    def _request(self,method,path,**kwargs):
        assert path.startswith("/v2/orders")
        self.orders.append((method,path,kwargs.get("json")))
        if self.uncertain:
            raise RuntimeError("transport uncertainty fixture")
        if method=="POST":
            p=kwargs["json"]
            assert p["order_class"]=="oco" and p["type"]=="limit"
            assert p["side"]=="sell" and p["time_in_force"]=="gtc"
            return {"id":"root-12345678","client_order_id":p["client_order_id"],
                    "order_class":"oco","symbol":p["symbol"],"side":"sell"}
        if method=="PATCH":
            assert set(kwargs["json"])=={"stop_price"}
            return {"id":"stop-12345678","side":"sell"}
        raise AssertionError("unexpected method")


def _root(row,stop):
    return {"id":"root-12345678","client_order_id":row["client_id"],
        "symbol":row["symbol"],"side":"sell","type":"limit","order_class":"oco",
        "status":"new","time_in_force":"gtc","qty":row["qty"],
        "limit_price":row["target"],"legs":[{
            "id":"stop-12345678","symbol":row["symbol"],
            "side":"sell","type":"stop","status":"new","stop_price":str(stop),
            "qty":row["qty"],
        }]}


def test_oco_create_is_durable_and_single_submission(monkeypatch,tmp_path):
    _setup(monkeypatch,tmp_path)
    client=FakeClient()
    plan=profit_lock.initial("100",10,"2")
    p={"symbol":"AAPL","qty":"10"}
    r=profit_oco._create(client,"account-1",p,plan,"swp2-entry",datetime.now(UTC),D("100"))
    assert r.startswith("oco_submitted")
    row=profit_oco._saved("account-1","AAPL")
    assert row["state"]=="ACKNOWLEDGED" and row["root_order_id"]=="root-12345678"
    assert len(client.orders)==1
    assert profit_oco._create(client,"account-1",p,plan,"swp2-entry",datetime.now(UTC),D("100"))=="existing_protection_record"
    assert len(client.orders)==1


def test_post_transport_uncertainty_never_submits_twice(monkeypatch,tmp_path):
    _setup(monkeypatch,tmp_path)
    client=FakeClient(uncertain=True)
    plan=profit_lock.initial(100,10,2)
    p={"symbol":"AAPL","qty":"10"}
    assert profit_oco._create(client,"account-1",p,plan,"swp2-entry",datetime.now(UTC),D("100"))=="create_uncertain_blocked"
    assert profit_oco._saved("account-1","AAPL")["state"]=="UNKNOWN"
    assert profit_oco._create(client,"account-1",p,plan,"swp2-entry",datetime.now(UTC),D("100"))=="existing_protection_record"
    assert len(client.orders)==1


def test_confirmed_oco_stop_is_monotone_and_replacement_is_not_replayed(monkeypatch,tmp_path):
    _setup(monkeypatch,tmp_path)
    client=FakeClient()
    plan=profit_lock.initial(100,10,2)
    p={"symbol":"AAPL","qty":"10"}
    profit_oco._create(client,"account-1",p,plan,"swp2-entry",datetime.now(UTC),D("100"))
    row=profit_oco._saved("account-1","AAPL")
    assert profit_oco._sync(client,row,[_root(row,plan.initial_stop)])=="active_oco_verified"
    row=profit_oco._saved("account-1","AAPL")
    assert row["state"]=="ACTIVE"
    outcome=profit_oco._ratchet(client,row,_root(row,plan.initial_stop),
                  "stop-12345678",plan.initial_stop,D("110"),datetime.now(UTC).isoformat())
    assert outcome=="stop_replace_requested_pending_broker_proof"
    assert len(client.orders)==2
    assert D(client.orders[-1][2]["stop_price"])>plan.initial_stop
    row=profit_oco._saved("account-1","AAPL")
    assert row["state"]=="REPLACE_PENDING"
    with pytest.raises(profit_oco.ProtectionError,match="uncertain_intent"):
        profit_oco._ratchet(client,row,_root(row,plan.initial_stop),
                    "stop-12345678",plan.initial_stop,D("110"),datetime.now(UTC).isoformat())
    assert len(client.orders)==2
    assert profit_oco._sync(client,row,[_root(row,plan.initial_stop)])=="oco_replace_pending_no_repeat"
    assert profit_oco._saved("account-1","AAPL")["state"]=="REPLACE_PENDING"
    updated=profit_lock.decimal(row["requested_stop"])
    assert profit_oco._sync(client,row,[_root(row,updated)])=="active_oco_verified"
    fresh=profit_oco._saved("account-1","AAPL")
    assert fresh["state"]=="ACTIVE"
    assert profit_lock.decimal(fresh["current_stop"])==updated


def test_invalid_oco_sibling_is_refused(monkeypatch,tmp_path):
    _setup(monkeypatch,tmp_path)
    client=FakeClient()
    plan=profit_lock.initial(100,10,2)
    profit_oco._create(client,"account-1",{"symbol":"AAPL","qty":"10"},
                       plan,"swp2-entry",datetime.now(UTC),D("100"))
    row=profit_oco._saved("account-1","AAPL")
    fake=_root(row,plan.initial_stop)
    fake["legs"][0]["type"]="limit"
    assert profit_oco._sync(client,row,[fake])=="oco_leg_verification_failed"
    assert profit_oco._saved("account-1","AAPL")["state"]=="UNVERIFIED"


def test_disarmed_by_default(monkeypatch,tmp_path):
    _setup(monkeypatch,tmp_path)
    monkeypatch.setenv("STOCKSWATCH_EXECUTION_BACKEND","alpaca_paper")
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS","1")
    monkeypatch.delenv("STOCKSWATCH_PROTECTION_ALLOW_PAPER_ORDERS",raising=False)
    assert profit_oco.armed() is False
    monkeypatch.setenv("STOCKSWATCH_PROTECTION_ALLOW_PAPER_ORDERS","1")
    assert profit_oco.armed() is True
