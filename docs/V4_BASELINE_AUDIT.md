# V4 baseline audit

Starting commit: `8506a7d`; implementation branch: `codex/v4-execution-research`.

Before changing source, the complete suite ran against isolated real PostgreSQL:
`python -m pytest -q -s --junitxml=docs/evidence/v4-baseline.xml`.
Result: **80 passed in 332.77 seconds**, no failures or skips.
Evidence: [JUnit](evidence/v4-baseline.xml). The test database administrator URL
was supplied using `AUTOTRADER_TEST_PG_ADMIN_URL`; it is not a production account.

Confirmed defects: PositionManager compares midpoint with long stops and targets;
target exits are market orders without a net-proceeds floor; independent intents
can reuse liquidity from the same immutable book observation. Stale protection
currently returns an ephemeral action without a durable position risk watch.
Depth walking already exists in dispatch, and the book validator already permits
wide spreads. Protective exits must retain that behavior.

Existing strengths to preserve: account-first locking, immutable attributed fills
and journal, atomic cash/basis/target changes, persisted reservations, crash recovery,
independent reconciliation, fixed EUR 500 account and hard risk limits.

Historical execution currently assumes a spread and volume-derived liquidity from
OHLCV. These are assumptions, not reconstructed L2. Existing short fixture backtests
do not establish a profitable strategy. Existing support-image security findings
remain unresolved until assessed and rescanned with V4 evidence.
