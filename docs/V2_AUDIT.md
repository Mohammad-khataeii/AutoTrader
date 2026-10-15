# AutoTrader V2 Audit

Audit date: 2026-10-12

## Verified Baseline

Executed:

- `python3 -m ruff check .`
- `python3 -m pytest`
- `python3 -m mypy src/autotrader`
- `cd frontend && npm test`
- `cd frontend && npm run build`
- `cd frontend && npm audit --audit-level=moderate`

Results: backend lint passed, backend tests passed with 10 tests and one third-party Starlette/AnyIO deprecation warning, mypy passed, frontend Vitest passed with 1 test, frontend build passed with a bundle-size warning, and npm audit reported 0 vulnerabilities.

## Components That Work

- Configuration rejects `LIVE_TRADING_ENABLED=true`.
- Technical indicators calculate RSI, MACD, EMA, ATR, Bollinger Bands, VWAP, ADX, support/resistance, relative volume, momentum, volatility, breakout distance, and volume acceleration from ordered candle history.
- Strategy signals are structured and include evidence, conditions, invalidation, estimated costs, and explanations.
- The deterministic decision engine can combine strategy signals, mock AI output, portfolio state, and risk checks.
- The risk engine enforces the basic EUR 500 policy for cash reserve, position size, exposure, daily/weekly loss budget, and entry frequency.
- The in-memory paper broker simulates market and limit acceptance, partial fills, fees, slippage, cancellation, and duplicate fill idempotency at the `Portfolio` layer.
- The API serializes scanner output and exposes health, readiness, overview, scanner, and paper order endpoints.
- The dashboard renders against the API and clearly marks paper-only operation.

## Mocked Or Disconnected Components

- `src/autotrader/api/main.py` uses `_sample_candles()` instead of persisted or live market data.
- `src/autotrader/worker/runner.py` is a heartbeat loop only; it does not ingest data, scan markets, create decisions, reconcile orders, or monitor positions.
- `PaperBroker`, `Portfolio`, API orders, fills, and positions are in memory and disappear after process restart.
- SQLAlchemy models and Alembic migrations exist, but runtime code does not write authoritative financial state to PostgreSQL.
- Backtesting reuses some decision/risk logic, but it uses synthetic spreads and in-memory broker state.
- AI caching, retries, budget persistence, circuit breaking, selective invocation, and prompt-injection hardening are minimal.
- Dashboard pages show a functional shell, but most pages do not yet read durable operational data.

## Persistence Gaps

- Missing durable cash balances, capital reservations, positions, order transitions, portfolio snapshots, risk evaluations, strategy versions, backtest runs, and incidents in V1.
- Existing migrations cover core audit tables, but they do not support reconstructing portfolio state after restart.
- No transactional repository enforces idempotent order submission or fill application.
- No database constraints prevent negative balances or overselling.
- Redis is configured but unused for queues.

## Runtime And Recovery Gaps

- No event-driven schedules for ingestion, features, opportunities, AI, orders, positions, reconciliation, or evaluation.
- No single-writer lock or idempotency key enforcement around execution.
- No restart recovery path reconstructs the simulated portfolio from fills and balances.
- No delayed/stale data protection is wired into order submission.
- No order lifecycle transition table exists, so status changes are not auditable.

## Market Intelligence Gaps

- Indicators are single-timeframe; no multi-timeframe feature aggregation exists.
- Relative strength requires provided BTC/ETH features but runtime does not supply them.
- Swing structure, higher highs/lows, retests, resistance rejection, VWAP distance, market depth, and regime transitions are incomplete.
- Revolut X adapter is read-only and rate-limited, but it is not integrated into the worker.

## Strategy And Decision Gaps

- Current strategy class has eight research hypotheses but not the requested ten-strategy ensemble.
- Catalyst strategy is a placeholder.
- The ensemble does not resolve contradictory SELL/REDUCE/HOLD/WAIT recommendations.
- Trade construction is simple ATR-based sizing and target calculation; no expected reward/risk or liquidity-aware sizing is persisted.
- Outcome evaluation is absent.

## Backtesting Gaps

- Single-asset only.
- No walk-forward or out-of-sample validation.
- No parameter sensitivity, Monte Carlo, missed-opportunity analysis, or strategy/regime breakdown.
- No historical liquidity constraints beyond synthetic spread assumptions.

## Security And Deployment Gaps

- Development default `admin/change-me` exists and should be rejected for production.
- PostgreSQL, Redis, Prometheus, and Grafana are published or internally available without production access hardening.
- Docker Compose does not run migrations before API/worker startup.
- Containers do not yet include restricted users, resource limits, or explicit graceful shutdown behavior.

## V2 Priority

The highest-value first slice is durable financial state and recovery:

1. Add ledger-oriented tables for balances, reservations, positions, order transitions, risk evaluations, snapshots, and incidents.
2. Add a transactional repository and persistent paper runtime.
3. Persist decisions, risk, orders, transitions, fills, balances, positions, and snapshots in one connected workflow.
4. Add reconciliation that rebuilds a portfolio from durable fills and verifies invariants.
5. Add tests for duplicate submissions, duplicate fills, restart recovery, and the 20-step acceptance scenario using deterministic fixtures.

