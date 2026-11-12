"""Nov 11 broker evidence: HELD OCO stop children must not deadlock protection.

Pure Alpaca fixtures, transient SQLite only. No broker requests or orders.
"""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from stockswatch import profit_oco as po, profit_lock, storage, alpaca_paper as paper

NOW=datetime(2026,11,11,15,26,tzinfo=timezone.utc)
CASES=[
    ("AAPL","33","351.08","329.12","405.98"),
    ("ABBV","40","294.25","275.61","340.85"),
]

def fixture(symbol,qty,entry,stop,target):
    return {
        "account_id":"paper-account",
        "symbol":symbol, "client_id":"swg1-test-"+symbol,
        "entry_client_id":"swp2-entry-"+symbol,
        "qty":qty,"entry":entry,"atr":"2.5",
        "target":target,"current_stop":stop,
        "root_order_id":"root-"+symbol+"-12345678",
        "stop_leg_id":None,
        "state":"UNVERIFIED"
    }

def root(record):
    return {
        "id":record["root_order_id"],"client_order_id":record["client_id"],
        "symbol":record["symbol"],"side":"sell","type":"limit",
        "status":"new","order_class":"oco","time_in_force":"gtc",
        "qty":record["qty"],"limit_price":record["target"],
        "legs":[{
            "id":"held-stop-"+record["symbol"]+"-12345678",
            "symbol":record["symbol"],"side":"sell","type":"stop",
            "status":"held","order_class":"oco",
            "qty":record["qty"],"stop_price":record["current_stop"]
        }]
    }

@pytest.mark.parametrize("symbol,qty,entry,stop,target",CASES)
def test_alpaca_held_stop_verified_as_real_broker_leg(symbol,qty,entry,stop,target):
    record=fixture(symbol,qty,entry,stop,target)
    leg,level=po._validate_pair(root(record),record)
    assert leg=="held-stop-"+symbol+"-12345678"
    assert level==Decimal(stop)

@pytest.mark.parametrize("state",["canceled","rejected","expired","filled","pending_cancel"])
def test_held_does_not_allow_terminal_or_canceling_stop(state):
    record=fixture(*CASES[0])
    order=root(record)
    order["legs"][0]["status"]=state
    with pytest.raises(po.ProtectionError,match="stop_missing"):
        po._validate_pair(order,record)

def test_parent_held_is_not_accepted_as_active_limit():
    record=fixture(*CASES[0])
    order=root(record)
    order["status"]="held"
    with pytest.raises(po.ProtectionError,match="parent_invalid"):
        po._validate_pair(order,record)

def test_undercovering_stop_quantity_refused():
    record=fixture(*CASES[0])
    order=root(record)
    order["legs"][0]["qty"]="1"
    with pytest.raises(po.ProtectionError,match="stop_quantity_mismatch"):
        po._validate_pair(order,record)

