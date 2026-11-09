"""Additive 20-pair USD AlpacaCrypto universe and safe history warmup.

No network calls, broker POSTs, or writes to a real trading ledger.
"""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from stockswatch import alpaca_crypto as ac, storage


CORE = (
    "BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "LINK/USD",
    "LTC/USD", "BCH/USD", "DOGE/USD", "UNI/USD", "AAVE/USD",
)
ADDED = (
    "XRP/USD", "ADA/USD", "DOT/USD", "SHIB/USD", "ARB/USD",
    "RENDER/USD", "ONDO/USD", "FIL/USD", "GRT/USD", "PEPE/USD",
)


def _temporary_ledger(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "new-crypto-universe.sqlite3"))
    monkeypatch.setattr(ac.time, "sleep", lambda seconds: None)
    ac.initialize()


def test_existing_symbols_unchanged_and_ten_additive():
    assert ac.BASE_PAIRS == CORE
    assert ac.EXPANSION_PAIRS == ADDED
    assert ac.PAIRS == CORE + ADDED
    assert len(ac.PAIRS) == len(set(ac.PAIRS)) == 20
    assert all(symbol.endswith("/USD") for symbol in ac.PAIRS)


def test_initialize_and_queue_preserve_existing_jobs(monkeypatch, tmp_path):
    _temporary_ledger(monkeypatch, tmp_path)
    now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    ac.queue(now)
    with storage.connect() as conn:
        original = dict(conn.execute(
            "SELECT symbol,COUNT(*) FROM ac_jobs GROUP BY symbol"
        ))
        count_before = conn.execute("SELECT COUNT(*) FROM ac_jobs").fetchone()[0]
        conn.execute("""UPDATE ac_jobs SET state='COMPLETE'
            WHERE symbol=?""", (CORE[0],))
    # Existing completed data and jobs must not be reset by another startup.
    ac.initialize()
    ac.queue(now)
    with storage.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ac_assets").fetchone()[0] == 20
        assert conn.execute("SELECT COUNT(*) FROM ac_jobs").fetchone()[0] == count_before
        assert conn.execute("SELECT COUNT(*) FROM ac_jobs WHERE symbol=? AND state='COMPLETE'",
                            (CORE[0],)).fetchone()[0] == original[CORE[0]]
        assert conn.execute("SELECT COUNT(*) FROM ac_jobs WHERE symbol=?",
                            (ADDED[-1],)).fetchone()[0] > 0


def test_new_pair_warmup_writes_only_history_and_never_completes_archive(monkeypatch, tmp_path):
    _temporary_ledger(monkeypatch, tmp_path)
    now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    ac.queue(now)

    class FakeHistory:
        def bars(self, job):
            sym, tf = job["symbol"], job["timeframe"]
            # Records are already validated by ac.CryptoData.bars in production.
            return [(
                sym, tf, job["start_at"], 1.0, 2.0, 0.5, 1.5, 12.0,
                "synthetic-test-only", now.isoformat()
            )], None

    results = ac.warmup_expansion(FakeHistory(), now, symbols=ADDED[:1])
    assert len(results) == 2
    assert {x["timeframe"] for x in results} == {"1Day", "1Hour"}
    assert all(x["new_rows"] == 1 for x in results)
    with storage.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ac_bars WHERE symbol=?",
                            (ADDED[0],)).fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM ac_jobs WHERE symbol=? AND state='COMPLETE'",
                            (ADDED[0],)).fetchone()[0] == 0
        assert conn.execute("SELECT paused FROM ac_state WHERE id=1").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM ac_intents").fetchone()[0] == 0
    rerun = ac.warmup_expansion(FakeHistory(), now, symbols=ADDED[:1])
    assert all(x["new_rows"] == 0 for x in rerun)


def test_warmup_rejects_non_expansion_pair(monkeypatch, tmp_path):
    import pytest
    _temporary_ledger(monkeypatch, tmp_path)
    class NoNetwork:
        def bars(self, job):
            raise AssertionError("Should not call data provider")
    with pytest.raises(ac.CryptoDataError, match="crypto_warmup_requires_expansion_pair"):
        ac.warmup_expansion(NoNetwork(), symbols=[CORE[0]])
