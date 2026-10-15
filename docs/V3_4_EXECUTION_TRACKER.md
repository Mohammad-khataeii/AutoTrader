# V3.4 permanent execution tracker

Baseline commit: `27812aa`. First P0 implementation milestone: `5b900db`; final verified functional checkpoint: `fd62e86`. This tracker supersedes interim claims.

**Evidence correction:** earlier Windows restart results killed only the venv launcher and are INVALID as worker-restart proof. Only the corrected actual-interpreter PID harness and later Docker/process reports count. Current corrected full regression:80passed/no skips in `docs/evidence/complete-regression.xml`. The Linux password-authenticated regression is recorded separately in `docs/evidence/linux-regression.xml`.

Statuses apply to the stated assertions. Broad IN_PROGRESS requirements are never promoted merely because a narrower component passed. All paths below are repository-relative; files outside src are named explicitly.

## REQ-0 — NON-NEGOTIABLE PROJECT CONFIGURATION

Severity: P1

- Previous defect: V1 version labels, development deployment credentials and unaudited capital projections.
- Relevant implementation files: config.py; accounting.py; docker-compose.yml
- Required change: NON-NEGOTIABLE PROJECT CONFIGURATION
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: Settings -> startup; PostgreSQL funding -> gateway hard policy
- Test file: tests/test_v34_acceptance.py
- Test name: test_proof_c_full_autonomous_lifecycle_and_authenticated_api
- Actual execution result: 80-test PostgreSQL regression passed; credential-free mock Compose deployment and browser passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## REQ-1 — DEVELOPMENT EXECUTION CONTRACT

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: docs/V3_4_EXECUTION_TRACKER.md; docs/CONTINUE_FROM_HERE.md
- Required change: DEVELOPMENT EXECUTION CONTRACT
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: Audit -> P0 repair -> regression -> tracker -> Git milestone
- Test file: docs/V3_4_TEST_EVIDENCE.md
- Test name: Milestone audit and real executed gates
- Actual execution result: Baseline and both verified milestones committed; final implementation checkpoint fd62e86. Remaining security work is explicitly tracked.
- Database evidence: No original user database or volumes reset.
- Remaining blocker: Unresolved stack image security findings; exact versions and next implementation actions are in stack-security.json and CONTINUE_FROM_HERE.md.

## REQ-2 — MANDATORY BASELINE AUDIT

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: docs/V3_4_BASELINE_AUDIT.md
- Required change: MANDATORY BASELINE AUDIT
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: git archive 27812aa -> isolated dependency install -> baseline pytest
- Test file: Original archived tests
- Test name: Archived baseline pytest
- Actual execution result: 30 passed, 4 PostgreSQL skipped in baseline; skipped results were not accepted as concurrency proof.
- Database evidence: Original tracked autotrader.db preserved byte-for-byte.
- Remaining blocker: None for this requirement

## REQ-3 — CRITICAL DEFECT: TAKE-PROFIT ACCOUNTING IS STILL WRONG

Severity: P0

- Previous defect: All SELL quantities were distributed sequentially into profit targets; completed prices were erased.
- Relevant implementation files: accounting.py; models.py; position_manager.py
- Required change: CRITICAL DEFECT: TAKE-PROFIT ACCOUNTING IS STILL WRONG
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop
- Actual execution result: Corrected actual-process proof passed: TP1=3, TP2=4 after partial/restart, STOP leaves TP3=0; same-symbol lifecycle independent.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## REQ-4 — REBUILD THE FINANCIAL LEDGER

Severity: P0

- Previous defect: Mutable balances lacked an immutable financial journal and an explicit reviewed correction path.
- Relevant implementation files: src/autotrader/persistence/accounting.py; models.py; corrections.py; api/main.py
- Required change: REBUILD THE FINANCIAL LEDGER
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_risk_accounting.py; tests/test_v34_corrections.py; tests/test_v34_acceptance.py
- Test name: test_fees_cost_basis_realized_pnl_and_duplicate_fill; test_authenticated_reviewed_projection_repair_is_atomic_and_idempotent; test_proof_a_targets_survive_actual_worker_restart_and_stop
- Actual execution result: 80-case Windows regression passed, no skips. Actual authenticated correction API restores damaged projections using a reviewed fingerprint, appends operator/reason audit and zero-economic balance adjustment, refuses stale/unknown history, and applies concurrent retries once.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for fixed-capital paper accounting. External deposits/withdrawals are disabled; unresolved legacy meaning cannot be invented.

## REQ-5 — SAFE DATABASE MIGRATIONS

Severity: P0

- Previous defect: 0005 inferred positions by symbol; startup create_all bypassed versioned migration.
- Relevant implementation files: alembic/versions/0005* through 0009*; persistence/database.py
- Required change: SAFE DATABASE MIGRATIONS
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: Alembic advisory lock -> head 0009_legacy_quarantine -> check_schema -> worker readiness
- Test file: tests/test_v34_migrations.py
- Test name: test_populated_v33_history_is_preserved_and_quarantined; test_failed_postgres_migration_rolls_back_and_retries
- Actual execution result: Fresh/populated upgrade, preserved legacy reports, unresolved identity clearing, SQL constraints and transactional DDL rollback/retry passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## REQ-6 — POSTGRESQL CONCURRENCY AND EXACTLY-ONCE ECONOMIC EFFECTS

Severity: P0

- Previous defect: Risk and writes were not protected by one durable lock scope; in-memory locks cannot coordinate processes.
- Relevant implementation files: accounting.py; persistence/retry.py
- Required change: POSTGRESQL CONCURRENCY AND EXACTLY-ONCE ECONOMIC EFFECTS
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_d_concurrent_buys_idempotency_and_sell_race; test_real_postgres_deadlock_is_retried; test_lost_database_connection_after_commit_does_not_duplicate_economics
- Actual execution result: Independent-session BUY/SELL races, duplicate keys/fills, real deadlock and connection termination passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## REQ-7 — ACTUAL WORKER PROCESS RESTART RECOVERY

Severity: P0

- Previous defect: Repository reopen was called restart; initial new Windows harness killed only venv launcher. That earlier restart evidence is explicitly invalidated.
- Relevant implementation files: worker/runner.py; failure_injection.py; tests/process_support.py
- Required change: ACTUAL WORKER PROCESS RESTART RECOVERY
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop; test_proof_c_full_autonomous_lifecycle_and_authenticated_api; test_worker_entry_crash_boundaries_recover; test_exit_process_crash_rolls_back_target_and_ledger; test_worker_crash_during_cancellation_recovers_reservation
- Actual execution result: 80-test corrected regression passed. Actual interpreter PID verification: A 28656->20656, B 24100->24316, C 10652->29844. All 11 named injection boundaries represented. Linux80-case suite also passed; A81->84,B98->101,C184->193/API183,4fills,replay[].
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## REQ-8 — PORTFOLIO EQUITY-BASED RISK MANAGEMENT

Severity: P0

