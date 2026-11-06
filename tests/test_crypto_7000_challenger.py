"""Research, forensic and ownership regressions without any order submission."""

from __future__ import annotations

import gzip
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from autotrader.api.trade_reports import completed_price_path
from autotrader.clock import at
from autotrader.crypto_research.audit import _filter, read_audit
from autotrader.crypto_research.context import PEERS, STEP, benchmark_context, entry_context
from autotrader.crypto_research.replay import INSUFFICIENT, estimate, replay
from autotrader.crypto_research.shadow import (
    capture,
    load_captures,
    registration,
    report,
    write_record,
)
from autotrader.domain import Candle, OrderBook, OrderBookLevel, TradingPair
from autotrader.market_data.service import MarketDataService
from autotrader.personal_paper.policy import fingerprint

STAMP = datetime(2026, 11, 6, 12, tzinfo=UTC)
SYMBOL = "SOL-EUR"
A3 = "A3_COST_AWARE_CONTINUATION"


def bars(symbol=SYMBOL, *, count=280, change=D(".02"), end=STAMP):
    result = []
    for i in range(count):
        price = D(100) + i * change
        result.append(
            Candle(
                symbol,
                end - (count - i) * STEP,
                price,
                price + D(".1"),
                price - D(".1"),
                price,
                D(100),
                "5m",
                "revolut-x",
            )
        )
    return result


def test_a3_observes_declining_benchmarks_on_local_advance():
    histories = {SYMBOL: bars(), **{s: bars(s, change=D("-.03")) for s in PEERS}}
    result = entry_context(SYMBOL, histories, STAMP, D(105), D(104), A3)
    assert result["asset_return_60m"] is not None and D(result["asset_return_60m"]) > 0
    assert result["macro"]["status"] == "READY"
    assert result["macro"]["regime"] in {"JOINT_DECLINE", "CORRELATED_SELLOFF"}
    assert result["checks"]["macro"] is False
    assert D(result["relative_return_60m"]) > 0


def test_incomplete_future_missing_and_duplicate_benchmark_bars():
    histories = {s: bars(s) for s in PEERS}
    expected = benchmark_context(histories, STAMP)
    histories[PEERS[0]].append(replace(histories[PEERS[0]][-1], timestamp=STAMP, close=D(5)))
    assert benchmark_context(histories, STAMP) == expected
    histories[PEERS[0]].pop(-2)
    assert benchmark_context(histories, STAMP)["status"] == INSUFFICIENT
    histories[PEERS[0]] = bars(PEERS[0])
    histories[PEERS[0]].append(histories[PEERS[0]][-1])
    assert benchmark_context(histories, STAMP)["status"] == INSUFFICIENT


def test_bearish_hourly_recovery():
    own = bars(change=D("-.1"))
    own[-1] = replace(own[-1], close=own[-1].high)
    result = entry_context(SYMBOL, {SYMBOL: own}, STAMP, D(73), D(72), "RAOE_EARLY_RECOVERY")
    assert result["hourly"] == "BEARISH"
    assert result["checks"]["recovery"] is False


@pytest.mark.parametrize(
    ("close", "expected"), [(D(107), "HELD_RETEST"), (D(104), "FAILED_BREAKOUT")]
)
def test_breakout_requires_hold_and_rejects_noise_sized_stop(close, expected):
    own = bars()
    own[-2] = replace(own[-2], open=D(106), high=D(107), close=D(106))
    own[-1] = replace(own[-1], open=D(106), high=D(108), low=D(104), close=close)
    histories = {SYMBOL: own, **{s: bars(s, change=D("-.03")) for s in PEERS}}
    result = entry_context(SYMBOL, histories, STAMP, D(107), D("106.99"), A3)
    assert result["structure"] == expected
    assert D(result["stop_atr"]) < 1
    assert result["checks"]["a3"] is False


def test_cluster_observes_only_realized_past_losses():
    prior = {"opened": STAMP - 3 * STEP, "closed": STAMP + STEP, "pnl": D(-1)}
    assert not _filter("cluster", {"context": {"checks": {}}, "submitted": STAMP}, [prior])
    prior["opened"] -= 12 * STEP
    assert _filter("cluster", {"context": {"checks": {}}, "submitted": STAMP}, [prior])
    assert not _filter(
        "cluster", {"context": {"checks": {}}, "submitted": STAMP + 2 * STEP}, [prior]
    )


def test_replay_dual_touch_adverse_gap_cost_and_missing_bar():
    setup = {
        "entry": D(100),
        "quantity": D(1),
        "stop": D(98),
        "target": D(103),
        "horizon": 2,
        "spread_bps": D(0),
        "fee_bps": D(10),
        "slippage_bps": D(8),
    }
    bar = Candle(SYMBOL, STAMP, D(97), D(105), D(96), D(101), D(1), "5m", "revolut-x")
    basic = replay([bar], STAMP, **setup)
    stress = replay([bar], STAMP, **setup, extra_bps=D(50))
    assert basic.kind == "STOP_FIRST" and basic.net < -3
    assert stress.net < basic.net
    assert basic.net == D(97) * D(".9992") - 100 - basic.fees
    assert replay([replace(bar, timestamp=STAMP + STEP)], STAMP, **setup) is None
    assert replay([bar], STAMP + timedelta(seconds=1), **setup) is None
    assert estimate([(STAMP, basic)])["probabilities"] is None


