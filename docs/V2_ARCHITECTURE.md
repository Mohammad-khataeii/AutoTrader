# V2 Architecture

V2 keeps the modular monolith shape and adds a durable paper-trading runtime.

Current connected path:

1. Candle fixtures or market data feed inputs
2. Indicator calculation
3. Strategy signal generation
4. Mock/OpenAI AI assessment interface
5. Decision engine
6. Risk engine
7. Persistent paper execution
8. Durable balances, positions, orders, fills, transitions, snapshots
9. Reconciliation command/API overview

Authoritative financial state is now PostgreSQL/SQLite via SQLAlchemy models, not `Portfolio` memory. The in-memory `Portfolio` and `PaperBroker` remain for unit tests and backtesting, while `PersistentTradingRepository` powers V2 runtime persistence.

Live trading remains disabled and unsupported.