- Previous defect: Daily/weekly protection omitted unrealized losses; exposure could change between intention and dispatch.
- Relevant implementation files: risk.py; accounting.py; execution_gateway.py
- Required change: PORTFOLIO EQUITY-BASED RISK MANAGEMENT
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_b_unrealized_equity_halt_survives_process_restart; test_weekly_unrealized_loss_after_day_rollover; test_missing_or_stale_mark_blocks_entries; test_marked_exposure_and_pending_dispatch_are_risk_checked
- Actual execution result: Actual valuation produces equity480/daily-20 and persisted RISK_HALTED; API reports halt; protective exits work after actual restart. Weekly/stale/exposure checks passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## REQ-9 — COMPLETE AUTONOMOUS POSITION MANAGEMENT

Severity: P0

- Previous defect: Protective monitoring depended on discovery; durable trailing/expiry/cooldowns were incomplete.
- Relevant implementation files: position_manager.py; worker/runner.py; accounting.py
- Required change: COMPLETE AUTONOMOUS POSITION MANAGEMENT
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_c_full_autonomous_lifecycle_and_authenticated_api; test_worker_protective_policies_use_durable_positions; test_trailing_stop_never_moves_down_and_cooldown_survives_repository_reopen; test_strategy_cooldown_persists_across_symbols
- Actual execution result: TP1/TP2/STOP lifecycle passed; extra worker-process TIME_EXIT/EMERGENCY/MARKET_RISK tests passed. Monotonic trailing and symbol/strategy cooldown tests passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## REQ-10 — FULL AUTONOMOUS MARKET SCANNER

Severity: P1

- Previous defect: Disconnected strategies, best-only allocation and incomplete persisted explanations.
- Relevant implementation files: scanner.py; strategies.py; indicators.py; worker/runner.py
- Required change: FULL AUTONOMOUS MARKET SCANNER
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_worker_allocation.py
- Test name: test_proof_c_full_autonomous_lifecycle_and_authenticated_api; ranked candidate allocation tests
- Actual execution result: Actual scanner produces accepted/rejected versioned evidence for strategies A-H; autonomous BUY/SELL passed; public-data Compose scanner reports OK.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## REQ-11 — OPENAI SOL-READY INTELLIGENCE ENGINE

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: ai.py; persistence/ai_budget.py; api/main.py
- Required change: OPENAI SOL-READY INTELLIGENCE ENGINE
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: make_ai_provider -> bounded prompt/schema -> PG reserve -> SENT -> provider boundary -> actual usage settlement -> DecisionEngine
- Test file: tests/test_v34_ai_budget.py; tests/test_v34_acceptance.py
- Test name: test_concurrent_budget_reservations_and_idempotent_settlement; test_openai_boundary_validation_usage_and_unknown_outcomes; test_off_mode_requires_no_key_or_network; test_proof_c_full_autonomous_lifecycle_and_authenticated_api
- Actual execution result: Mock/off and strict OpenAI external-boundary tests passed; USD10 concurrent holds, token/cache prices, invalid output charging, UNKNOWN timeout holds and persistent spending verified.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: Paid account connectivity/invoice comparison NOT_RUN: no API key supplied or required. No external news feed configured; authenticated article intake and untrusted prompt context are implemented.

## REQ-12 — REAL MARKET-DATA ENGINEERING

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: market_data/revolut.py; service.py; persistence/repository.py
- Required change: REAL MARKET-DATA ENGINEERING
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: Public GET allowlist -> endpoint limiter + PG shared gate -> parser -> validation -> candles/features/marks
- Test file: tests/test_revolut_client.py; tests/test_v34_risk_accounting.py; scripts/smoke_public.py
- Test name: Read-only public smoke; parser/freshness tests; test_public_rate_gate_is_shared_by_independent_sessions
- Actual execution result: Public smoke passed:379 markets,61 EUR pairs, book/tickers and240 closed5m candles. PG shared request-family limiter and persistence/dedup tested.
- Database evidence: Compose PostgreSQL stores real public closed candles and scanner snapshots.
- Remaining blocker: None for this requirement

## REQ-13 — BACKTESTING AND QUANTITATIVE VALIDATION

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: src/autotrader/backtest.py; clock.py; cli.py; api/main.py; frontend/src/main.tsx
- Required change: BACKTESTING AND QUANTITATIVE VALIDATION
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: Backtester -> historical boundary + clock -> same scanner/gateway/manager/repository -> metrics; API/CLI/UI select explicit entry type
- Test file: tests/test_backtest.py; tests/test_v34_confirmation.py; scripts/verify_research.py
- Test name: test_historical_limit_ioc_can_expire_without_manufacturing_fills; test_backtest_produces_reproducible_report_without_fabricating_profit; public replay and walk_forward
- Actual execution result: MARKET/LIMIT IOC replay test passed: same qualifying data produces market fills while unfilled limits produce zero fills/cash movement. Real480-bar BTC/ETH replay and two disjoint OOS windows completed with losses; no edge claim. Browser executed a completed stored LIMIT report.
- Database evidence: Isolated migrated replay SQLite; runtime PostgreSQL consistency is independently tested.
- Remaining blocker: None for documented IOC/next-bar historical policy; resting queue priority is not assumed.

## REQ-14 — FRONTEND MUST REFLECT ACTUAL RUNTIME STATE

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: frontend/src/main.tsx; frontend/src/styles.css; api/main.py
- Required change: FRONTEND MUST REFLECT ACTUAL RUNTIME STATE
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: Authenticated polling -> overview/scanner/history/AI/system/settings/backtests; controls -> persistent repository controls
- Test file: frontend/e2e/dashboard.spec.ts; frontend/src/main.test.ts
- Test name: authenticated runtime data, all pages, and persistent paper controls
- Actual execution result: TypeScript/Vitest/build passed; Playwright all12pages, actual available cash, all5controls, signout and visible authoritative equity curve passed.
- Database evidence: Displayed balance and controls compared with actual authenticated backend; no fabricated chart values.
- Remaining blocker: None for this requirement

## REQ-15 — DOCKER, MIGRATIONS AND VPS SECURITY

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: Dockerfile.backend; Dockerfile.postgres; Dockerfile.redis; Dockerfile.grafana; frontend/Dockerfile; docker-compose.yml
- Required change: DOCKER, MIGRATIONS AND VPS SECURITY
- Implementation status: IN_PROGRESS
- Exact runtime call path: Generated secrets -> internal networks -> Alembic -> readiness -> worker/frontend/monitoring -> restart/restore -> actual image scans
- Test file: scripts/verify_deployment.py; scripts/verify_restore.py; security scans
- Test name: Selected Compose restart; backup/restore; source/secret review; all service image audit
- Actual execution result: Backend/frontend upgraded Alpine images report zero known vulnerabilities. Database/cache/monitoring package hardening, final restart/restore and full image review executed; exact final findings in stack-security.json.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: Remaining stack image high/critical findings require remediation/validated applicability before security clearance; see stack-security.json and continuation actions.

## REQ-16 — ABSOLUTELY NO FAKE ACCEPTANCE TESTS

Severity: P1

