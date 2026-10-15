# V4 executed evidence

## Preserved baseline and financial regression

Unchanged V3.4 baseline: **80passed, zero failed/skipped,332.77s**, v4-baseline.xml. After execution/data changes: **98passed, zero failed/skipped,455.16s**, v4-financial-regression.xml. The original ledger, immutable position attribution, reservations, cash/basis posting, concurrency, recovery, migration and equity-based risk checks remain included.

## Final source verification

Current source fingerprint: b31992258941962d61ee8bfaa7b38ea882a7f5449099ff78fb0045fc15e4966d (58Python source files).

Native Windows: **118passed, zero failed/skipped,516.60s**, evidence/v4-release-windows.xml. Actual interpreter process evidence: A30640->27980; B14056->31612 with equity480 and persistent RISK_HALTED; C30012->20488 with API25036, four fills, exact targets and empty reconciliation. Combined V4 proof: worker18596->6340/API31108, BTC cost rejected, ETH five unique fills, partial TP2 survives restart, final protective exit, empty replay differences.

Final installed-runtime Linux: **118passed, zero failed/skipped,445.74s**, evidence/v4-release-linux.xml. Actual process proofs: A85->88; B102->105 with equity480 and persistent halt; C188->197/API187; combined V4 worker415->424/API414 with five fills, partial TP2 recovery and empty reconciliation. The earlier116case run remains as historical evidence. Tests use real PostgreSQL and disposable databases, not SQLite concurrency substitutes.

Targeted current-source evidence: execution12passed/24.69s (v4-execution-current.xml), causal research8passed/2.05s (v4-causal-research.xml), authentication/API/cache/budget11passed/23.33s (v4-auth-final.xml), combined actual autonomous lifecycle1passed/15.14s (v4-lifecycle.xml). Counts overlap the full suite and must not be added to it.

Execution checks cover bid stop/midpoint discrepancy, net target floors with fees/slippage, finite shared depth across intents/restarts, partial fills, cost rejection, wide spread protection, gap stops, stop-first collisions, durable stale-data watch/recovery, failed-breakout exit without target advancement and direct repository target-floor enforcement.

Causal checks cover prefix invariance, exact EMA equivalence, suspicious full-range quality known only after close, identical known-quality gating for V3/V4, and insufficient/tiny samples failing validation. Authentication cooldown now runs before credential comparison; even a valid secret from a locked client receives429. Mocked AI tests preserve schema, cache and persistent spending behavior without paid requests.

Ruff passes src/tests/scripts/alembic; strict mypy passes all58source files. TypeScript production build and Vitest1case pass. Vite's approximately535kB bundle warning remains a performance limitation.

## Genuine research

Full run research-20261015T205023 matches the final source fingerprint. It used actual48datasets/76606bar records, six strategies on daily/4h, frozen training choices, validation/test, four walk-forward windows, cost sensitivity, benchmarks and matched mock-AI comparison. Verdict: **NO STRATEGY PASSED VALIDATION**. Exports contain623simulated fills and4260equity/drawdown rows across twelve distinct strategy/timeframe simulations. These are not production account fills.

Earlier studies are retained as diagnostic history. A suspicious-bar lookahead correction keeps the execution-open event and marks full-range quality after close. Both candidate and legacy research now apply that same gate. No pre-correction study is the current evidence. Historical holdouts were reused during engineering, so prospective never-seen validation is not claimed.

## Dashboard and research worker

Final Playwright: **1test passed in46.6s** (test body45.6s), evidence/playwright.json. It visits all15pages, verifies real account cash, loads equity/drawdown/trades, submits a genuine selected research job, waits for the dedicated worker to complete it, runs the existing historical LIMIT replay, checks all persistent controls and logout, and observes zero page errors. Screenshots: strategy-lab-v4.png/dashboard-v4.png.

The earlier browser run exposed Windows backslashes in a report pointer. Loader normalization and POSIX writer output fixed it; portable-path regression coverage was added. Curves are pinned to matching run/timeframe/strategy artifacts.

## Deployment, restore and security

Current isolated Compose project autotrader-v34-acceptance was rebuilt/deployed/restarted. Readiness, PostgreSQL/Redis, authentication, metrics, scanner, journal IDs and persisted controls pass. The restart verifier now restarts only already-running services, preserving disabled monitoring. Evidence: v4-deployment-verification.json;51journal events preserved, reconciliation empty.

Binary backup restored into a new isolated database with matching financial counts/cash/schema and empty reconciliation. Existing volumes were not deleted. Evidence: v4-backup-restore.json.

Application backend/frontend scans are clear at all severities. Pip and npm audits are clear. Redis and the rebuilt Prometheus high/critical scans are clear. Prometheus3.15.0 rebuilt with Go1.27.2/x/net0.60.0 passes actual Compose config, embedded UI asset, query API and authenticated backend scrape up=1. PostgreSQL/Grafana findings remain assessed and unresolved as detailed in V4_SECURITY_REMEDIATION.md. Monitoring is stopped. Functional success does not clear that security gate.

Original tracked SQLite blob remains b2b81065cd9f90c2d2f728cb3e5c8a7d6e424c31. No real exchange order or paid AI request was submitted.

## Corrections retained for audit

Early execution tests misread dictionary results as objects; assertions were corrected. Old lifecycle fixtures lacked executable/cost-feasible quotes; fixture inputs were corrected without weakening financial invariants. Zero-spread direct accounting compatibility was retained while crossed books remain rejected. An initial Linux cache-corruption test selected an arbitrary filesystem entry; it now selects the exact request hash. Those failed runs are not passing milestones. The final suites above supersede them.
