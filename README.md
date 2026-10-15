# Revolut X AutoTrader V3.4

Autonomous EUR 500 **paper trading** using public Revolut X market data,
PostgreSQL accounting, FastAPI and a React dashboard. The worker discovers
setups, applies deterministic risk controls, simulates orders and manages exits.
Live trading is rejected at startup. No exchange trading credentials are used.
AI defaults to mock; no paid API key is needed.

## Start

```sh
python scripts/generate_env.py --output .env
docker compose --profile monitoring up --build -d
docker compose ps
docker compose exec backend autotrader-reconcile
```

The generator creates private secrets and refuses overwrites. Sign in using the
credentials in your local `.env`. Dashboard: http://localhost:3000. API readiness:
http://localhost:8000/readyz. Services bind to loopback; database/cache ports are
internal. See [deployment](docs/V3_4_DEPLOYMENT.md) for VPS access and backup.

## Verify

```sh
python -m pip install -e '.[dev]'
# Set AUTOTRADER_TEST_PG_ADMIN_URL to a disposable PostgreSQL admin database.
python -m pytest -q -s
python -m ruff check src tests scripts alembic
python -m mypy src/autotrader
npm ci --prefix frontend
npm run typecheck --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
```

PostgreSQL tests create independent databases and fail if PostgreSQL is missing;
they never silently substitute SQLite. Browser/deployment verification requires
the explicitly selected isolated deployment described in the evidence.

## Engineering status

Read the [execution tracker](docs/V3_4_EXECUTION_TRACKER.md),
[executed evidence](docs/V3_4_TEST_EVIDENCE.md),
[known limitations](docs/V3_4_KNOWN_LIMITATIONS.md), and
[continuation checkpoint](docs/CONTINUE_FROM_HERE.md).
The short real-data replay lost money; no profitable edge has been established.
Earlier V1-V3 documentation is historical and does not establish V3.4 acceptance.