- Previous defect: Original50-step test repeated unrelated assertions to inflate a counter.
- Relevant implementation files: tests/test_v3_3_postgres_failure_hunt.py; tests/test_v34_acceptance.py
- Required change: ABSOLUTELY NO FAKE ACCEPTANCE TESTS
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: External data/AI boundary replay -> real PostgreSQL and internal runtime
- Test file: tests/test_v34_acceptance.py
- Test name: test_proof_c_full_autonomous_lifecycle_and_authenticated_api
- Actual execution result: Artificial50-step counter replaced by meaningful assertions. Current total reports collected test cases, not repeated assertion counts.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## REQ-17 — MANDATORY PROOF A — TARGET ATTRIBUTION

Severity: P1

- Previous defect: All SELL quantities were distributed sequentially into profit targets; completed prices were erased.
- Relevant implementation files: accounting.py; models.py; position_manager.py
- Required change: MANDATORY PROOF A — TARGET ATTRIBUTION
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop
- Actual execution result: Corrected actual-process proof passed: TP1=3, TP2=4 after partial/restart, STOP leaves TP3=0; same-symbol lifecycle independent.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## REQ-18 — MANDATORY PROOF B — EQUITY LOSS CIRCUIT BREAKER

Severity: P1

- Previous defect: Daily/weekly protection omitted unrealized losses; exposure could change between intention and dispatch.
- Relevant implementation files: risk.py; accounting.py; execution_gateway.py
- Required change: MANDATORY PROOF B — EQUITY LOSS CIRCUIT BREAKER
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_b_unrealized_equity_halt_survives_process_restart; test_weekly_unrealized_loss_after_day_rollover; test_missing_or_stale_mark_blocks_entries; test_marked_exposure_and_pending_dispatch_are_risk_checked
- Actual execution result: Actual valuation produces equity480/daily-20 and persisted RISK_HALTED; API reports halt; protective exits work after actual restart. Weekly/stale/exposure checks passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## REQ-19 — MANDATORY PROOF C — FULL AUTONOMOUS LIFECYCLE

Severity: P1

- Previous defect: Repository reopen was called restart; initial new Windows harness killed only venv launcher. That earlier restart evidence is explicitly invalidated.
- Relevant implementation files: worker/runner.py; failure_injection.py; tests/process_support.py
- Required change: MANDATORY PROOF C — FULL AUTONOMOUS LIFECYCLE
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop; test_proof_c_full_autonomous_lifecycle_and_authenticated_api; test_worker_entry_crash_boundaries_recover; test_exit_process_crash_rolls_back_target_and_ledger; test_worker_crash_during_cancellation_recovers_reservation
- Actual execution result: 80-test corrected regression passed. Actual interpreter PID verification: A 28656->20656, B 24100->24316, C 10652->29844. All 11 named injection boundaries represented. Linux80-case suite also passed; A81->84,B98->101,C184->193/API183,4fills,replay[].
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## REQ-20 — MANDATORY PROOF D — CONCURRENCY

Severity: P1

- Previous defect: Risk and writes were not protected by one durable lock scope; in-memory locks cannot coordinate processes.
- Relevant implementation files: accounting.py; persistence/retry.py
- Required change: MANDATORY PROOF D — CONCURRENCY
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_d_concurrent_buys_idempotency_and_sell_race; test_real_postgres_deadlock_is_retried; test_lost_database_connection_after_commit_does_not_duplicate_economics
- Actual execution result: Independent-session BUY/SELL races, duplicate keys/fills, real deadlock and connection termination passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## REQ-21 — MANDATORY PROOF E — REAL MARKET-DATA OPERATION

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: market_data/revolut.py; service.py; persistence/repository.py
- Required change: MANDATORY PROOF E — REAL MARKET-DATA OPERATION
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: Public GET allowlist -> endpoint limiter + PG shared gate -> parser -> validation -> candles/features/marks
- Test file: tests/test_revolut_client.py; tests/test_v34_risk_accounting.py; scripts/smoke_public.py
- Test name: Read-only public smoke; parser/freshness tests; test_public_rate_gate_is_shared_by_independent_sessions
- Actual execution result: Public smoke passed:379 markets,61 EUR pairs, book/tickers and240 closed5m candles. PG shared request-family limiter and persistence/dedup tested.
- Database evidence: Compose PostgreSQL stores real public closed candles and scanner snapshots.
- Remaining blocker: None for this requirement

## REQ-22 — MANDATORY PROOF F — DOCKER AND FRONTEND

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: frontend/src/main.tsx; frontend/src/styles.css; api/main.py
- Required change: MANDATORY PROOF F — DOCKER AND FRONTEND
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: Authenticated polling -> overview/scanner/history/AI/system/settings/backtests; controls -> persistent repository controls
- Test file: frontend/e2e/dashboard.spec.ts; frontend/src/main.test.ts
- Test name: authenticated runtime data, all pages, and persistent paper controls
- Actual execution result: TypeScript/Vitest/build passed; Playwright all12pages, actual available cash, all5controls, signout and visible authoritative equity curve passed.
- Database evidence: Displayed balance and controls compared with actual authenticated backend; no fabricated chart values.
- Remaining blocker: None for this requirement

## REQ-23 — FULL AUTOMATED QUALITY GATES

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: docs/V3_4_TEST_EVIDENCE.md; requirements.lock; package-lock.json
- Required change: FULL AUTOMATED QUALITY GATES
- Implementation status: IN_PROGRESS
- Exact runtime call path: Independent quality tools -> machine-readable evidence files
- Test file: Full pytest; Ruff; Mypy; frontend gates; security audits
- Test name: Exact commands and captured outputs in V3_4_TEST_EVIDENCE.md
- Actual execution result: 80 passed, no failures/skips in complete-regression.xml. Linux password-authenticated full regression also passed80cases/no skips in341.53s; stack security findings remain. TypeScript/Vitest/build/Playwright passed.
- Database evidence: Real PG integration required; backend package checks do not replace Docker or browser proof.
- Remaining blocker: Unresolved stack image security findings; exact versions and next implementation actions are in stack-security.json and CONTINUE_FROM_HERE.md.

## REQ-24 — STRICT PRIORITY ORDER

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: docs/V3_4_BASELINE_AUDIT.md; Git milestones
- Required change: STRICT PRIORITY ORDER
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: Baseline -> P0 milestone5b900db -> P1 runtime/deployment -> adversarial gates
- Test file: docs/V3_4_TEST_EVIDENCE.md
- Test name: P0 accounting/recovery and P1 integration sequence
- Actual execution result: Financial identity, ledger, migration, concurrency and risk fixes preceded frontend work.
- Database evidence: No destructive user-volume operations.
- Remaining blocker: None for this requirement

