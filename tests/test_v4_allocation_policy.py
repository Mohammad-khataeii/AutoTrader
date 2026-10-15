from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

from autotrader.allocation import allocation_advice
from autotrader.execution.protection import trailing_update
from autotrader.persistence.repository import PersistentTradingRepository
from test_v34_acceptance import PAIR, book, buy, gateway


def test_profiles_correlation_and_monotonic_volatility_stop() -> None:
    metadata = {"return_history_20": [str(D(i % 5) / 100) for i in range(20)]}
    assert not allocation_advice(metadata, [metadata]).accepted
    assert allocation_advice(metadata, [], profile="conservative").quote_cap == 50
    assert allocation_advice(metadata, [], profile="opportunistic").quote_cap == 100
    assert not allocation_advice(metadata, [{}], profile="conservative").accepted
    first = trailing_update(previous_stop=D(98), highest_bid=D(110), basis=D("100.1"), quantity=D(1),
        distance=D(3), atr=D(2), fee_bps=D(10), slippage_bps=D(8))
    wider = trailing_update(previous_stop=first.stop, highest_bid=D(111), basis=D("100.1"), quantity=D(1),
        distance=first.distance, atr=D(8), fee_bps=D(10), slippage_bps=D(8))
    assert wider.distance > first.distance and wider.stop >= first.stop
    assert first.breakeven_bid > D("100.1")


async def test_unvalidated_entry_gate_persists_and_protection_remains_available(pg_repo: PersistentTradingRepository, tmp_path: Path) -> None:
    await pg_repo.initialize_portfolio(D(500))
    assert (await buy(pg_repo)).accepted
    await pg_repo.configure_research_policy(tmp_path, test_environment=False, approved={"A_TREND_PULLBACK"})
    rejected = await buy(pg_repo, "unapproved-entry", symbol="ETH-EUR")
    assert not rejected.accepted and rejected.reason == "strategy_not_approved_and_validated"
    reopened = PersistentTradingRepository(pg_repo.session_factory)
    rejected_again = await buy(reopened, "unapproved-restarted", symbol="SOL-EUR")
    assert not rejected_again.accepted
    position = (await reopened.list_positions())[0]
    exit_result = await gateway(reopened).execute_exit(PAIR, position.quantity, book("9.7"), "protect-existing", "protective_stop", position_id=position.position_id)
    assert exit_result.accepted
    assert await reopened.verify_invariants(D(500)) == []
