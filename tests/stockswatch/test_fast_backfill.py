"""Isolated regression checks for the accelerated historical backfill."""
from datetime import UTC, date, datetime

from stockswatch import backfill, fast_backfill, storage


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "stockswatch.sqlite3"))
    storage.init()
    backfill.initialize()
    start = backfill.midnight(date(2026, 10, 1)).isoformat()
    end = backfill.midnight(date(2026, 11, 1)).isoformat()
    with storage.connect() as c:
        c.executemany(
            """INSERT INTO sw_history_jobs
               (symbol,timeframe,feed,adjustment,first_at,end_at,state)
               VALUES(?,'1Day','iex','raw',?,?,'PENDING')""",
            [(s, start, end) for s in ("AAPL", "ABT", "BAC")],
        )
    return datetime(2026, 11, 7, 10, tzinfo=UTC)


class FakeAlpaca:
    def __init__(self, token=None):
        self.token = token
        self.calls = 0
        self.actions = 0

    def bar_page(self, symbols, feed, start, end, timeframe, adjustment, token=None):
        self.calls += 1
        assert len(symbols) == 3 and feed == "iex" and timeframe == "1Day"
        stamp = backfill.midnight(date(2026, 10, 15)).isoformat()
        data = {symbol: [{"t": stamp, "o": 10, "h": 12, "l": 9,
                           "c": 11, "v": 1000}] for symbol in symbols}
        return data, self.token

    def corporate_actions(self, symbol, start, end):
        self.actions += 1
        return []


def test_batch_finishes_matching_daily_partitions_atomically(monkeypatch, tmp_path):
    now = _setup(monkeypatch, tmp_path)
    provider = FakeAlpaca()
    assert fast_backfill.step(provider, now) is True
    assert provider.calls == 1 and provider.actions == 3
    with storage.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM sw_history_jobs WHERE state='COMPLETE'").fetchone()[0] == 3
        assert c.execute("SELECT COUNT(*) FROM sw_historical_bars").fetchone()[0] == 3
        assert c.execute("SELECT COUNT(*) FROM sw_history_actions").fetchone()[0] == 0


def test_truncated_group_falls_back_without_committing(monkeypatch, tmp_path):
    now = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(backfill, "step", lambda provider, timestamp: True)
    provider = FakeAlpaca("next-page")
    assert fast_backfill.step(provider, now) is True
    assert provider.calls == 1 and provider.actions == 0
    with storage.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM sw_history_jobs WHERE state='PENDING'").fetchone()[0] == 3
        assert c.execute("SELECT COUNT(*) FROM sw_historical_bars").fetchone()[0] == 0


def test_worker_interval_is_bounded(monkeypatch):
    monkeypatch.setenv("STOCKSWATCH_HISTORY_INTERVAL_SECONDS", "1")
    assert fast_backfill.interval_seconds() == 8
    monkeypatch.setenv("STOCKSWATCH_HISTORY_INTERVAL_SECONDS", "2000")
    assert fast_backfill.interval_seconds() == 120