## REQ-25 — CODEX SELF-VERIFICATION IS NOT SUFFICIENT

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: docs/V3_4_ADVERSARIAL_REVIEW.md
- Required change: CODEX SELF-VERIFICATION IS NOT SUFFICIENT
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: Assume incorrect implementation -> attack identity/cash/risk/process assumptions -> independent expected assertions
- Test file: tests/test_v34_risk_accounting.py; tests/test_v34_acceptance.py
- Test name: test_corrupt_position_projection_cannot_authorize_oversell; test_marked_exposure_and_pending_dispatch_are_risk_checked; actual PID restart proofs
- Actual execution result: Separate adversarial pass found and corrected oversell projection, dispatch exposure, forming candle and Windows launcher restart defects; regressions executed.
- Database evidence: Immutable fill/journal replay and kernel PID termination checks provide separate evidence.
- Remaining blocker: No external human review or paid-provider audit was performed.

## REQ-26 — FILES REQUIRED AT DELIVERY

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: docs/V3_4_*.md; scripts/; alembic/; tests/fixtures/
- Required change: FILES REQUIRED AT DELIVERY
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: Source artifacts -> executable gates -> factual documentation
- Test file: docs/V3_4_TEST_EVIDENCE.md
- Test name: Deliverable inventory and executed script checks
- Actual execution result: Required documentation, migrations, reconciliation command, replay fixture, actual process harness, secrets template, dashboard and deployment/restore scripts supplied.
- Database evidence: Schema head and backup evidence recorded.
- Remaining blocker: None for this requirement

## REQ-27 — FINAL ACCEPTANCE CONTRACT

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: docs/V3_4_EXECUTION_TRACKER.md
- Required change: FINAL ACCEPTANCE CONTRACT
- Implementation status: IN_PROGRESS
- Exact runtime call path: Requirement-specific source and executed proof -> acceptance status
- Test file: AC-01 through AC-44 below
- Test name: Evidence mapped per acceptance condition
- Actual execution result: Individual acceptance conditions are mapped below; this does not waive unresolved detailed requirements.
- Database evidence: Financial and restart assertions must pass against actual PG/processes.
- Remaining blocker: Unresolved stack image security findings; exact versions and next implementation actions are in stack-security.json and CONTINUE_FROM_HERE.md.

## REQ-28 — FINAL RESPONSE FORMAT

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: Final engineering report; docs/CONTINUE_FROM_HERE.md
- Required change: FINAL RESPONSE FORMAT
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: Executed evidence -> exact status -> continuation actions
- Test file: docs/V3_4_TEST_EVIDENCE.md
- Test name: A-K factual report
- Actual execution result: A-K report prepared from executed evidence with status PARTIALLY_COMPLETE_WITH_BLOCKERS; security blockers and precise continuation are recorded.
- Database evidence: No unsupported completion or profitability claims.
- Remaining blocker: Unresolved stack image security findings; exact versions and next implementation actions are in stack-security.json and CONTINUE_FROM_HERE.md.

## AC-01 — Historical fills are not misattributed.

Severity: P0

- Previous defect: 0005 inferred positions by symbol; startup create_all bypassed versioned migration.
- Relevant implementation files: alembic/versions/0005* through 0009*; persistence/database.py
- Required change: Historical fills are not misattributed.
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: Alembic advisory lock -> head 0009_legacy_quarantine -> check_schema -> worker readiness
- Test file: tests/test_v34_migrations.py
- Test name: test_populated_v33_history_is_preserved_and_quarantined; test_failed_postgres_migration_rolls_back_and_retries
- Actual execution result: Fresh/populated upgrade, preserved legacy reports, unresolved identity clearing, SQL constraints and transactional DDL rollback/retry passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-02 — Each position has unique lifecycle identity.

Severity: P0

- Previous defect: All SELL quantities were distributed sequentially into profit targets; completed prices were erased.
- Relevant implementation files: accounting.py; models.py; position_manager.py
- Required change: Each position has unique lifecycle identity.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop
- Actual execution result: Corrected actual-process proof passed: TP1=3, TP2=4 after partial/restart, STOP leaves TP3=0; same-symbol lifecycle independent.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-03 — Exit intents have stable identities.

Severity: P0

- Previous defect: All SELL quantities were distributed sequentially into profit targets; completed prices were erased.
- Relevant implementation files: accounting.py; models.py; position_manager.py
- Required change: Exit intents have stable identities.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop
- Actual execution result: Corrected actual-process proof passed: TP1=3, TP2=4 after partial/restart, STOP leaves TP3=0; same-symbol lifecycle independent.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-04 — TP1/TP2/TP3 track only their actual linked fills.

Severity: P0

- Previous defect: All SELL quantities were distributed sequentially into profit targets; completed prices were erased.
- Relevant implementation files: accounting.py; models.py; position_manager.py
- Required change: TP1/TP2/TP3 track only their actual linked fills.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop
- Actual execution result: Corrected actual-process proof passed: TP1=3, TP2=4 after partial/restart, STOP leaves TP3=0; same-symbol lifecycle independent.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-05 — Stop exits cannot modify TP progress.

Severity: P0

- Previous defect: All SELL quantities were distributed sequentially into profit targets; completed prices were erased.
- Relevant implementation files: accounting.py; models.py; position_manager.py
- Required change: Stop exits cannot modify TP progress.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop
- Actual execution result: Corrected actual-process proof passed: TP1=3, TP2=4 after partial/restart, STOP leaves TP3=0; same-symbol lifecycle independent.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-06 — Multiple positions in the same symbol remain independent.

Severity: P0

- Previous defect: All SELL quantities were distributed sequentially into profit targets; completed prices were erased.
- Relevant implementation files: accounting.py; models.py; position_manager.py
- Required change: Multiple positions in the same symbol remain independent.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop
- Actual execution result: Corrected actual-process proof passed: TP1=3, TP2=4 after partial/restart, STOP leaves TP3=0; same-symbol lifecycle independent.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-07 — Realized P&L is attributed correctly.

Severity: P0

- Previous defect: Mutable balances lacked an immutable financial journal and an explicit reviewed correction path.
- Relevant implementation files: src/autotrader/persistence/accounting.py; models.py; corrections.py; api/main.py
- Required change: Realized P&L is attributed correctly.
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_risk_accounting.py; tests/test_v34_corrections.py; tests/test_v34_acceptance.py
- Test name: test_fees_cost_basis_realized_pnl_and_duplicate_fill; test_authenticated_reviewed_projection_repair_is_atomic_and_idempotent; test_proof_a_targets_survive_actual_worker_restart_and_stop
- Actual execution result: 80-case Windows regression passed, no skips. Actual authenticated correction API restores damaged projections using a reviewed fingerprint, appends operator/reason audit and zero-economic balance adjustment, refuses stale/unknown history, and applies concurrent retries once.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this narrower clause; the containing REQ remains incomplete as stated above.

## AC-08 — Entry and exit fees are handled correctly.

Severity: P0

- Previous defect: Mutable balances lacked an immutable financial journal and an explicit reviewed correction path.
- Relevant implementation files: src/autotrader/persistence/accounting.py; models.py; corrections.py; api/main.py
- Required change: Entry and exit fees are handled correctly.
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_risk_accounting.py; tests/test_v34_corrections.py; tests/test_v34_acceptance.py
- Test name: test_fees_cost_basis_realized_pnl_and_duplicate_fill; test_authenticated_reviewed_projection_repair_is_atomic_and_idempotent; test_proof_a_targets_survive_actual_worker_restart_and_stop
- Actual execution result: 80-case Windows regression passed, no skips. Actual authenticated correction API restores damaged projections using a reviewed fingerprint, appends operator/reason audit and zero-economic balance adjustment, refuses stale/unknown history, and applies concurrent retries once.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this narrower clause; the containing REQ remains incomplete as stated above.

