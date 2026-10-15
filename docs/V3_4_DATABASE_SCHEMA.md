# V3.4 database schema

Head: `0009_legacy_quarantine`. Migrations 0001–0004 are retained; 0005 no longer guesses fill attribution from symbols. Migration 0006 quarantines legacy attribution, including guesses already made by the previously deployed 0005. Migrations 0007–0008 add complete AI usage pricing fields and conservative holds for legacy paid usage.

| Table | Identity and responsibility |
|---|---|
| accounts | `account_id=paper-eur`, EUR funding policy and persisted controls |
| positions | Immutable lifecycle identity; current quantity, fee-inclusive remaining basis, realized P&L, stop/high-water/expiry projections |
| exit_plans | One durable plan per position; strategy and holding settings |
| exit_targets | Plan/position foreign keys, original price and quantity, linked-fill progress, reservations and status |
| exit_intents | Position/plan/optional target references; reason, stable key and reserved quantity |
| orders | Unique client intent key; account/position/intent/target references and durable simulation parameters |
| fills | Unique fill identity; account/position/intent/target foreign keys and confirmed attribution status |
| financial_journal | Unique event key; immutable signed cash, reservation, quantity, basis and P&L postings |
| equity_snapshots / risk_periods | Observed equity and persistent day/week baselines |
| market_candles / market_marks / market_features | Deduplicated observation keys, timestamps, prices, provenance and computed features |
| system_state / system_incidents | Durable controls, risk state, scanner snapshot, heartbeat and incidents |
| cooldowns | Persistent symbol/strategy identifier and expiry |
| ai_budgets / ai_usage | Locked monthly spend/holds and request-level usage, status and configured prices |
| legacy_attribution_report | Original fill ID, previous position guess and explicit unresolved reason |

Financial values use `Numeric(28,12)` and application Decimal arithmetic. Journal and fill UPDATE/DELETE operations are rejected by database triggers. Nullable identity columns exist solely to preserve unresolved legacy rows; new economic fills populate their full identity chain.

Populated upgrade and transactional DDL failure/retry tests are in `tests/test_v34_migrations.py`. The existing user database and volumes were not reset.
