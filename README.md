# Revolut X AutoTrader V4.1

Autonomous EUR 500 **paper trading** with public Revolut X data, PostgreSQL accounting,
FastAPI and a React dashboard. Existing bid/ask execution, partial targets, protective
exits, financial journal and server risk controls are retained. Live trading is
rejected; no exchange trading credentials are used. AI defaults to mock and enforces
persistent paid-mode limits of 30/day, 6/rolling hour and USD 10/calendar month.

**NO STRATEGY PASSED VALIDATION.** The genuine 5m/15m study rejected all six strategies.
Normal operation is RESEARCH_ONLY with cash held and new entries blocked. Software
tests do not establish a profitable strategy. Overall status is
PARTIALLY_COMPLETE_WITH_BLOCKERS; see the [full report](docs/V4_1_FINAL_REPORT.md).

## Start an isolated deployment

```sh
python3 scripts/generate_env.py --output .env
python3 deploy/vps.py inventory --project autotrader-v41 --env-file .env
python3 deploy/vps.py build --project autotrader-v41 --env-file .env
python3 deploy/vps.py up --project autotrader-v41 --env-file .env
python3 deploy/vps.py verify --project autotrader-v41 --env-file .env
```

The generator refuses overwrites and creates private credentials. Sign in using
your local `.env`. Default dashboard: http://127.0.0.1:3000; readiness:
http://127.0.0.1:8000/readyz. UI/API bind to loopback; database/cache ports stay
internal. Optional monitoring is stopped. Grafana is quarantined pending remediation.
Read [deployment](docs/V4_1_VPS_DEPLOYMENT.md) before operating on existing data or a
VPS. Actual testing used a separate local Docker project; no user's VPS was deployed.

Research needs verified history in `.data/research`. The [data report](docs/V4_1_INTRADAY_DATA.md)
records all 48 datasets, 351,788 observations, coverage and gaps. The
[backtests](docs/V4_1_FIVE_MINUTE_BACKTESTS.md) retain losing results and cost stress.
Use `deploy/vps.py sync-research` to publish matching-source research into the project
volume after verification. Approval is explicit and cannot override failed gates.

## Verify

```sh
python3 -m pip install -e '.[dev]'
# Set AUTOTRADER_TEST_PG_ADMIN_URL to a disposable PostgreSQL admin database.
python3 -m pytest -q -s
python3 -m ruff check src tests scripts alembic deploy
python3 -m mypy src/autotrader
npm ci --prefix frontend
npm run typecheck --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
```

PostgreSQL tests create separate databases and fail if PostgreSQL is missing;
they never substitute SQLite. Browser/deployment verification requires the explicitly
selected isolated project. Final native and installed-Linux regressions: **148 passed each**, including the
selected backported PostgreSQL16 image in the Linux run. See the
[executed evidence](docs/V4_1_TEST_EVIDENCE.md) for the exact scope and retained failures.

[Completion matrix](docs/V4_1_COMPLETION_MATRIX.md) ·
[Security disposition](docs/V4_1_SECURITY_REMEDIATION.md) ·
[AI quotas](docs/V4_1_AI_QUOTAS.md) ·
[Paper pilot](docs/V4_1_PAPER_PILOT.md) ·
[Limitations](docs/V4_1_KNOWN_LIMITATIONS.md) ·
[Continuation](docs/CONTINUE_FROM_HERE.md)

The prospective pilot capability is verified; 30 days have not elapsed. Earlier
V1–V4 documentation is retained as historical evidence, not current acceptance.