## AC-09 — Ledger replay reconstructs balances.

Severity: P0

- Previous defect: Mutable balances lacked an immutable financial journal and an explicit reviewed correction path.
- Relevant implementation files: src/autotrader/persistence/accounting.py; models.py; corrections.py; api/main.py
- Required change: Ledger replay reconstructs balances.
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_risk_accounting.py; tests/test_v34_corrections.py; tests/test_v34_acceptance.py
- Test name: test_fees_cost_basis_realized_pnl_and_duplicate_fill; test_authenticated_reviewed_projection_repair_is_atomic_and_idempotent; test_proof_a_targets_survive_actual_worker_restart_and_stop
- Actual execution result: 80-case Windows regression passed, no skips. Actual authenticated correction API restores damaged projections using a reviewed fingerprint, appends operator/reason audit and zero-economic balance adjustment, refuses stale/unknown history, and applies concurrent retries once.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this narrower clause; the containing REQ remains incomplete as stated above.

## AC-10 — Cash and quantity invariants pass.

Severity: P0

- Previous defect: Mutable balances lacked an immutable financial journal and an explicit reviewed correction path.
- Relevant implementation files: src/autotrader/persistence/accounting.py; models.py; corrections.py; api/main.py
- Required change: Cash and quantity invariants pass.
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_risk_accounting.py; tests/test_v34_corrections.py; tests/test_v34_acceptance.py
- Test name: test_fees_cost_basis_realized_pnl_and_duplicate_fill; test_authenticated_reviewed_projection_repair_is_atomic_and_idempotent; test_proof_a_targets_survive_actual_worker_restart_and_stop
- Actual execution result: 80-case Windows regression passed, no skips. Actual authenticated correction API restores damaged projections using a reviewed fingerprint, appends operator/reason audit and zero-economic balance adjustment, refuses stale/unknown history, and applies concurrent retries once.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this narrower clause; the containing REQ remains incomplete as stated above.

## AC-11 — PostgreSQL row-level concurrency tests pass.

Severity: P0

- Previous defect: Risk and writes were not protected by one durable lock scope; in-memory locks cannot coordinate processes.
- Relevant implementation files: accounting.py; persistence/retry.py
- Required change: PostgreSQL row-level concurrency tests pass.
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_d_concurrent_buys_idempotency_and_sell_race; test_real_postgres_deadlock_is_retried; test_lost_database_connection_after_commit_does_not_duplicate_economics
- Actual execution result: Independent-session BUY/SELL races, duplicate keys/fills, real deadlock and connection termination passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-12 — Duplicate fills have no duplicate economic effect.

Severity: P0

- Previous defect: Risk and writes were not protected by one durable lock scope; in-memory locks cannot coordinate processes.
- Relevant implementation files: accounting.py; persistence/retry.py
- Required change: Duplicate fills have no duplicate economic effect.
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_d_concurrent_buys_idempotency_and_sell_race; test_real_postgres_deadlock_is_retried; test_lost_database_connection_after_commit_does_not_duplicate_economics
- Actual execution result: Independent-session BUY/SELL races, duplicate keys/fills, real deadlock and connection termination passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-13 — Pending orders recover after actual process restart.

Severity: P0

- Previous defect: Repository reopen was called restart; initial new Windows harness killed only venv launcher. That earlier restart evidence is explicitly invalidated.
- Relevant implementation files: worker/runner.py; failure_injection.py; tests/process_support.py
- Required change: Pending orders recover after actual process restart.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop; test_proof_c_full_autonomous_lifecycle_and_authenticated_api; test_worker_entry_crash_boundaries_recover; test_exit_process_crash_rolls_back_target_and_ledger; test_worker_crash_during_cancellation_recovers_reservation
- Actual execution result: 80-test corrected regression passed. Actual interpreter PID verification: A 28656->20656, B 24100->24316, C 10652->29844. All 11 named injection boundaries represented. Linux80-case suite also passed; A81->84,B98->101,C184->193/API183,4fills,replay[].
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-14 — Capital reservations persist correctly.

Severity: P0

- Previous defect: Repository reopen was called restart; initial new Windows harness killed only venv launcher. That earlier restart evidence is explicitly invalidated.
- Relevant implementation files: worker/runner.py; failure_injection.py; tests/process_support.py
- Required change: Capital reservations persist correctly.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop; test_proof_c_full_autonomous_lifecycle_and_authenticated_api; test_worker_entry_crash_boundaries_recover; test_exit_process_crash_rolls_back_target_and_ledger; test_worker_crash_during_cancellation_recovers_reservation
- Actual execution result: 80-test corrected regression passed. Actual interpreter PID verification: A 28656->20656, B 24100->24316, C 10652->29844. All 11 named injection boundaries represented. Linux80-case suite also passed; A81->84,B98->101,C184->193/API183,4fills,replay[].
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-15 — Daily unrealized losses trigger risk controls.

Severity: P0

- Previous defect: Daily/weekly protection omitted unrealized losses; exposure could change between intention and dispatch.
- Relevant implementation files: risk.py; accounting.py; execution_gateway.py
- Required change: Daily unrealized losses trigger risk controls.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_b_unrealized_equity_halt_survives_process_restart; test_weekly_unrealized_loss_after_day_rollover; test_missing_or_stale_mark_blocks_entries; test_marked_exposure_and_pending_dispatch_are_risk_checked
- Actual execution result: Actual valuation produces equity480/daily-20 and persisted RISK_HALTED; API reports halt; protective exits work after actual restart. Weekly/stale/exposure checks passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-16 — Weekly unrealized losses trigger risk controls.

Severity: P0

- Previous defect: Daily/weekly protection omitted unrealized losses; exposure could change between intention and dispatch.
- Relevant implementation files: risk.py; accounting.py; execution_gateway.py
- Required change: Weekly unrealized losses trigger risk controls.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_b_unrealized_equity_halt_survives_process_restart; test_weekly_unrealized_loss_after_day_rollover; test_missing_or_stale_mark_blocks_entries; test_marked_exposure_and_pending_dispatch_are_risk_checked
- Actual execution result: Actual valuation produces equity480/daily-20 and persisted RISK_HALTED; API reports halt; protective exits work after actual restart. Weekly/stale/exposure checks passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-17 — Risk circuit breakers persist after restart.

Severity: P0