def test_cost_adjusted_giveback_requires_a_completed_progress_bar():
    setup = {
        "entry": D(100),
        "quantity": D(1),
        "stop": D(98),
        "target": D(104),
        "horizon": 2,
        "spread_bps": D(0),
        "fee_bps": D(10),
        "slippage_bps": D(8),
    }
    first = Candle(SYMBOL, STAMP, D(100), D(103), D(99), D(103), D(1), "5m", "revolut-x")
    second = replace(first, timestamp=STAMP + STEP, open=D(103), close=D("100.1"), low=D(99))
    result = replay([first, second], STAMP, **setup, policy="giveback")
    assert result.kind == "STOP_FIRST" and result.net > 0
    assert replay([first, second], STAMP, **setup).kind == "TIME"


def test_trade_path_censors_missing_candles_and_boundary_fragments():
    candles = bars(count=5, end=STAMP + 5 * STEP)
    position = SimpleNamespace(
        opened_at=STAMP + timedelta(seconds=30),
        closed_at=STAMP + 4 * STEP,
        average_entry_price=D(100),
    )
    result = completed_price_path(position, candles)
    assert result["status"] == "COMPLETED_OHLC_PROXY"
    assert result["observed_bars"] == 3
    assert completed_price_path(position, [candles[1], candles[3]])["mfe_fraction"] is None


def test_archive_rejects_wrong_account_and_count(tmp_path):
    path = tmp_path / "audit.jsonl.gz"
    header = {
        "section": "meta",
        "account": "OFFICIAL",
        "read_only": True,
        "source": "read_only_postgres_snapshot",
    }
    count = {"section": "counts", "rows": {"positions": 1}, "truncated_sections": []}

    def save():
        with gzip.open(path, "wt") as stream:
            for row in (header, count):
                stream.write(json.dumps(row) + "\n")

    save()
    with pytest.raises(ValueError, match="unexpected_audit_scope"):
        read_audit(path)
    header["account"] = "PERSONAL_PLAN_PAPER_7000"
    save()
    with pytest.raises(ValueError, match="archive_counts_mismatch"):
        read_audit(path)


def test_research_registration_is_write_once_and_forward_only(tmp_path):
    with at(STAMP):
        with pytest.raises(ValueError, match="future_chronological"):
            registration(STAMP - STEP, STAMP + STEP, STAMP + 2 * STEP, STAMP + 3 * STEP)
        plan = registration(STAMP, STAMP + STEP, STAMP + 2 * STEP, STAMP + 3 * STEP)
    path = tmp_path / "registration.json"
    write_record(path, plan)
    with pytest.raises(FileExistsError):
        write_record(path, {"replacement": True})
    assert load_captures(tmp_path, plan) == []
    result = report(plan, [], STAMP)
    assert result["authority"] == "RESEARCH_ONLY"
    assert result["qualification"]["automatic_activation"] is False
    assert result["qualification"]["status"] == INSUFFICIENT
    assert not result["qualification"]["proxy_review_checks"]["holdout"][
        "minimum_observations_each"
    ]


@pytest.mark.asyncio
async def test_public_capture_exercises_the_normal_entry_path_without_orders():
    class Feed:
        async def get_pairs(self):
            return [TradingPair(s, s.split("-")[0], "EUR") for s in (*PEERS, SYMBOL)]

        async def get_tickers(self):
            return [
                {
                    "symbol": SYMBOL,
                    "bid": "105.59",
                    "ask": "105.61",
                    "low_24h": "100",
                    "high_24h": "110",
                    "quote_volume_24h": "1000000",
                }
            ]

        async def get_candles(self, symbol, *_):
            return bars(symbol)

        async def get_order_book(self, symbol, **_):
            assert symbol in (*PEERS, SYMBOL)
            return OrderBook(
                symbol,
                STAMP,
                (OrderBookLevel(D("105.59"), D(100)),),
                (OrderBookLevel(D("105.61"), D(100)),),
                "revolut-x",
            )

    with at(STAMP):
        plan = registration(STAMP, STAMP + STEP, STAMP + 2 * STEP, STAMP + 3 * STEP)
        market = MarketDataService(Feed(), candle_lookback=288, cache_enabled=False)
        row = await capture(market, plan, [])
    assert row["selected"] == [SYMBOL]
    assert row["markets"][SYMBOL]["macro"] is True
    assert row["macro"]["breadth"]["sample"] == 1
    assert row["failures"] == {}