def test_unverified_recovers_via_get_without_post_then_arms_next_cycle(monkeypatch,tmp_path):
    monkeypatch.setattr(storage,"DB_PATH",str(tmp_path/"stockswatch.sqlite3"))
    storage.init()
    paper.broker_init()
    # Simulate a persisted OCO that went UNVERIFIED solely because Alpaca
    # reported the stop child as HELD during Nov 10's broker check.
    base=fixture(*CASES[0])
    with storage.connect() as db:
        db.execute("""INSERT INTO sw_protection
          (account_id,symbol,entry_client_id,qty,entry,atr,initial_stop,
           current_stop,target,highwater,client_id,root_order_id,state,updated_at,last_error)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
           base["account_id"],base["symbol"],base["entry_client_id"],
           base["qty"],base["entry"],base["atr"],base["current_stop"],
           base["current_stop"],base["target"],base["entry"],base["client_id"],
           base["root_order_id"],"UNVERIFIED",NOW.isoformat(),"protection_oco_stop_missing"))
    pos={"symbol":"AAPL","asset_class":"us_equity","side":"long",
         "qty":"33","qty_available":"0","avg_entry_price":"351.08"}
    snap={"account":{"id":"paper-account"},"positions":[pos],"open_orders":[root(base)],
          "fills":[{"id":"proof"}],"warnings":{}}
    client=object()
    with patch.object(po,"armed",return_value=True), \
         patch("stockswatch.intraday_policy.phase_at",return_value=SimpleNamespace(name="CORE")), \
         patch.object(po,"_nested",return_value=[root(base)]) as nested, \
         patch.object(po,"_entry_id",return_value=base["entry_client_id"]), \
         patch.object(po,"_ratchet",return_value="no_change") as ratchet, \
         patch.object(po,"_find_live_quote",return_value=(Decimal("351.08"),NOW.isoformat())) as quote, \
         patch.object(paper,"_position_owned",return_value=True):
        first=po.cycle(client,snap,NOW,data=object())
        # The first cycle is GET-only even though it restores ACTIVE in DB.
        assert nested.call_count==1
        ratchet.assert_not_called()
        assert first["status"]=="OBSERVING"
        assert first["paper_orders_enabled"] is False
        assert po._saved("paper-account","AAPL")["state"]=="ACTIVE"
        assert po._saved("paper-account","AAPL")["broker_stop"]=="329.12"
        second=po.cycle(client,snap,NOW,data=object())
        assert second["status"]=="PAPER_OCO_MONITORING"
        assert second["paper_orders_enabled"] is True
        assert second["positions"][0]["verified_broker_stop"]=="329.12"
        ratchet.assert_called_once()
        quote.side_effect=po.ProtectionError("protection_quote_timestamp_stale")
        third=po.cycle(client,snap,NOW,data=object())
        assert third["positions"][0]["verified_broker_stop"]=="329.12"
        assert third["positions"][0]["reason"]=="protection_quote_timestamp_stale"
        ratchet.assert_called_once()
        quote.side_effect=None
        def uncertain(client, record, *args):
            po._set_state(record, "REPLACE_UNCERTAIN", requested=Decimal("330"))
            return "replace_uncertain_blocked"
        ratchet.side_effect=uncertain
        fourth=po.cycle(client,snap,NOW,data=object())
        assert fourth["changed"]
        assert fourth["positions"][0]["broker_state"]=="REPLACE_UNCERTAIN"
        assert fourth["positions"][0]["verified_broker_stop"] is None

def test_unverified_missing_root_stays_blocked(monkeypatch,tmp_path):
    monkeypatch.setattr(storage,"DB_PATH",str(tmp_path/"stockswatch.sqlite3"))
    storage.init()
    paper.broker_init()
    rec=fixture(*CASES[0])
    with storage.connect() as db:
        db.execute("""INSERT INTO sw_protection
          (account_id,symbol,entry_client_id,qty,entry,atr,initial_stop,
           current_stop,target,highwater,client_id,root_order_id,state,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
            rec["account_id"],rec["symbol"],rec["entry_client_id"],rec["qty"],
            rec["entry"],rec["atr"],rec["current_stop"],rec["current_stop"],
            rec["target"],rec["entry"],rec["client_id"],rec["root_order_id"],
            "UNVERIFIED",NOW.isoformat()))
    pos={"symbol":"AAPL","asset_class":"us_equity","side":"long",
         "qty":"33","qty_available":"0","avg_entry_price":"351.08"}
    snap={"account":{"id":"paper-account"},"positions":[pos],
          "open_orders":[{"symbol":"AAPL","id":"different"}],
          "fills":[],"warnings":{}}
    with patch.object(po,"armed",return_value=True), \
         patch("stockswatch.intraday_policy.phase_at",return_value=SimpleNamespace(name="CORE")), \
         patch.object(po,"_nested",return_value=[]), \
         patch.object(po,"_entry_id",return_value=rec["entry_client_id"]):
        result=po.cycle(object(),snap,NOW,data=object())
    assert result["paper_orders_enabled"] is False
    assert po._saved("paper-account","AAPL")["state"]=="UNVERIFIED"
