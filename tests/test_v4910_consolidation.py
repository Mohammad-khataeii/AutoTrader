"""Source-only regression coverage for the shared research engine."""
import pytest

from autotrader.learning.consolidation import Source, retain
from autotrader.learning.consolidation_model import one_per_episode, purged, score, train
from autotrader.learning.consolidation_ops import archive_copy, archive_plan, require_capacity
from autotrader.learning.consolidation_review import (
    costed_path, eligible_feature, gate_evidence, reconcile_position, rejection_class, sizing_advice,
)
from autotrader.learning.consolidation_schema import migrate
from autotrader.learning.store import Store
from autotrader.research.data import canonical
from deploy.capacity import forecast

AT = "2026-10-01T00:00:02.000000+00:00"
CAPTURED = "2026-10-02T00:00:00.000000+00:00"


@pytest.fixture
def store(tmp_path):
    result=Store(tmp_path/"research")
    migrate(result)
    try:
        yield result
    finally:
        result.close()


def test_deduplicates_market_content_but_keeps_source_keys_and_known_time_unknown(store):
    first=Source("official","OPERATIONAL","paper-eur",{},"RETAINED")
    second=Source("shadow","SHADOW","research",{},"PAUSED")
    row={"symbol":"SOL-EUR","source":"revolut-x-mid","timeframe":"5m",
         "timestamp":"2026-10-01T00:00:00Z","open":"100","high":"102","low":"99","close":"101","volume":"5"}
    assert retain(store,first,"market_candles","1",canonical({**row,"id":1}).decode(),CAPTURED)
    assert retain(store,second,"market_candles","19",canonical({**row,"id":19}).decode(),CAPTURED)
    assert retain(store,second,"market_candles","19",canonical({**row,"id":19}).decode(),CAPTURED)
    assert store.db.execute("SELECT count(*) FROM research_content").fetchone()==(1,)
    assert store.db.execute("SELECT record_id,known_at FROM research_refs ORDER BY source").fetchall()==[("1",None),("19",None)]
    assert store.db.execute("SELECT count(*) FROM research_versions").fetchone()==(2,)


def test_rejects_unclosed_or_contradictory_candles(store):
    source=Source("official","OPERATIONAL","paper-eur",{},"RETAINED")
    row={"symbol":"SOL-EUR","source":"revolut-x-mid","timeframe":"5m",
         "timestamp":"2026-10-01T00:00:00Z","open":"100","high":"102","low":"99","close":"101","volume":"5"}
    assert not retain(store,source,"market_candles","1",canonical(row).decode(),AT)
    assert not retain(store,source,"market_candles","2",canonical({**row,"low":"105"}).decode(),CAPTURED)
    assert store.db.execute("SELECT count(*) FROM research_errors").fetchone()==(2,)


def test_late_signal_is_never_available_to_an_earlier_decision(store):
    source=Source("personal","PERSONAL","personal",{},"RETAINED")
    signal={"signal_id":"signal","strategy_id":"RAOE_EARLY_RECOVERY","symbol":"SOL-EUR",
            "created_at":"2026-10-01T00:00:03Z","timestamp":"2026-09-30T23:55:00Z",
            "data_quality":"GOOD","payload_json":'{"evidence":{}}'}
    assert retain(store,source,"strategy_signals","signal",canonical(signal).decode(),CAPTURED)
    with pytest.raises(ValueError,match="late_ingestion"):
        eligible_feature(store,source.database,signal,AT)


def test_duplicate_outcome_cannot_change_episode_representative_and_purge_covers_overlap():
    row={"role":"PERSONAL","episode":"same","observed_at":AT,
         "end_at":"2026-10-01T04:00:02.000000+00:00","source":"personal","record_id":"p","task_id":"p"}
    shadow={**row,"role":"SHADOW","source":"shadow","target":{"net_return":10},"task_id":"s"}
    assert one_per_episode([shadow,row])==[row]
    assert purged([row],"2026-10-02T00:00:00Z")==[]
    assert purged([row],"2026-10-03T00:00:00Z")==[row]


def event():
    return {"observed_at":AT,"symbol":"SOL-EUR","evidence":{
        "entry_plan":{"stop":"99","targets":["101","102","103"]},"economics":{"measurements":{
            "entry":{"vwap":"100","spread_bps":"0"},"exit_now":{"depth_impact_bps":"0"},
            "cost_basis_eur":"100.1","fillable_quantity":"1","holding_bars":12,
            "partial_exit_fractions":[".3",".4",".3"],"assumptions":{"exit_fee_bps":"10","slippage_bps":"10"}}}}}


def bars(high="101.05",low="99.5"):
    return [{"symbol":"SOL-EUR","source":"revolut-x-mid","timestamp":f"2026-10-01T00:{minute}:00Z",
             "open":"100","high":high,"low":low,"close":"100"} for minute in ("05","10")]


