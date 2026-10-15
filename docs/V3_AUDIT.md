# AutoTrader V3.0 Source Audit

Date: 2026-10-12

Scope: full repository audit before V3 implementation. Trading remains paper only.

## Executive Findings

The V2 codebase has a durable portfolio/order ledger and a reusable strategy, AI, decision, and risk path, but normal runtime still mixes that path with synthetic observations and an order endpoint that bypasses market discovery. The critical V3 gap is not persistence; it is the connection between real Revolut X observations, multi-asset scanning, risk-controlled paper execution, and continuous position management.

## Verified Critical Deficiencies

1. `src/autotrader/worker/runner.py` uses `_sample_candles()` in the continuous loop. Status: Incorrect.
2. `src/autotrader/worker/runner.py` uses `_sample_order_book()` in the continuous loop. Status: Incorrect.
3. The worker is hard-coded to `TradingPair("BTC-EUR", "BTC", "EUR")`. Status: Incorrect.
4. Worker position monitoring exits on fixed midprice thresholds `103` and `97`. Status: Incorrect.
5. `/api/scanner` in `src/autotrader/api/main.py` generates synthetic candles. Status: Mock-only.
6. `/api/paper/orders` creates a fixed BTC-EUR market buy directly through the repository. Status: Incorrect.
7. Multi-asset autonomous scanning is not connected to runtime. Status: Missing.
8. AI is connected inside `PaperTradingRuntime.run_market_cycle()` and `/api/scanner`, but the worker feeds it synthetic single-asset data. Status: Partially operational.
9. Positions store optional stop and targets, but the runtime does not persist or execute multi-stage TP/SL plans. Status: Partially operational.
10. The dashboard displays portfolio state, but scanner charts and opportunity rows are fed by synthetic API output and generated chart data. Status: Partially operational.

## Subsystem Classification

| Subsystem | Status | Evidence |
| --- | --- | --- |
| Configuration and paper-only guard | Operational | `Settings.reject_live_trading()` rejects live trading and defaults to `live_trading_enabled=False`. |
| Revolut X public adapter | Partially operational | Has public pair, ticker, order-book, and candle methods. Needs stricter normalization, validation, freshness handling, and runtime use. |
| Market data validation | Missing | No central checks for stale books, crossed books, duplicate candles, bad intervals, invalid prices, or provider latency. |
| Multi-asset scanner | Missing | No service discovers and ranks supported markets continuously. |
| Indicators | Operational | Deterministic indicator calculation exists and handles insufficient history via `DataQuality`. |
| Strategy engine | Partially operational | Generates deterministic signals, but only receives synthetic/single-market data in normal runtime. |
| AI provider integration | Partially operational | Mock/OpenAI provider path exists. It is not consistently fed real continuous scanner candidates. |
| Decision engine | Partially operational | Enforces deterministic decision and risk checks, but can be bypassed by `/api/paper/orders`. |
| Risk engine | Operational | Independent paper-entry risk checks exist. |
| Paper execution ledger | Partially operational | Durable orders, fills, balances, reservations, snapshots, and idempotency exist; direct repository access needs a gateway. |
| Position manager | Missing | Fixed threshold worker code is not a stateful TP/SL manager. |
| API | Partially operational | Health, readiness, metrics, overview are real; scanner/order endpoints are not V3 compliant. |
| Worker | Incorrect | Uses fixtures, hard-coded pair, and fixed exits. |
| Dashboard | Partially operational | Reads API state but does not surface real scan coverage, provider failures, candidate ranking, or position plans. |
| Backtesting | Operational | Offline broker/backtest path is intentionally fixture-compatible and separate from normal runtime. |
| Tests | Partially operational | Good V2 coverage; needs V3 tests for real-data gating, scanner unavailable states, and guarded execution. |

## Revolut X Documentation Notes

The current official Revolut X REST documentation identifies `https://revx.revolut.com/api/` as the base URL, public unauthenticated endpoints under `/public/`, and authenticated account/trading endpoints requiring API key, timestamp, and signature headers. Public market data includes pair configuration, tickers, OHLCV candles, trades, and v2 public order-book snapshots. The implementation must use public endpoints for read-only market observations and must not call authenticated trading endpoints because this project is paper only.

## V3 Implementation Direction

- Remove synthetic candles/order books from API and worker normal runtime.
- Introduce a real market-data service that validates Revolut X public observations.
- Add a multi-asset scanner that discovers supported EUR/USD pairs and ranks real candidates.
- Centralize all paper order submission in a risk-controlled execution gateway.
- Add a position manager that reads persisted stops/targets and executes paper exits with fresh order books.
- Update the dashboard payload so it exposes scan coverage, rejected markets, provider errors, and real candidates.