- Previous defect: Daily/weekly protection omitted unrealized losses; exposure could change between intention and dispatch.
- Relevant implementation files: risk.py; accounting.py; execution_gateway.py
- Required change: Risk circuit breakers persist after restart.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_b_unrealized_equity_halt_survives_process_restart; test_weekly_unrealized_loss_after_day_rollover; test_missing_or_stale_mark_blocks_entries; test_marked_exposure_and_pending_dispatch_are_risk_checked
- Actual execution result: Actual valuation produces equity480/daily-20 and persisted RISK_HALTED; API reports halt; protective exits work after actual restart. Weekly/stale/exposure checks passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-18 — Stale portfolio valuation blocks unsafe entries.

Severity: P0

- Previous defect: Daily/weekly protection omitted unrealized losses; exposure could change between intention and dispatch.
- Relevant implementation files: risk.py; accounting.py; execution_gateway.py
- Required change: Stale portfolio valuation blocks unsafe entries.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_b_unrealized_equity_halt_survives_process_restart; test_weekly_unrealized_loss_after_day_rollover; test_missing_or_stale_mark_blocks_entries; test_marked_exposure_and_pending_dispatch_are_risk_checked
- Actual execution result: Actual valuation produces equity480/daily-20 and persisted RISK_HALTED; API reports halt; protective exits work after actual restart. Weekly/stale/exposure checks passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-19 — Every open position is independently monitored.

Severity: P0

- Previous defect: Protective monitoring depended on discovery; durable trailing/expiry/cooldowns were incomplete.
- Relevant implementation files: position_manager.py; worker/runner.py; accounting.py
- Required change: Every open position is independently monitored.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_c_full_autonomous_lifecycle_and_authenticated_api; test_worker_protective_policies_use_durable_positions; test_trailing_stop_never_moves_down_and_cooldown_survives_repository_reopen; test_strategy_cooldown_persists_across_symbols
- Actual execution result: TP1/TP2/STOP lifecycle passed; extra worker-process TIME_EXIT/EMERGENCY/MARKET_RISK tests passed. Monotonic trailing and symbol/strategy cooldown tests passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-20 — Multi-stage take-profit works.

Severity: P0

- Previous defect: All SELL quantities were distributed sequentially into profit targets; completed prices were erased.
- Relevant implementation files: accounting.py; models.py; position_manager.py
- Required change: Multi-stage take-profit works.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop
- Actual execution result: Corrected actual-process proof passed: TP1=3, TP2=4 after partial/restart, STOP leaves TP3=0; same-symbol lifecycle independent.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-21 — Trailing stops work.

Severity: P0

- Previous defect: Protective monitoring depended on discovery; durable trailing/expiry/cooldowns were incomplete.
- Relevant implementation files: position_manager.py; worker/runner.py; accounting.py
- Required change: Trailing stops work.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_c_full_autonomous_lifecycle_and_authenticated_api; test_worker_protective_policies_use_durable_positions; test_trailing_stop_never_moves_down_and_cooldown_survives_repository_reopen; test_strategy_cooldown_persists_across_symbols
- Actual execution result: TP1/TP2/STOP lifecycle passed; extra worker-process TIME_EXIT/EMERGENCY/MARKET_RISK tests passed. Monotonic trailing and symbol/strategy cooldown tests passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-22 — Time-based exits work.

Severity: P0

- Previous defect: Protective monitoring depended on discovery; durable trailing/expiry/cooldowns were incomplete.
- Relevant implementation files: position_manager.py; worker/runner.py; accounting.py
- Required change: Time-based exits work.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_c_full_autonomous_lifecycle_and_authenticated_api; test_worker_protective_policies_use_durable_positions; test_trailing_stop_never_moves_down_and_cooldown_survives_repository_reopen; test_strategy_cooldown_persists_across_symbols
- Actual execution result: TP1/TP2/STOP lifecycle passed; extra worker-process TIME_EXIT/EMERGENCY/MARKET_RISK tests passed. Monotonic trailing and symbol/strategy cooldown tests passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-23 — Re-entry cooldown persists.

Severity: P0

- Previous defect: Protective monitoring depended on discovery; durable trailing/expiry/cooldowns were incomplete.
- Relevant implementation files: position_manager.py; worker/runner.py; accounting.py
- Required change: Re-entry cooldown persists.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_c_full_autonomous_lifecycle_and_authenticated_api; test_worker_protective_policies_use_durable_positions; test_trailing_stop_never_moves_down_and_cooldown_survives_repository_reopen; test_strategy_cooldown_persists_across_symbols
- Actual execution result: TP1/TP2/STOP lifecycle passed; extra worker-process TIME_EXIT/EMERGENCY/MARKET_RISK tests passed. Monotonic trailing and symbol/strategy cooldown tests passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-24 — Multiple market candidates are evaluated.

Severity: P1

- Previous defect: Disconnected strategies, best-only allocation and incomplete persisted explanations.
- Relevant implementation files: scanner.py; strategies.py; indicators.py; worker/runner.py
- Required change: Multiple market candidates are evaluated.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_worker_allocation.py
- Test name: test_proof_c_full_autonomous_lifecycle_and_authenticated_api; ranked candidate allocation tests
- Actual execution result: Actual scanner produces accepted/rejected versioned evidence for strategies A-H; autonomous BUY/SELL passed; public-data Compose scanner reports OK.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-25 — Autonomous simulated BUY works.

Severity: P1

- Previous defect: Disconnected strategies, best-only allocation and incomplete persisted explanations.
- Relevant implementation files: scanner.py; strategies.py; indicators.py; worker/runner.py
- Required change: Autonomous simulated BUY works.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_worker_allocation.py
- Test name: test_proof_c_full_autonomous_lifecycle_and_authenticated_api; ranked candidate allocation tests
- Actual execution result: Actual scanner produces accepted/rejected versioned evidence for strategies A-H; autonomous BUY/SELL passed; public-data Compose scanner reports OK.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-26 — Autonomous simulated SELL works.

Severity: P1

- Previous defect: Disconnected strategies, best-only allocation and incomplete persisted explanations.
- Relevant implementation files: scanner.py; strategies.py; indicators.py; worker/runner.py
- Required change: Autonomous simulated SELL works.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_worker_allocation.py
- Test name: test_proof_c_full_autonomous_lifecycle_and_authenticated_api; ranked candidate allocation tests
- Actual execution result: Actual scanner produces accepted/rejected versioned evidence for strategies A-H; autonomous BUY/SELL passed; public-data Compose scanner reports OK.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-27 — Risk is enforced on every execution path.

Severity: P0

