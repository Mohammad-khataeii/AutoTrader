# AutoTrader V3.3 Independent Failure Hunt Tracker

Date: 2026-10-13

This tracker was created during the V3.3 failure hunt because the requested
`docs/V3_3_EXECUTION_TRACKER.md` file was not present at the start of review.

| Requirement | Test name / command | Actual result | Runtime proof | Remaining risk |
|---|---|---|---|---|
| TP1/TP2/TP3 fill attribution | `test_postgres_50_step_lifecycle_restart_replay_and_symbol_reuse` | Passed | Real PostgreSQL DB; sell fills are attributed by `fills.position_id`; TP sync only counts fills for the active position. | Advanced ambiguous candle ordering still needs strategy/backtest policy. |
| Position identity reuse across successive trades | `test_postgres_50_step_lifecycle_restart_replay_and_symbol_reuse` | Passed | Closed BTC-EUR position retained its `position_id`; second BTC-EUR trade created a new `position_id`. | Existing production data with ambiguous historical symbol-only fills is backfilled by symbol during migration. |
| Unrealized P&L calculation | `test_postgres_50_step_lifecycle_restart_replay_and_symbol_reuse` | Passed | `PersistentTradingRepository.unrealized_pnl()` marked the open restarted position at 75 and returned `-5`. | Not yet integrated into daily/weekly risk circuit breaker decisions. |
| Double-counted trading fees | `test_postgres_50_step_lifecycle_restart_replay_and_symbol_reuse`; `ledger()` independent replay | Passed | Independent replay of all PostgreSQL fills matched persisted cash exactly. | Fee currency is still assumed to be quote currency. |
| Negative cash under concurrency | `test_postgres_parallel_buy_reservations_cannot_make_negative_cash` | Passed | Ten concurrent BUY submissions on real PostgreSQL produced five fills, five rejects, zero available/reserved cash, and no invariant failures. | Isolation behavior verified on local PostgreSQL 15, not remote VPS PostgreSQL 16 container. |
| Oversold positions under concurrency | `test_postgres_stop_and_target_race_cannot_oversell` | Passed | Concurrent full-size stop and target sells produced one fill and one reject; final position quantity was zero. | No pending exit-order queue yet; immediate simulated market fills only. |
| Duplicate financial events after restart | `test_postgres_50_step_lifecycle_restart_replay_and_symbol_reuse` | Passed | Duplicate TP sell idempotency keys returned the same order and did not create extra fills after repository restart. | Worker process kill was simulated by repository reconstruction, not by OS process termination. |
| Pending reservations never released | `test_postgres_unfilled_buy_releases_pending_reservation` | Passed | Unfilled BUY became `REJECTED`, cash returned to available, reserved cash zero, no `OPEN` reservations. | Long-lived partially filled order policies remain simple immediate simulation. |
| Race between stop-loss and take-profit | `test_postgres_stop_and_target_race_cannot_oversell` | Passed | Real parallel transactions against same open position could not both sell the same quantity. | Strategy-level stop/target collision for historical candles still needs explicit conservative outcome policy. |
| AI spending after restart | `test_openai_budget_survives_provider_restart` | Passed | Fresh `OpenAIProvider` read persisted OpenAI assessment spend from DB and blocked before API call. | Pending concurrent AI budget reservations are not implemented. |
| Insecure VPS exposure | `docker compose config` with explicit secrets | Passed | Config requires `POSTGRES_PASSWORD`, `DASHBOARD_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`; published ports bind to `127.0.0.1`; placeholder env file is no longer injected into containers. | Full `docker compose up` blocked by unavailable Docker daemon in this environment. |
| PostgreSQL migrations existing-data safety | `alembic upgrade head` on temporary PostgreSQL DB | Passed | Full migration chain through `0005_v3_3_ledger` completed on real PostgreSQL. | Downgrade with multiple same-symbol positions would fail by design if reintroducing symbol uniqueness. |
| API integration | `pytest -q` | Passed | Includes FastAPI scanner/order endpoint tests. | No live browser-driven dashboard test in this pass. |
| Frontend build | `npm run build` in `frontend/` | Passed | TypeScript and Vite production build completed. | Bundle-size warning remains from Vite. |
| Docker deployment | `docker compose ps` with explicit secrets | Blocked | Docker CLI present, but daemon socket unavailable: `unix:///Users/mohammadkhataei/.docker/run/docker.sock`. | Requires starting Docker Desktop/daemon before deployment test can run. |

## Verification Commands

- `pytest -q`: 34 passed, 1 third-party deprecation warning.
- `ruff check . && mypy src/autotrader`: passed.
- `npm run build` in `frontend/`: passed.
- `POSTGRES_PASSWORD=test-postgres DASHBOARD_PASSWORD=test-dashboard GRAFANA_ADMIN_PASSWORD=test-grafana docker compose config`: passed.
- `alembic upgrade head` against a temporary local PostgreSQL database: passed.
- `POSTGRES_PASSWORD=test-postgres DASHBOARD_PASSWORD=test-dashboard GRAFANA_ADMIN_PASSWORD=test-grafana docker compose ps`: blocked by Docker daemon socket unavailable.