def test_replay_does_not_accept_future_capture_or_outcome_backfill():
    with at(STAMP):
        plan = registration(STAMP, STAMP + 100 * STEP, STAMP + 200 * STEP, STAMP + 300 * STEP)
    setup = {
        "entry": "100",
        "quantity": "1",
        "stop": "98",
        "target": "103",
        "horizon": 2,
        "spread_bps": "0",
        "fee_bps": "10",
        "slippage_bps": "8",
        "conditional_target_net_eur": "2.5",
        "planned_net_loss_eur": "2.5",
    }
    decision = {
        "observed_at": STAMP.isoformat(),
        "reference": STAMP.isoformat(),
        "candles": {},
        "markets": {SYMBOL: {"entry": setup, "macro": True, "a3": True, "range": None}},
        "discovery": {"screened": 1},
        "selected": [SYMBOL],
        "failures": {},
        "macro": {},
    }
    touch = Candle(SYMBOL, STAMP, D(101), D(104), D(100), D(103), D(1), "5m", "revolut-x")
    future = {
        **decision,
        "observed_at": (STAMP + 7 * STEP).isoformat(),
        "reference": (STAMP + 7 * STEP).isoformat(),
        "markets": {},
        "candles": {SYMBOL: [{**asdict(touch), "timestamp": STAMP.isoformat()}]},
    }
    assert report(plan, [decision, future], STAMP + 3 * STEP)["capture_cycles"] == 1
    result = report(plan, [decision, future], STAMP + 10 * STEP)["periods"]["development"][
        "combined_continuation"
    ]["stress"]["0"]
    assert result["censored"] == 1 and result["observations"] == 0


def test_frozen_primary_execution_closure_is_unchanged():
    # Fetched, verified 201f8e98e1d09f695f7c433009c04a16cc49197f.
    assert fingerprint() == "8568cac192b61bec09e6c67716d82eb04a16ebea236d3ed11a78ed8ddd096e4d"


def test_challenger_endpoint_requires_authentication_and_rejects_order_authority(tmp_path):
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.testclient import TestClient

    from autotrader.api.v47 import install
    from autotrader.crypto_research.context import VERSION

    def authorize(authorization: str | None = Header(None)):
        if authorization != "test":
            raise HTTPException(401)

    app = FastAPI()
    service = SimpleNamespace(settings=SimpleNamespace(research_root=tmp_path))
    install(app, service, authorize)
    url = "/api/personal-paper/challenger"
    path = tmp_path / "crypto-7000" / "report.json"
    with TestClient(app) as client:
        assert client.get(url).status_code == 401
        headers = {"Authorization": "test"}
        assert client.get(url, headers=headers).json()["capture_cycles"] == 0
        base = {"schema": VERSION, "authority": "RESEARCH_ONLY", "capture_cycles": 2}
        write_record(path, {**base, "qualification": {"automatic_activation": True}})
        assert client.get(url, headers=headers).json()["capture_cycles"] == 0
        write_record(path, {**base, "qualification": {"automatic_activation": False}}, replace=True)
        assert client.get(url, headers=headers).json()["capture_cycles"] == 2


def test_trade_report_preserves_legacy_ownership_and_accounts_for_midpoint_costs():
    from autotrader.api.trade_reports import explain_position

    def order(side, strategy, bid, ask):
        return SimpleNamespace(
            order_id=side,
            created_at=STAMP,
            side=side,
            filled_quantity=D(1),
            exit_intent_id=None,
            execution_json=json.dumps(
                {
                    "strategy_id": strategy,
                    "book": {"bids": [[bid, "1"]], "asks": [[ask, "1"]]},
                    "strategy_evidence": {
                        "economics": {
                            "measurements": {
                                "expected_net_stop_loss_eur": "5",
                                "estimated_total_round_trip_cost_eur": "2",
                            }
                        }
                    },
                }
            ),
        )

    orders = [order("BUY", A3, "98", "100"), order("SELL", "LEGACY_WRONG_LABEL", "94", "96")]
    before = [o.execution_json for o in orders]
    fills = [
        SimpleNamespace(
            order_id=s, fill_id=s, created_at=STAMP, side=s, quantity=D(1), price=D(p), fee=D(".1")
        )
        for s, p in (("BUY", "100.1"), ("SELL", "93.9"))
    ]
    journal = [
        SimpleNamespace(order_id=s, cash_delta=D(v))
        for s, v in (("BUY", "-100.2"), ("SELL", "93.8"))
    ]
    plan = SimpleNamespace(strategy_id=A3, settings_json="{}")
    pos = SimpleNamespace(
        position_id="test",
        symbol=SYMBOL,
        state="CLOSED",
        realized_pnl=D("-6.4"),
        initial_stop=D(95),
        average_entry_price=D("100.1"),
        opened_at=STAMP,
        closed_at=STAMP + STEP,
    )
    result = explain_position(pos, plan, orders, fills, [], [], journal, [])
    assert result["net_pnl_eur"] == result["journal_net_cash_eur"] == "-6.4"
    assert result["realized_cost_vs_midpoint_eur"] == "2.4"
    assert result["planned_round_trip_cost_eur"] == "2"
    assert result["strategy_id"] == A3
    assert result["fills"][1]["raw_strategy_id"] == "LEGACY_WRONG_LABEL"
    assert [o.execution_json for o in orders] == before
