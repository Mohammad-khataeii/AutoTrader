# V2 Deployment

Fresh local start:

```bash
docker compose up --build -d
```

Useful commands:

```bash
docker compose logs -f backend worker
docker compose down
alembic upgrade head
autotrader-reconcile
```

V2 migration behavior:

- Alembic reads `DATABASE_URL`.
- Async runtime URLs are converted for sync migrations:
  - `sqlite+aiosqlite://` to `sqlite://`
  - `postgresql+asyncpg://` to `postgresql+psycopg://`

Security note: default development credentials must not be used for public deployments.

