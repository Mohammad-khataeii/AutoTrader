# V2 Trading Engine

Implemented in this slice:

- `PaperTradingRuntime` connects features, signals, AI, decision, risk, and persistent execution.
- `PersistentTradingRepository.submit_order()` performs idempotent simulated order submission.
- Orders write lifecycle transitions.
- Fills update balances and positions transactionally.
- Portfolio snapshots are recorded after fills.
- Duplicate order submissions with the same idempotency key return the original order.
- Worker initializes durable state and runs a cautious paper scan/reconciliation loop.

Remaining:

- Real Revolut X feed scheduling in the worker.
- Redis queue orchestration.
- Distributed locking for multi-worker deployment.
- Full autonomous target/stop state machine.

