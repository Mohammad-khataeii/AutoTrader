# V4.1 executed verification

The final application package fingerprint is `e0140ff18c36d86ac4c676e07aa650c2d93bac3fcfa6b708e0025f6573d66c5e` (62 Python package files). The full genuine 5m/15m study uses this same fingerprint. Deployment scripts, image builds, tests, frontend and documentation are outside that package fingerprint; they have separate Git/evidence records. No result was relabeled to match a changed source.

| Executed check | Actual result | Evidence |
|---|---|---|
| Unchanged baseline, PostgreSQL 15 | 118 passed, no failures/skips, 147.35s | v4_1-baseline.xml |
| Final native regression, disposable PostgreSQL 16 databases | **148 passed**, no failures/errors/skips, 415.35s | v4_1-release-final.xml |
| Final installed Linux runtime, selected backported PostgreSQL16 | **148 passed**, no failures/errors/skips, 414.98s | v4_1-linux-final.xml |
| Installed Linux runtime full regression before fixture repair | 146 passed, 1 failed, 430.24s | v4_1-linux.xml |
| Installed Linux corrected risk-accounting cases plus V4→V4.1 migration | **20 passed**, no failures/skips, 121.67s | v4_1-linux-repairs.xml |
| Actual independent worker/API lifecycle | Passed: cost rejection, entry, partial targets, kill/restart, protective exit, five unique fills, empty reconciliation | v4_1-lifecycle.xml; final full JUnit |
| Initial atomic AI quota tests on PostgreSQL 16 | 17 passed | v4_1-quotas.xml |
| Quota, migration, promotion, lease, authentication and pilot targeted suite | 19 passed | v4_1-safety-targeted.xml |
| Data integrity/incremental ingestion | 12 passed | v4_1-data.xml |
| Causal simulation/frozen research regressions | 23 passed initially; all current cases included in final148 | v4_1-research-unit.xml; final JUnit |
| Chromium real frontend/backend workflow | 1 passed, 49.0s, 16 pages, no browser page errors | v4_1-playwright.json; dashboard/strategy screenshots |
| Scoped deployment upgrade/rollback | Passed, binary archive, isolated restore/reconciliation, migration, retained image rollback | v4_1-upgrade.json; v4_1-rollback.json |
| Full running-project restart | Passed, persisted controls, one original funding entry, no journal loss, empty reconciliation | v4_1-deployment-restart.json |
| Redis and PostgreSQL outages/recovery | Passed; Redis optional; PostgreSQL readiness503; RESEARCH_ONLY recovery | v4_1-dependency-recovery.json |
| Python lint/type checks | Ruff passes; mypy passes all62 package files | final command records |
| Frontend typecheck/Vitest/production build | Pass; Vitest1case; existing >500kB bundle warning remains | final command records |
| Source/secrets/exchange/network checks | Pass, no configured secrets/key findings, GET-only exchange, loopback UI/API | v4_1-source-security.json |
| Locked dependency audits | pip no known dependency vulnerabilities; npm zero findings | v4_1-pip-audit.json; v4_1-npm-audit.json |
| Images | Scope is high/critical; exact findings and remediation in security report | raw v4_1-*.sarif |

## Financial and promotion evidence

The suites execute real PostgreSQL transactions and actual independent Python worker/API processes. They cover competing reservations, cash/quantity constraints, side-aware liquidity/IOC behavior, duplicate fills, partial targets, stopped/paused/emergency controls, stop monotonicity, realized fees/cost basis, marked exposure, missing/stale mark rejection, daily/weekly unrealized loss, shared public API rate limits, deadlock retry, lost response after commit, killed processes at accounting boundaries, journal replay and recovery. The full lifecycle uses an isolated qualifying acceptance fixture; no production research bypass is introduced.

`test_explicit_approval_timeframe_restart_and_durable_suspension`, `test_failed_research_never_approves` and `test_single_coordinator_and_old_owner_financial_fence` cover matching immutable candidate approval, timeframe/source/parameter invalidation, restart and stale-owner fencing under the financial lock. Successful synthetic approvals do not approve the losing genuine historical candidates.

`test_v4_to_v41_preserves_existing_ai_holds_and_financial_history` runs the actual migration from V4 head and verifies prior holds/journal. This is separate from merely creating an empty schema. The original user SQLite file stays byte-identical.

## AI evidence

`test_daily_thirty_then_reject_thirty_first`, `test_rolling_hour_concurrency_restart_and_exact_expiry`, calendar/day/month boundary cases, duplicate unknown billing, audited reconciliation, cost-bound fail-closed handling, cross-month submission rejection and protected portfolio-review capacity all pass. Transactions use the real shared PostgreSQL account lock. Fake provider responses are used only at the network boundary; no real paid request was made. Monthly enforcement is an internal reservation guard, not a guarantee of an external invoice after erroneous pricing or provider overages.

## Browser and deployment evidence

The browser logs in, checks available cash against authenticated API data, visits16pages, loads genuine 5m evidence, queues and completes a1h research-worker job, runs historical LIMIT replay, exercises persistent paper controls, verifies mock0/30 and0/6 counters, starts a real-market local RESEARCH_ONLY pilot, waits for a persisted observation and exports JSON/CSV. Screenshots were visually inspected. The full matching 5m/15m research pointer was restored after the selected research job; no approval was granted.

The first browser attempt exposed a real root-owned research-pointer permission error. `deploy/vps.py sync-research` now gives both newly published pointers to UID10001. The subsequent browser workflow passes. Worker retry recovered after the fix without resetting the ledger.

## Retained failures and limits

Earlier artifacts intentionally remain: missing-PostgreSQL invocation failed rather than substituting SQLite; a development test used the wrong production/test pricing context; API lifespan/throttling fixtures required real PostgreSQL initialization; the old UNKNOWN billing assertion was updated to the explicit OUTCOME_UNKNOWN state. An earlier full suite had 141 passed/1 failure; it is not the final release result. The Linux full and prior native full each failed the same exposure fixture because a long process-lease wait made an unrelated ETH mark stale. The repaired fixture refreshes both real test books before the exposure assertion, preserving stale-mark rejection and all financial limits. All 148 final native cases and 20 Linux repair/migration cases pass. A fresh installed-Linux run against the selected backported PostgreSQL image passes all 148 cases (414.98s).

There is one deprecation warning from Starlette/AnyIO in the native suite and a frontend bundle-size warning. No source runtime exception was suppressed to pass tests. Security findings, remote deployment and30-day elapsed performance remain separate from engineering test success. Test/live-public smoke observations are not investment evidence.

Final PostgreSQL backport evidence includes upstream/bounds/negative-control tests, XML and extension behavior, separate restored-data restart, selected-volume upgrade, SQL/XML and exact running core image scans (`v4_1-core-scan.json`). All four running core images have zero high/critical findings. Grafana remains quarantined and unresolved. The deployment verifier also rejects an unavailable worker or SYSTEM_ERROR/RECOVERY_REQUIRED rather than accepting database readiness alone.