- Previous defect: Daily/weekly protection omitted unrealized losses; exposure could change between intention and dispatch.
- Relevant implementation files: risk.py; accounting.py; execution_gateway.py
- Required change: Risk is enforced on every execution path.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_b_unrealized_equity_halt_survives_process_restart; test_weekly_unrealized_loss_after_day_rollover; test_missing_or_stale_mark_blocks_entries; test_marked_exposure_and_pending_dispatch_are_risk_checked
- Actual execution result: Actual valuation produces equity480/daily-20 and persisted RISK_HALTED; API reports halt; protective exits work after actual restart. Weekly/stale/exposure checks passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-28 — Persistent OpenAI spending controls work.

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: ai.py; persistence/ai_budget.py; api/main.py
- Required change: Persistent OpenAI spending controls work.
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: make_ai_provider -> bounded prompt/schema -> PG reserve -> SENT -> provider boundary -> actual usage settlement -> DecisionEngine
- Test file: tests/test_v34_ai_budget.py; tests/test_v34_acceptance.py
- Test name: test_concurrent_budget_reservations_and_idempotent_settlement; test_openai_boundary_validation_usage_and_unknown_outcomes; test_off_mode_requires_no_key_or_network; test_proof_c_full_autonomous_lifecycle_and_authenticated_api
- Actual execution result: Mock/off and strict OpenAI external-boundary tests passed; USD10 concurrent holds, token/cache prices, invalid output charging, UNKNOWN timeout holds and persistent spending verified.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: Paid account connectivity/invoice comparison NOT_RUN: no API key supplied or required. No external news feed configured; authenticated article intake and untrusted prompt context are implemented.

## AC-29 — Mock AI operates without credentials.

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: ai.py; persistence/ai_budget.py; api/main.py
- Required change: Mock AI operates without credentials.
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: make_ai_provider -> bounded prompt/schema -> PG reserve -> SENT -> provider boundary -> actual usage settlement -> DecisionEngine
- Test file: tests/test_v34_ai_budget.py; tests/test_v34_acceptance.py
- Test name: test_concurrent_budget_reservations_and_idempotent_settlement; test_openai_boundary_validation_usage_and_unknown_outcomes; test_off_mode_requires_no_key_or_network; test_proof_c_full_autonomous_lifecycle_and_authenticated_api
- Actual execution result: Mock/off and strict OpenAI external-boundary tests passed; USD10 concurrent holds, token/cache prices, invalid output charging, UNKNOWN timeout holds and persistent spending verified.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: Paid account connectivity/invoice comparison NOT_RUN: no API key supplied or required. No external news feed configured; authenticated article intake and untrusted prompt context are implemented.

## AC-30 — Exchange market-data parsing works.

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: market_data/revolut.py; service.py; persistence/repository.py
- Required change: Exchange market-data parsing works.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: Public GET allowlist -> endpoint limiter + PG shared gate -> parser -> validation -> candles/features/marks
- Test file: tests/test_revolut_client.py; tests/test_v34_risk_accounting.py; scripts/smoke_public.py
- Test name: Read-only public smoke; parser/freshness tests; test_public_rate_gate_is_shared_by_independent_sessions
- Actual execution result: Public smoke passed:379 markets,61 EUR pairs, book/tickers and240 closed5m candles. PG shared request-family limiter and persistence/dedup tested.
- Database evidence: Compose PostgreSQL stores real public closed candles and scanner snapshots.
- Remaining blocker: None for this requirement

## AC-31 — Historical market data is persisted.

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: market_data/revolut.py; service.py; persistence/repository.py
- Required change: Historical market data is persisted.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: Public GET allowlist -> endpoint limiter + PG shared gate -> parser -> validation -> candles/features/marks
- Test file: tests/test_revolut_client.py; tests/test_v34_risk_accounting.py; scripts/smoke_public.py
- Test name: Read-only public smoke; parser/freshness tests; test_public_rate_gate_is_shared_by_independent_sessions
- Actual execution result: Public smoke passed:379 markets,61 EUR pairs, book/tickers and240 closed5m candles. PG shared request-family limiter and persistence/dedup tested.
- Database evidence: Compose PostgreSQL stores real public closed candles and scanner snapshots.
- Remaining blocker: None for this requirement

## AC-32 — Multiple strategies are connected to the runtime.

Severity: P1

- Previous defect: Disconnected strategies, best-only allocation and incomplete persisted explanations.
- Relevant implementation files: scanner.py; strategies.py; indicators.py; worker/runner.py
- Required change: Multiple strategies are connected to the runtime.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_worker_allocation.py
- Test name: test_proof_c_full_autonomous_lifecycle_and_authenticated_api; ranked candidate allocation tests
- Actual execution result: Actual scanner produces accepted/rejected versioned evidence for strategies A-H; autonomous BUY/SELL passed; public-data Compose scanner reports OK.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-33 — Backtesting produces reproducible outcomes.

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: src/autotrader/backtest.py; clock.py; cli.py; api/main.py; frontend/src/main.tsx
- Required change: Backtesting produces reproducible outcomes.
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: Backtester -> historical boundary + clock -> same scanner/gateway/manager/repository -> metrics; API/CLI/UI select explicit entry type
- Test file: tests/test_backtest.py; tests/test_v34_confirmation.py; scripts/verify_research.py
- Test name: test_historical_limit_ioc_can_expire_without_manufacturing_fills; test_backtest_produces_reproducible_report_without_fabricating_profit; public replay and walk_forward
- Actual execution result: MARKET/LIMIT IOC replay test passed: same qualifying data produces market fills while unfilled limits produce zero fills/cash movement. Real480-bar BTC/ETH replay and two disjoint OOS windows completed with losses; no edge claim. Browser executed a completed stored LIMIT report.
- Database evidence: Isolated migrated replay SQLite; runtime PostgreSQL consistency is independently tested.
- Remaining blocker: None for this narrower clause; the containing REQ remains incomplete as stated above.

## AC-34 — Dashboard uses authoritative backend data.

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: frontend/src/main.tsx; frontend/src/styles.css; api/main.py
- Required change: Dashboard uses authoritative backend data.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: Authenticated polling -> overview/scanner/history/AI/system/settings/backtests; controls -> persistent repository controls
- Test file: frontend/e2e/dashboard.spec.ts; frontend/src/main.test.ts
- Test name: authenticated runtime data, all pages, and persistent paper controls
- Actual execution result: TypeScript/Vitest/build passed; Playwright all12pages, actual available cash, all5controls, signout and visible authoritative equity curve passed.
- Database evidence: Displayed balance and controls compared with actual authenticated backend; no fabricated chart values.
- Remaining blocker: None for this requirement

## AC-35 — Paper-trading controls actually function.

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: frontend/src/main.tsx; frontend/src/styles.css; api/main.py
- Required change: Paper-trading controls actually function.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: Authenticated polling -> overview/scanner/history/AI/system/settings/backtests; controls -> persistent repository controls
- Test file: frontend/e2e/dashboard.spec.ts; frontend/src/main.test.ts
- Test name: authenticated runtime data, all pages, and persistent paper controls
- Actual execution result: TypeScript/Vitest/build passed; Playwright all12pages, actual available cash, all5controls, signout and visible authoritative equity curve passed.
- Database evidence: Displayed balance and controls compared with actual authenticated backend; no fabricated chart values.
- Remaining blocker: None for this requirement

## AC-36 — API administrative controls are authenticated.

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: frontend/src/main.tsx; frontend/src/styles.css; api/main.py
- Required change: API administrative controls are authenticated.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: Authenticated polling -> overview/scanner/history/AI/system/settings/backtests; controls -> persistent repository controls
- Test file: frontend/e2e/dashboard.spec.ts; frontend/src/main.test.ts
- Test name: authenticated runtime data, all pages, and persistent paper controls
- Actual execution result: TypeScript/Vitest/build passed; Playwright all12pages, actual available cash, all5controls, signout and visible authoritative equity curve passed.
- Database evidence: Displayed balance and controls compared with actual authenticated backend; no fabricated chart values.
- Remaining blocker: None for this requirement

