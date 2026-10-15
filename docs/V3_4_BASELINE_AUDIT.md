# V3.4 baseline audit

Starting commit: `27812aa` (its message says version 3.4; source is the V3.3 implementation).

Confirmed by source inspection:

* `sync_exit_plan_from_fills` apportions all SELL quantities sequentially and erases target prices.
* Migration 0005 backfills position identity from symbol alone.
* No immutable financial journal; opening fees omitted from cost basis.
* Gateway checks risk before the repository transaction; repository accepts buys without risk policy.
* Runtime calls metadata.create_all; readyz unconditionally reports ready.
* Exit orders have no position/target/intent identity; idempotency uses symbol and minute.
* Daily/weekly checks use realized losses only; no persisted equity baseline.
* Worker monitors all open positions but lacks durable trailing/time/cooldown state and control state.
* PostgreSQL test pads a step counter with repeated assertions and calls object reconstruction a restart.
* AI budget is a read-then-call sum; cost is an assumed per-token constant.
* Dashboard health reports literal risk=ok, and has only overview/scanner/order endpoints.

Initial command: `python -m pytest -q` -> FAILED: No module named pytest.
Docker CLI exists; initial docker info -> BLOCKED: Linux daemon named pipe absent.
No PostgreSQL executable found on PATH. Installing project dependencies in `.venv`.

Existing user SQLite database is preserved. Testing uses isolated databases only.
