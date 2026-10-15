# Revolut X AutoTrader V1.0 Architecture

This workspace did not contain the referenced V0.2 repository, so V1.0 was created as a new modular monolith.

The backend is organized around typed contracts in `autotrader.domain`. Market data adapters are read-only; execution is restricted to `PaperBroker`, which has no dependency on authenticated Revolut X order endpoints. The decision engine combines structured strategy signals, optional AI assessments, portfolio state, and the independent risk engine.

Important safety boundaries:

- `LIVE_TRADING_ENABLED=true` is rejected at configuration validation.
- The Revolut X adapter only implements documented public endpoints.
- AI providers return assessments only and cannot place or approve orders.
- Risk checks must pass before any paper order is accepted.
- Paper fills are marked `simulated=true`.

Current persistence includes migrations for the core audit trail tables: assets, pairs, candles, features, signals, AI assessments, decisions, orders, fills, and system events. Additional V1 tables such as news events, balances, reservations, positions, snapshots, backtest runs, and strategy versions should be added as the persistence layer is deepened.

