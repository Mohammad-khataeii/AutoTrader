# AutoTrader V3.1 Initial Audit

Date: 2026-10-12

Scope: repository audit and continuation repair for the V3.1 paper-only Revolut X autonomous trading mandate.

## Verified External Contract

Source checked: https://developer.revolut.com/docs/api/revolut-x-crypto-exchange

- Public order book: `GET /api/2.0/public/order-book/{symbol}` with `data.bids`,
  `data.asks`, level `price` and `quantity`, and `metadata.timestamp`.
- Public candles: `GET /api/1.0/public/candles/{symbol}` with candle `start` in epoch
  milliseconds, plus `open`, `high`, `low`, `close`, and `volume`.
- Public pair configuration: `GET /api/1.0/public/configuration/pairs` with `base`,
  `quote`, `base_step`, `quote_step`, `min_order_size`, `max_order_size`,
  `min_order_size_quote`, and `status`.
- Public market-data endpoints document one request per second and `Retry-After` in
  milliseconds for 429 responses.

## Root Causes Found

- API and worker construction had drifted from `PaperExecutionGateway.__init__`, so tests
  failed during collection and runtime entry orders could not be created through the API
  path.
- The old Revolut client test still asserted deprecated/fallback fields
  (`tick_size`, `step_size`, `min_order_value`) that V3.1 explicitly disallows.
- The Revolut adapter parsed V2 order-book levels but did not reject empty or crossed books
  at the adapter boundary.
- Candle parsing used the documented `start` field, but sequence validation was incomplete:
  duplicates, missing intervals, out-of-order records, and forming candles could reach
  downstream strategy code.
- Region metadata was accepted but not compared to the configured operating region.
- `Retry-After` handling treated small numeric headers as seconds, despite Revolut X public
  docs documenting milliseconds.
- Portfolio reconstruction in scanner/runtime used the default `Portfolio` quote asset
  instead of the repository quote asset.

## Implemented Repairs

- Wired `risk_engine` and `initial_cash` into `PaperExecutionGateway` construction in the API,
  worker, and persistent runtime tests.
- Preserved repository quote currency when rebuilding runtime/scanner portfolio snapshots.
- Tightened V2 public order-book parsing to reject missing liquidity and locked/crossed books.
- Added region compatibility validation for order-book and candle responses.
- Added strict candle sequence validation for duplicate, out-of-order, missing-interval, and
  still-forming candles.
- Changed public API 429 `Retry-After` handling to milliseconds.
- Replaced stale Revolut client tests with documented contract fixtures covering:
  V2 order book, empty/invalid/crossed books, millisecond candle timestamps, candle gaps,
  pair configuration, disabled pairs, and `Retry-After`.

## Remaining V3.1 Work

- Persist currency explicitly on balances, orders, fills, fees, reservations, and snapshots;
  the current repository remains EUR-centric and rejects non-EUR execution through the
  gateway, but the database schema is not yet fully multi-currency typed.
- Add durable circuit breaker models for provider failures and risk lockouts.
- Extend risk accounting to include unrealized P/L, beginning-of-day/week equity,
  deposit/withdrawal adjustments, correlated exposure, and pending-order commitments beyond
  the current reservation model.
- Expand position persistence to the full V3.1 state machine with original quantity,
  remaining quantity, target execution state, trailing stops, and restart-safe partial exits.
- Add a dedicated position-monitoring worker test proving TP1 is not duplicated after restart.
- Add Docker/VPS startup verification that migrations run before API/worker startup.

## Regression Status

- `pytest -q`: 22 passed.
