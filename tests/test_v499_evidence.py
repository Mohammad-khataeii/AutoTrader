"""V4.9.9 regression sources. Authored without execution at the user's request."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import json

import pytest

from autotrader.domain import OrderBook, OrderBookLevel
from autotrader.perpetuals.market import Bar, MINUTE
from autotrader.perpetuals.multi.evidence import candle_review, category, realized_distribution
from autotrader.perpetuals.multi.research import compare_frozen, evaluate, reference_records
from autotrader.perpetuals.multi.research_v2 import generate_v2, POLICY_HASH
from autotrader.perpetuals.multi.scanner import adaptive_screen
from autotrader.personal_paper.freshness import entry_freshness
from autotrader.shadow.performance import metrics

NOW = 1_800_000_000_000


def hypothesis(side=1, decision_at=NOW):
    return {'id': f'signal-{side}', 'symbol': 'SOLUSDT', 'policy': 'MULTI_CONTINUATION_V2',
            'side': side, 'cutoff': NOW, 'decision_at': decision_at, 'reference': '100',
            'target': str(100+side), 'stop': str(100-side), 'hold_minutes': 3,
            'regime': 'RANGE', 'feature_hash': 'frozen-feature-hash', 'reasons': [],
            'evidence': {'policy_hash': POLICY_HASH}, 'decision': {'group': 'UNECONOMIC_OR_UNSAFE'}}


@pytest.mark.parametrize('total,known,net,wins,profit,loss,pf,status', [
    (0, 0, None, 0, None, None, None, 'NO_TRADES'),
    (3, 3, D('-6'), 0, None, D('-6'), '0', 'DEFINED'),
    (2, 2, D('4'), 2, D('4'), None, None, 'NO_LOSSES'),
    (2, 2, D('0'), 1, D('2'), D('-2'), '1', 'DEFINED'),
    (3, 2, D('-2'), 0, None, D('-2'), None, 'MISSING_PNL'),
])
def test_null_aggregate_performance(total, known, net, wins, profit, loss, pf, status):
    result = metrics(total, known, net, wins, profit, loss, None)
    assert result['profit_factor'] == pf
    assert result['profit_factor_status'] == status
    assert result['max_drawdown'] is None
    if known != total or not known: assert result['expectancy'] is None


@pytest.mark.parametrize('side', [1, -1])
def test_ambiguous_bar_is_stop_first_and_costs_are_only_in_proxy(side):
    bars = {NOW+i*MINUTE: Bar(NOW+i*MINUTE, D(100), D(102), D(98), D(100)) for i in range(3)}
    review = candle_review(hypothesis(side), bars, now=NOW+3*MINUTE)
    assert review['conservative_first_barrier'] == 'STOP'
    assert review['ambiguous_first_barrier']
    assert review['gross_barrier_or_time_fraction'] == D('-.01')
    assert review['cost_stressed_no_fill_proxy_fraction'] < D('-.012')
    assert review['funding_fraction'] is None
    assert review['missed_profitable_trade'] is None
    assert review['hypothetical_no_fill']


def test_decision_minute_excluded_and_observed_gap_not_filled_at_stop():
    s = hypothesis(decision_at=NOW+1000)
    bars = {NOW+i*MINUTE: Bar(NOW+i*MINUTE, D(100), D(100), D(100), D(100)) for i in range(4)}
    bars[NOW] = Bar(NOW, D(100), D(110), D(90), D(100))
    review = candle_review(s, bars, now=NOW+4*MINUTE)
    assert review['conservative_first_barrier'] == 'TIME'
    bars[NOW+MINUTE] = Bar(NOW+MINUTE, D(97), D(98), D(96), D(97))
    review = candle_review(s, bars, now=NOW+4*MINUTE)
    assert review['gross_barrier_or_time_fraction'] == D('-.03')


def test_review_rejects_future_or_incomplete_data():
    with pytest.raises(ValueError): candle_review(hypothesis(), {}, now=NOW)
    with pytest.raises(KeyError): candle_review(hypothesis(), {}, now=NOW+3*MINUTE)


def test_categories_preserve_technical_and_data_failures():
    assert category({'reasons': ['no_setup']}, 'entries_paused') == 'TECHNICALLY_INVALID'
    assert category({'reasons': []}, 'stale_depth') == 'DATA_QUALITY'
    assert category({'reasons': []}, 'cohort_10:aggregate_exposure_margin_or_risk_cap') == 'RISK_OR_CONTROL'
    assert category({'reasons': []}, 'net_target_or_reward_risk_insufficient') == 'UNECONOMIC_OR_UNSAFE'


def test_realized_distribution_uses_net_once_and_never_pools_cohorts():
    events = []
    for cohort in (1, 3, 10):
        for i, net in enumerate(('-2', '1')):
            events.append({'kind': 'EXIT_SETTLED', 'event_key': f'{cohort}:{i}', 'at': NOW+i*MINUTE,
                           'net': net, 'entry_fee': '100', 'exit_fee': '100',
                           'position': {'symbol': 'SOLUSDT', 'side': 1, 'leverage': cohort,
                                        'signal': {'policy': 'V1', 'regime': 'RANGE'}}})
    rows = realized_distribution(events+events)
    assert len(rows) == 3
    for row in rows:
        assert row['closed'] == 2
        assert row['net_per_trade'] == D('-.5')
        assert row['profit_factor'] == D('.5')
        assert row['confidence'] == 'UNKNOWN'
        assert row['expected_future_net_profit'] is None


def envelope(rows, symbol='SOLUSDT'):
    return json.dumps({'kind': 'last_trade_ohlcv_1m', 'symbol': symbol,
                       'params': {'category': 'linear', 'symbol': symbol, 'interval': '1'},
                       'fetched_at_utc': datetime.fromtimestamp((NOW+10*MINUTE)/1000, UTC).isoformat(),
                       'response': {'ok': True, 'result': {'symbol': symbol, 'category': 'linear', 'list': rows}}})


def test_reference_adapter_freezes_outcomes_and_rejects_conflicting_pages():
    rows = [[str(NOW+i*MINUTE), '100', '100.1', '99.9', '100', '50', '5000'] for i in range(3)]
    dataset = reference_records([envelope(rows)])
    result = evaluate(hypothesis(), dataset, now=NOW+3*MINUTE)
    assert result['outcome']['conservative_first_barrier'] == 'TIME'
    assert result['outcome']['mark_price_coverage'] == 'UNKNOWN'
    assert result['metadata_known_at_decision'] is False
    before = json.dumps(result, default=str, sort_keys=True)
    report = compare_frozen([result], [result, result])
    assert report['candidate'][0]['unique_signals'] == 1
    assert report['automatic_promotion'] is False
    assert json.dumps(result, default=str, sort_keys=True) == before
    conflicting = [list(r) for r in rows]; conflicting[0][4] = '100.05'
    with pytest.raises(ValueError, match='conflicting'):
        reference_records([envelope(rows), envelope(conflicting)])


def test_funding_changes_proxy_only_when_coverage_is_explicit():
    bars = {NOW+i*MINUTE: Bar(NOW+i*MINUTE, D(100), D('100.1'), D('99.9'), D(100)) for i in range(3)}
    s = hypothesis()
    unknown = candle_review(s, bars, now=NOW+3*MINUTE)
    funded = candle_review(s, bars, now=NOW+3*MINUTE,
                           funding=[{'at': NOW+MINUTE, 'rate': '.001', 'mark': '100'}])
    assert funded['cost_stressed_no_fill_proxy_fraction'] == unknown['cost_stressed_no_fill_proxy_fraction']-D('.001')
    assert unknown['cost_provenance']['funding_complete'] is False


def test_scanner_has_fair_slots_and_never_rewards_rolling_turnover_changes():
    mapped = [{'symbol': s, 'base': s, 'dashboard_symbols': []} for s in ('A', 'B', 'C', 'D')]
    tickers = [{'symbol': r['symbol'], 'bid1Price': '99.99', 'ask1Price': '100.01',
                'turnover24h': '2000000', 'highPrice24h': '102', 'lowPrice24h': '98'} for r in mapped]
    prior = {'revisits': {'A': NOW-100, 'B': NOW-100, 'C': 0, 'D': NOW-50},
             'samples': {'A': [{'at': NOW-MINUTE, 'mid': '100', 'volume24h': '1'}],
                         'B': [{'at': NOW-MINUTE, 'mid': '100', 'volume24h': '2000000'}]}}
    selected, rows, _ = adaptive_screen(mapped, tickers, NOW, prior, batch=2)
    assert len(selected) == 2
    assert any(r['symbol'] == 'C' and r['selection'] == 'FAIR_REVISIT' for r in selected)
    by_symbol = {r['symbol']: r for r in rows}
    assert by_symbol['A']['score'] == by_symbol['B']['score']
    assert by_symbol['A']['feature_status'] == 'UNKNOWN_OR_EXPIRED_CANDLES'


def test_v2_has_separate_long_short_identities_and_ignores_future_bars():
    bars = {NOW-i*MINUTE: Bar(NOW-i*MINUTE, D(100), D('100.2'), D('99.8'), D(100), D(50)) for i in range(1, 91)}
    signals = generate_v2('SOLUSDT', bars, NOW, NOW)
    assert len(signals) == 8
    assert len({s.id for s in signals}) == 8
    assert {s.side for s in signals} == {-1, 1}
    assert all(s.evidence['research_only'] and s.evidence['policy_hash'] == POLICY_HASH for s in signals)
    bars[NOW] = Bar(NOW, D(100), D(200), D(1), D(180), D(5000))
    assert generate_v2('SOLUSDT', bars, NOW, NOW) == signals


@pytest.mark.parametrize('age,qualified', [(0, True), (20, True), (21, False), (45, False), (-3, False)])
def test_personal_entry_freshness_is_separate_from_exit_availability(age, qualified):
    now = datetime(2026, 11, 4, tzinfo=UTC)
    book = OrderBook('SOL-EUR', now-timedelta(seconds=age),
                     (OrderBookLevel(D(99), D(10)),), (OrderBookLevel(D(100), D(10)),), 'fixture')
    result = entry_freshness(book, now)
    assert result['entry_qualified'] is qualified
    assert result['protective_exit_qualified'] is None
    assert result['policy']['protective_exit_max_age_seconds'] == 90


async def test_durable_research_never_reserves_cash_and_reviews_are_idempotent(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy import select
    from autotrader.perpetuals.multi.ledger import MultiLedger, Refused
    from autotrader.perpetuals.multi.models import Base, MultiState, MultiSignal, MultiEvent
    monkeypatch.setattr('autotrader.perpetuals.multi.ledger.clock_ms', lambda: NOW)
    engine = create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'evidence.sqlite'))
    try:
        async with engine.begin() as connection: await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session, session.begin(): session.add(MultiState(id=1, generation=0, payload=None))
        ledger = MultiLedger(factory)
        assert await ledger.acquire('worker')
        s = hypothesis(); s['evidence']['research_only'] = True
        before = (await ledger.load())[1]['accounts']
        with pytest.raises(Refused, match='no_entry_authority'): await ledger.reserve('worker', s, [], None)
        assert await ledger.record_signal('worker', s, 'research_only_no_entry_authority')
        assert not await ledger.record_signal('worker', s, 'research_only_no_entry_authority')
        assert await ledger.review('worker', s, {'hypothetical_no_fill': True})
        assert not await ledger.review('worker', s, {'hypothetical_no_fill': True})
        assert (await ledger.load())[1]['accounts'] == before
        async with factory() as session:
            stored = json.loads((await session.get(MultiSignal, s['id'])).payload)
            assert stored['decision']['group'] == 'RESEARCH_ONLY'
            events = (await session.scalars(select(MultiEvent).where(MultiEvent.kind=='RESEARCH_OBSERVED'))).all()
            assert len(events) == 1
    finally:
        await engine.dispose()
