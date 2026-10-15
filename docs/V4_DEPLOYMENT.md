# V4 deployment and verification

The tested isolated project retains the name `autotrader-v34-acceptance` and its
existing volumes. Runtime application version is4.0.0. API18000 and frontend13000
are loopback-only. PostgreSQL/Redis remain internal. No production user database
or existing volume was reset or deleted.

Executed Windows commands (private environment values are never printed):

```powershell
.\.venv\Scripts\python -m pip install --no-deps -e .
.\.venv\Scripts\autotrader research full --root .data/research --start 2020-01-01 --hourly-days 180 --intraday-days 2
docker compose -p autotrader-v34-acceptance --env-file .tools/v34-test.env build backend worker migrate research-worker frontend
docker compose -p autotrader-v34-acceptance --env-file .tools/v34-test.env --profile research up -d --no-build backend worker frontend research-worker
.\.venv\Scripts\python scripts/verify_deployment.py --env-file .tools/v34-test.env --project autotrader-v34-acceptance --restart
.\.venv\Scripts\python scripts/verify_restore.py --env-file .tools/v34-test.env --project autotrader-v34-acceptance
```

Deployment checks verify readiness, real PostgreSQL/Redis, authenticated API/metrics,
persisted controls, worker heartbeat, preserved journal IDs and reconciliation.
Restore checks use a new isolated database and compare financial counts, cash and
schema before independently replaying invariants. Evidence is in
`v4-deployment-verification.json` and `v4-backup-restore.json`.

The dedicated research worker uses a writable research bind mount and independent
process/resource limits. API/trading worker mounts are read-only. Jobs persist
claims/leases/results in PostgreSQL. A killed research job is recomputed after its
lease expires; it cannot mutate financial postings. On Linux, create the research
cache before Compose and ensure UID10001 can write its root and `runs` directory.

For a new Linux checkout, create a virtualenv, install `requirements.lock` and the
project, then run `autotrader research full` to create genuine local data; the cache
is not stored in Git. Generate a fresh environment with
`python scripts/generate_env.py --output .env`; it refuses to overwrite secrets.
Then use the same Compose commands with `.env`. Approval defaults empty and the
research gate requires a matching live5m timeframe, exact frozen parameters and
source fingerprint. With the current research result, no entry is approved.

Installed-runtime Linux test command:

```powershell
docker build -f Dockerfile.tests -t autotrader-v4-verification .
docker run --rm --network autotrader-v34-acceptance_data --env-file .tools/v34-test.env -e ENVIRONMENT=test -v C:/Users/moha/Downloads/AutoTrader:/verification autotrader-v4-verification python scripts/run_linux_tests.py --junitxml=docs/evidence/v4-release-linux.xml
```

Source checks use Ruff, strict mypy, TypeScript build, Vitest, Playwright, pip/npm
audit and image scans. Monitoring remains subject to the separate security report;
a successful build alone is not security clearance. Live trading is disabled.

The restart verifier restarts only already-running services, so stopped optional
monitoring stays stopped. Do not restart PostgreSQL while the Linux regression
container is using it. The patched Prometheus image is selected in Compose and was
temporarily verified against the actual authenticated backend; both optional
monitoring containers are stopped again while Grafana findings remain unresolved.

Patched Prometheus commands actually exercised (the final stop preserves the
disabled monitoring state):

```powershell
docker build -f Dockerfile.prometheus -t autotrader-v4-prometheus:3.15.0-patched .
docker scout cves --format sarif --only-severity critical,high --output docs/evidence/v4-prometheus-patched-cves.sarif autotrader-v4-prometheus:3.15.0-patched
docker compose -p autotrader-v34-acceptance --env-file .tools/v34-test.env --profile monitoring up -d --no-build --no-deps prometheus
docker exec autotrader-v34-acceptance-prometheus-1 /bin/promtool check config /etc/prometheus/prometheus.yml
.\.venv\Scripts\python scripts/verify_v4_prometheus.py
docker compose -p autotrader-v34-acceptance --env-file .tools/v34-test.env --profile monitoring stop prometheus grafana
```
