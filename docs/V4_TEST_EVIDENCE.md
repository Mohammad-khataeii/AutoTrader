# V4 executed evidence

## Unchanged baseline

Before source changes: 80 passed, 0 failed, 0 skipped, 332.77 seconds.
Artifact: evidence/v4-baseline.xml. Actual worker PID termination/restart and
authenticated API proofs are included in that suite.

## Execution changes

New coverage: depth VWAP/costs, partial limit floors, reused snapshot exhaustion,
entry spread/cost rejection, midpoint/bid stop discrepancy, wide-spread protection,
gap stop execution, fee/slippage target delay, durable stale watch and recovery,
and direct repository caller target-floor enforcement.

Initial targeted run: 5 passed and 4 failed due to new test code treating the
repository's documented dictionary fill results as objects. Those assertions were
corrected without changing expected financial results. The failed run is not a
passing milestone. Full revised suite execution is pending.

Existing position-manager and backtest subset: 4 passed in 103.93 seconds before
the subsequent conservative historical-close/zero-volume replay change. That
historical change requires a fresh backtest check.

Ruff and strict mypy pass after execution changes (40 source files).

Targeted execution suite after assertion correction: **9 passed in 16.88 seconds**,
real PostgreSQL, evidence/v4-execution.xml. The first full revised run had 82 passes
and seven failures: cost-infeasible legacy fixtures, a midpoint-only target fixture,
and zero-spread accounting fixtures rejected by an unnecessarily stricter pure
validator. Zero-spread repository compatibility was restored; crossed books remain
rejected. Lifecycle fixture inputs now provide executable, cost-feasible quotes
without weakening ledger/restart assertions. A fresh full rerun is in progress.

## Financial regression after execution fixes

**98 passed in455.16 seconds**, zero failures/skips. Artifact:
`evidence/v4-financial-regression.xml`. Includes original80 accounting/risk/recovery/
migration/concurrency/API checks, nine execution cases and nine data cases.
Actual process evidence: A2856 ->30708, B6368 ->29800, C9244 ->12304;
C authenticated API25160 observed four fills and exact target attribution.
This result precedes the subsequent V4 strategy and research runtime integration.
