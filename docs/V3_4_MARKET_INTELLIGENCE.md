# V3.4 market intelligence

Ordinary operation discovers active Revolut X EUR markets, validates precision/minimums, fetches closed candles and order books, validates freshness, calculates indicators and persists observations, features, signals and decisions. Candles have unique observation keys; market marks retain provider timestamps and provenance. Ranked allocation evaluates multiple candidates through the same independent gateway.

Four completed contiguous UTC-aligned primary bars form each higher-timeframe confirmation observation (5m ->20m). At least50 complete higher bars are required; missing confirmation vetoes entries. Future bars are excluded.

The ensemble executes volume accumulation, compression, completed-candle breakout/retest, momentum continuation, failed-breakout rejection and risk-off detection. It also evaluates benchmark relative strength and book liquidity. Zero-score/rejected evidence remains persisted with strategy version 3.4.0. Bearish evidence vetoes entries; it cannot open a short position. Resistance excludes the current candle.

The public adapter has only GET requests. Public endpoint paths and millisecond Retry-After handling were checked against the [official Revolut X API](https://developer.revolut.com/docs/api/revolut-x-crypto-exchange). It rate-limits each endpoint family, shares a PostgreSQL admission gate across API/worker processes, re-acquires the limit for every retry, and defers long server Retry-After intervals. Missing/invalid data cannot produce fixture prices in ordinary operation.

Executed public smoke: 379 markets, 61 EUR markets, BTC-EUR metadata/book/ticker parsing and 240 completed five-minute candles. An inclusive forming candle exposed by this smoke was explicitly excluded. Evidence: `docs/evidence/live-public-smoke.json`; repeat with `python scripts/smoke_public.py`.

Synthetic external replay is restricted to `ENVIRONMENT=test`. Strategy scores are evidence summaries, not calibrated probabilities or evidence of profitability.
