# V3.4 deployment

From the repository root on a Linux VPS:

```sh
python scripts/generate_env.py --output .env
docker compose --profile monitoring up --build -d
docker compose ps
docker compose logs --tail=100 migrate backend worker
docker compose exec backend autotrader-reconcile
```

The generator refuses overwrites, creates independent random secrets, and does not print them. Protect the environment and metrics password file. The monitoring configuration uses the default admin username; update its username if changing DASHBOARD_USERNAME.

PostgreSQL and Redis have no published ports and use an internal data network. API, frontend, Prometheus and Grafana bind to loopback. Use an authenticated TLS reverse proxy or SSH forwarding when exposing the dashboard intentionally. API administration and metrics require authentication. Application containers run with resource limits; backend/worker use a non-root user, read-only root filesystem and dropped capabilities.

Alembic is the schema authority. A successful migration service gates the API; API readiness gates the worker. Worker health checks heartbeat and reconciliation. A separate protective task continues during scanner work. PostgreSQL, Redis and Grafana use named volumes; no deployment script deletes them.

Executable deployment/restart verification:

```sh
python scripts/verify_deployment.py --env-file .env --project YOUR_COMPOSE_PROJECT --restart
```

For backup, run `docker compose exec -T postgres pg_dump -U autotrader -Fc autotrader > backup.dump` from a shell preserving binary output. Restore into a separate empty database first with `pg_restore --no-owner`; compare financial journal/fill counts and run reconciliation before an intentional cutover. Never use `down -v` as an upgrade or recovery procedure.

Executed restore verification uses `python scripts/verify_restore.py --env-file .env --project YOUR_COMPOSE_PROJECT`. It stops only that project's worker, captures a binary pg_dump, creates a separately named restore database, compares counts/cash/schema and runs independent financial replay, then restarts the worker in a finally block. Dumps remain private under `.tools`; no databases or volumes are deleted. Evidence:51 journal events,19 fills,6 positions restored at schema0009 with zero reconciliation issues.

Final application runtime uses upgraded Python3.12 Alpine and Nginx Alpine images. PostgreSQL16 uses upgraded packages and the C su-exec privilege helper; Redis/Grafana receive package upgrades. The optional monitoring profile was exercised, then its containers were stopped pending unresolved image security findings. Default paper services remain running in the isolated acceptance project; volumes were retained. Do not treat a functional monitoring health check as security clearance.
