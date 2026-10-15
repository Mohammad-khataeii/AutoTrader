# V2 Test Report

Executed on 2026-10-12:

- `python3 -m ruff check .`: passed
- `python3 -m pytest`: 12 passed, 5 warnings
- `python3 -m mypy src/autotrader`: passed
- `cd frontend && npm test`: 1 passed
- `cd frontend && npm run build`: passed with a Vite bundle-size warning
- `cd frontend && npm audit --audit-level=moderate`: 0 vulnerabilities
- `DATABASE_URL="sqlite:///$tmpdb" alembic upgrade head`: passed
- `docker compose config`: passed
- `DATABASE_URL="sqlite+aiosqlite:///$tmpdb" autotrader-reconcile`: `reconciliation_ok`
- API smoke with temporary SQLite:
  - `/healthz`: 200
  - `/api/overview`: 200
  - `/api/paper/orders`: 200, simulated order `FILLED`
  - overview showed one persisted order and one persisted fill

New V2 tests:

- Persistent buy, restart-style repository reconstruction, sell, and reconciliation.
- Duplicate order submission idempotency.

Warnings:

- Starlette/AnyIO deprecation warning from test client.
- FastAPI `on_event` deprecation warning; lifespan migration is pending.