def test_target_must_cover_exit_cost_and_ambiguous_candle_is_stop_first():
    result=costed_path(event(),bars(),15)
    assert result["exit_reason"]=="HORIZON"
    assert result["target_bid_triggers"][0]>101.05
    assert result["net_return"]<0
    assert result["executable_outcome_proven"] is False
    ambiguous=costed_path(event(),bars("104","98"),15)
    assert ambiguous["ambiguous"]
    assert ambiguous["exit_reason"]=="STOP_FIRST_CONSERVATIVE"
    with pytest.raises(ValueError,match="incomplete_future_window"):
        costed_path(event(),bars()[:1],15)


def test_financial_chain_reconciles_fees_once():
    position={"position_id":"p","account_id":"a","state":"CLOSED","closed_at":AT,
              "initial_stop":"99","realized_pnl":"-2"}
    common={"account_id":"a","quantity":"1","price":"100","fee":"1",
            "attribution_status":"CONFIRMED","simulated":True}
    fills=[{**common,"fill_id":"buy","side":"BUY"},{**common,"fill_id":"sell","side":"SELL"}]
    journal=[{"ledger_event_id":key,"fill_id":key,"account_id":"a","currency":"EUR",
              "reconciliation_state":"CONFIRMED","realized_pnl_delta":net}
             for key,net in (("buy","0"),("sell","-2"))]
    result=reconcile_position(position,fills,journal,[{"filled_quantity":"0"}])
    assert result["status"]=="RECONCILED"
    assert result["net_return"]==pytest.approx(-2/101)
    assert result["fees_eur"]=="2"
    assert reconcile_position(position,fills,journal[:1],[])["status"]=="FINANCIAL_MISMATCH"


def test_rejection_reason_tokens_are_not_failed_gate_evidence():
    evidence={"reasons":["review_target_cost_headroom"],
              "quality_policy":{"gates":{"review_target_cost_headroom":True,"review_stop_above_noise":False}}}
    result=gate_evidence(evidence)
    assert result["structured"]["quality_policy"]["failed"]==["review_stop_above_noise"]
    assert rejection_class("shadow_frozen_source_changed")=="FROZEN_SOURCE_AUTHORITY"
    assert rejection_class("risk_rejected:planned_loss")=="PLANNED_LOSS_LIMIT"


def test_insufficient_sample_publishes_no_model_and_scoring_defaults_to_abstain(store):
    result=train(store,horizon=240,holdout_start="2026-01-01T00:00:00Z",
                 holdout_end="2026-02-01T00:00:00Z",untouched=True)
    assert result["status"]=="INSUFFICIENT_EVIDENCE"
    assert "model" not in result
    assert store.read_artifact(result["model_id"])["automatic_promotion"] is False
    assert score(store,{},now=AT,enabled=True,paper_only=True,baseline_eligible=True)["status"]=="ABSTAIN_DISABLED"


def test_active_cap_counts_creating_and_never_auto_pauses():
    records=[{"experiment_id":str(i),"state":state}
             for i,state in enumerate(("SHADOW_ACTIVE","SHADOW_ACTIVE","CREATING"))]
    with pytest.raises(ValueError,match="active_shadow_cap"):
        require_capacity(records,3)
    assert require_capacity(records,3,existing="0")==3
    official={"role":"OPERATIONAL","identity":"official","archived":False,"state":"RETAINED"}
    plan=archive_plan([official])
    assert plan["records"][0]["recommendation"]=="PROTECTED_FINANCIAL"
    assert plan["automatic_actions"]==[]


def test_archive_refuses_without_exact_scope_and_external_mount(store,tmp_path):
    source=Source("autotrader_shadow_"+"a"*32,"SHADOW","test",{},"STOPPED")
    output=tmp_path/"archive.gz"
    with pytest.raises(ValueError,match="confirmation"):
        archive_copy(store,source,output,{},confirmation="wrong")
    with pytest.raises(ValueError,match="separate_volume"):
        archive_copy(store,source,output,{},confirmation="test")
    assert not output.exists()


def test_capacity_combines_shared_disk_reservations_and_retains_restore_margin():
    shared=(1,12_000)
    report=forecast({"official":1000,"paper":2000,"shadow":1000},backup_fs=shared,
                    docker_fs=shared,transfer_fs=shared,image_bytes=400,transfer_bytes=100,
                    extra_temp_bytes=10,reserve_bytes=100)
    assert report["database_count"]==3
    assert len(report["filesystems"])==1
    assert report["assumptions"]["dump_allowance_bytes"]==4600
    assert report["filesystems"][1]["reservations"]["isolated_restore"]>=2*4000+4600
    assert report["status"]=="INSUFFICIENT_CAPACITY"
    assert report["restore_verification_still_required"]


def test_sizing_respects_remaining_risk_and_volatility_floor():
    result=sizing_advice(stop_fraction=.0028,cost_fraction=.004,atr_fraction=.01,
                         risk_budget=35,remaining_risk=5,max_notional=700,available_cash=500)
    assert result["suggested_notional"]==pytest.approx(5/.014)
    assert result["stop_inside_one_atr"] is True
