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



def test_alpaca_held_stop_reconciles_unverified_without_duplicate_order(monkeypatch,tmp_path):
    """Nov 11 real broker shape: OCO parent=new, contingent stop=held."""
    _setup(monkeypatch,tmp_path)
    monkeypatch.setenv("STOCKSWATCH_EXECUTION_BACKEND","alpaca_paper")
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS","1")
    monkeypatch.setenv("STOCKSWATCH_PROTECTION_ALLOW_PAPER_ORDERS","1")
    client=FakeClient()
    plan=profit_lock.initial("100","10","2")
    profit_oco._create(client,"account-1",{"symbol":"AAPL","qty":"10"},
                       plan,"swp2-entry",datetime.now(UTC),D("100"))
    original=profit_oco._saved("account-1","AAPL")
    with storage.connect() as c:
        c.execute("UPDATE sw_protection SET state='UNVERIFIED',"
                  "broker_stop=NULL,last_error='protection_oco_stop_missing' "
                  "WHERE account_id=? AND symbol=?",("account-1","AAPL"))
    root=_root(original,plan.initial_stop)
    root["legs"][0]["status"]="held"
    client.get=lambda path,args: [root]
    monkeypatch.setattr(profit_oco,"_entry_id",lambda account,symbol:"swp2-entry")
    from stockswatch import alpaca_paper as paper
    monkeypatch.setattr(paper,"_position_owned",lambda *args:True)
    snapshot={
        "account":{"id":"account-1"},
        "warnings":{"fills":False,"open_orders":False},
        "positions":[{"symbol":"AAPL","asset_class":"us_equity","side":"long",
                      "qty":"10","qty_available":"0","avg_entry_price":"100"}],
        "open_orders":[{"id":root["id"],"symbol":"AAPL"}],
        "fills":[]
    }
    # Wednesday 10am New York: market CORE, reconciliation allowed.
    from datetime import datetime as dt
    outcome=profit_oco.cycle(client,snapshot,now=dt(2026,11,11,15,tzinfo=UTC))
    saved=profit_oco._saved("account-1","AAPL")
    assert saved["state"]=="ACTIVE" and saved["last_error"] is None
    assert D(saved["broker_stop"])==plan.initial_stop
    assert outcome["positions"][0]["verified_broker_stop"]==str(plan.initial_stop)
    assert len(client.orders)==1 # only the original mocked OCO POST


def test_held_stop_must_cover_identical_shares_and_symbol(monkeypatch,tmp_path):
    _setup(monkeypatch,tmp_path)
    client=FakeClient()
    plan=profit_lock.initial("100","10","2")
    profit_oco._create(client,"account-1",{"symbol":"AAPL","qty":"10"},
                       plan,"swp2-entry",datetime.now(UTC),D("100"))
    record=profit_oco._saved("account-1","AAPL")
    root=_root(record,plan.initial_stop)
    root["legs"][0]["status"]="held"
    assert profit_oco._sync(client,record,[root])=="active_oco_verified"
    root["legs"][0]["qty"]="9"
    with pytest.raises(profit_oco.ProtectionError,match="quantity_or_symbol_mismatch"):
        profit_oco._validate_pair(root,profit_oco._saved("account-1","AAPL"))
    root["legs"][0]["qty"]="10"
    root["legs"][0]["symbol"]="MSFT"
    with pytest.raises(profit_oco.ProtectionError,match="quantity_or_symbol_mismatch"):
        profit_oco._validate_pair(root,profit_oco._saved("account-1","AAPL"))
    root["legs"][0]["symbol"]="AAPL"
    root["legs"][0]["status"]="canceled"
    with pytest.raises(profit_oco.ProtectionError,match="protection_oco_stop_missing"):
        profit_oco._validate_pair(root,profit_oco._saved("account-1","AAPL"))


def test_parent_held_does_not_count_as_active_oco(monkeypatch,tmp_path):
    _setup(monkeypatch,tmp_path)
    client=FakeClient()
    plan=profit_lock.initial("100","10","2")
    profit_oco._create(client,"account-1",{"symbol":"AAPL","qty":"10"},
                       plan,"swp2-entry",datetime.now(UTC),D("100"))
    record=profit_oco._saved("account-1","AAPL")
    root=_root(record,plan.initial_stop)
    root["status"]="held"
    root["legs"][0]["status"]="held"
    with pytest.raises(profit_oco.ProtectionError,match="protection_oco_parent_invalid"):
        profit_oco._validate_pair(root,record)

def test_disarmed_by_default(monkeypatch,tmp_path):
    _setup(monkeypatch,tmp_path)
    monkeypatch.setenv("STOCKSWATCH_EXECUTION_BACKEND","alpaca_paper")
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS","1")
    monkeypatch.delenv("STOCKSWATCH_PROTECTION_ALLOW_PAPER_ORDERS",raising=False)
    assert profit_oco.armed() is False
    monkeypatch.setenv("STOCKSWATCH_PROTECTION_ALLOW_PAPER_ORDERS","1")
    assert profit_oco.armed() is True


def test_adoption_of_already_profitable_stock_starts_with_raised_stop(monkeypatch,tmp_path):
    _setup(monkeypatch,tmp_path)
    client=FakeClient()
    # 40 shares at $100; ATR<1 -> initial risk $3/share and $300 TP.
    plan=profit_lock.initial("100","40","0.48")
    assert str((plan.target-plan.entry)*plan.qty)=="300.00"
    bid=D("106.25")  # current open gain $250 out of $300
    result=profit_oco._create(client,"account-1",{"symbol":"AAPL","qty":"40"},
                            plan,"swp2-entry",datetime.now(UTC),bid)
    assert result.startswith("oco_submitted")
    payload=client.orders[0][2]
    locked=D(payload["stop_loss"]["stop_price"])
    assert (locked-plan.entry)*plan.qty>=D("150")
    assert locked>plan.initial_stop
    assert locked<bid
    saved=profit_oco._saved("account-1","AAPL")
    assert D(saved["current_stop"])==locked


def test_near_target_is_rejected_instead_of_extending_tp(monkeypatch,tmp_path):
    _setup(monkeypatch,tmp_path)
    client=FakeClient()
    plan=profit_lock.initial(100,10,2)
    with pytest.raises(profit_oco.ProtectionError,match="near_or_beyond_tp"):
        profit_oco._create(client,"account-1",{"symbol":"AAPL","qty":"10"},
                           plan,"swp2-entry",datetime.now(UTC),D("112.49"))
    assert client.orders==[]