## AC-37 — Database migrations run correctly.

Severity: P0

- Previous defect: 0005 inferred positions by symbol; startup create_all bypassed versioned migration.
- Relevant implementation files: alembic/versions/0005* through 0009*; persistence/database.py
- Required change: Database migrations run correctly.
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: Alembic advisory lock -> head 0009_legacy_quarantine -> check_schema -> worker readiness
- Test file: tests/test_v34_migrations.py
- Test name: test_populated_v33_history_is_preserved_and_quarantined; test_failed_postgres_migration_rolls_back_and_retries
- Actual execution result: Fresh/populated upgrade, preserved legacy reports, unresolved identity clearing, SQL constraints and transactional DDL rollback/retry passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-38 — Docker deployment is verified.

Severity: P1

- Previous defect: See V3_4_BASELINE_AUDIT.md for verified baseline defects.
- Relevant implementation files: Dockerfile.backend; Dockerfile.postgres; Dockerfile.redis; Dockerfile.grafana; frontend/Dockerfile; docker-compose.yml
- Required change: Docker deployment is verified.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: Generated secrets -> internal networks -> Alembic -> readiness -> worker/frontend/monitoring -> restart/restore -> actual image scans
- Test file: scripts/verify_deployment.py; scripts/verify_restore.py; security scans
- Test name: Selected Compose restart; backup/restore; source/secret review; all service image audit
- Actual execution result: Backend/frontend upgraded Alpine images report zero known vulnerabilities. Database/cache/monitoring package hardening, final restart/restore and full image review executed; exact final findings in stack-security.json.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: Deployment/restart verified; OS findings remain separately tracked in REQ-15.

## AC-39 — Real worker restart test passes.

Severity: P0

- Previous defect: Repository reopen was called restart; initial new Windows harness killed only venv launcher. That earlier restart evidence is explicitly invalidated.
- Relevant implementation files: worker/runner.py; failure_injection.py; tests/process_support.py
- Required change: Real worker restart test passes.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop; test_proof_c_full_autonomous_lifecycle_and_authenticated_api; test_worker_entry_crash_boundaries_recover; test_exit_process_crash_rolls_back_target_and_ledger; test_worker_crash_during_cancellation_recovers_reservation
- Actual execution result: 80-test corrected regression passed. Actual interpreter PID verification: A 28656->20656, B 24100->24316, C 10652->29844. All 11 named injection boundaries represented. Linux80-case suite also passed; A81->84,B98->101,C184->193/API183,4fills,replay[].
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-40 — Financial reconciliation passes after restart.

Severity: P0

- Previous defect: Repository reopen was called restart; initial new Windows harness killed only venv launcher. That earlier restart evidence is explicitly invalidated.
- Relevant implementation files: worker/runner.py; failure_injection.py; tests/process_support.py
- Required change: Financial reconciliation passes after restart.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop; test_proof_c_full_autonomous_lifecycle_and_authenticated_api; test_worker_entry_crash_boundaries_recover; test_exit_process_crash_rolls_back_target_and_ledger; test_worker_crash_during_cancellation_recovers_reservation
- Actual execution result: 80-test corrected regression passed. Actual interpreter PID verification: A 28656->20656, B 24100->24316, C 10652->29844. All 11 named injection boundaries represented. Linux80-case suite also passed; A81->84,B98->101,C184->193/API183,4fills,replay[].
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-41 — Concurrent BUY/SELL tests pass.

Severity: P0

- Previous defect: Risk and writes were not protected by one durable lock scope; in-memory locks cannot coordinate processes.
- Relevant implementation files: accounting.py; persistence/retry.py
- Required change: Concurrent BUY/SELL tests pass.
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_d_concurrent_buys_idempotency_and_sell_race; test_real_postgres_deadlock_is_retried; test_lost_database_connection_after_commit_does_not_duplicate_economics
- Actual execution result: Independent-session BUY/SELL races, duplicate keys/fills, real deadlock and connection termination passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-42 — End-to-end autonomous lifecycle passes.

Severity: P0

- Previous defect: Repository reopen was called restart; initial new Windows harness killed only venv launcher. That earlier restart evidence is explicitly invalidated.
- Relevant implementation files: worker/runner.py; failure_injection.py; tests/process_support.py
- Required change: End-to-end autonomous lifecycle passes.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: worker.runner.main -> MarketScanner.scan_once -> DecisionEngine -> PaperExecutionGateway -> repository.submit_order -> dispatch_order -> fill/journal transaction; PositionManager.monitor_once -> execute_exit
- Test file: tests/test_v34_acceptance.py; tests/test_v34_risk_accounting.py
- Test name: test_proof_a_targets_survive_actual_worker_restart_and_stop; test_proof_c_full_autonomous_lifecycle_and_authenticated_api; test_worker_entry_crash_boundaries_recover; test_exit_process_crash_rolls_back_target_and_ledger; test_worker_crash_during_cancellation_recovers_reservation
- Actual execution result: 80-test corrected regression passed. Actual interpreter PID verification: A 28656->20656, B 24100->24316, C 10652->29844. All 11 named injection boundaries represented. Linux80-case suite also passed; A81->84,B98->101,C184->193/API183,4fills,replay[].
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-43 — No fake or artificial test-count manipulation.

Severity: P1

- Previous defect: Original50-step test repeated unrelated assertions to inflate a counter.
- Relevant implementation files: tests/test_v3_3_postgres_failure_hunt.py; tests/test_v34_acceptance.py
- Required change: No fake or artificial test-count manipulation.
- Implementation status: INTEGRATION_TESTED
- Exact runtime call path: External data/AI boundary replay -> real PostgreSQL and internal runtime
- Test file: tests/test_v34_acceptance.py
- Test name: test_proof_c_full_autonomous_lifecycle_and_authenticated_api
- Actual execution result: Artificial50-step counter replaced by meaningful assertions. Current total reports collected test cases, not repeated assertion counts.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement

## AC-44 — No real-money trading API calls occur.

Severity: P1

- Previous defect: V1 version labels, development deployment credentials and unaudited capital projections.
- Relevant implementation files: config.py; accounting.py; docker-compose.yml
- Required change: No real-money trading API calls occur.
- Implementation status: END_TO_END_VERIFIED
- Exact runtime call path: Settings -> startup; PostgreSQL funding -> gateway hard policy
- Test file: tests/test_v34_acceptance.py
- Test name: test_proof_c_full_autonomous_lifecycle_and_authenticated_api
- Actual execution result: 80-test PostgreSQL regression passed; credential-free mock Compose deployment and browser passed.
- Database evidence: Isolated real PostgreSQL 16; independent sessions and actual interpreter process boundaries. Fill, target, cash, basis, P&L and reservation replay assertions; no SQLite concurrency fallback.
- Remaining blocker: None for this requirement
