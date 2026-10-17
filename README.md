# Revolut X AutoTrader — V4.4

V4.4 preserves source-pinned V4.2 experiments through a verified legacy runner, adds structured decision explanations and bounded APIs, and keeps the four-page dashboard. Paused or stopped flat experiments can be archived to free a workspace slot while preserving all financial history. See the [release report and evidence](docs/V4_4_RELEASE_REPORT.md) and [approval-gated deployment/rollback plan](docs/V4_4_DEPLOYMENT_AND_ROLLBACK.md). This release is developed and verified locally; production deployment requires approval of its exact commit.

An autonomous EUR500 **paper-trading research platform** using public Revolut X observations, FastAPI, React and authoritative PostgreSQL accounting. The existing journal, realistic bid/ask execution, partial targets, protective stops, reservations and recovery remain intact. Real-money trading stays disabled. AI defaults to mock with persistent30/day,6/rolling-hour and USD10/month paid-mode limits.

**NO STRATEGY PASSED VALIDATION.** Official paper trading remains RESEARCH_ONLY. V4.2 adds independently funded, explicitly unvalidated EUR500 shadow experiments. Their equity and approval status never become official portfolio equity or approval. Engineering tests do not establish profitability.

Develop locally, test/build, commit, push, prepare an immutable release, then **wait for approval** before VPS deployment. [AGENTS.md](AGENTS.md) records this permanent workflow. The production server is a deployment target; its secrets and financial runtime state remain authoritative and stay on the server.

## Local development

Use a Python3.12+ virtual environment, Node/npm and Docker Desktop. Generate private local credentials without copying production `.env`:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock -e '.[dev]'
python scripts/generate_env.py --output .env.local
python deploy/vps.py build --project autotrader-v42-dev --env-file .env.local
python deploy/vps.py up --project autotrader-v42-dev --env-file .env.local
python deploy/vps.py verify --project autotrader-v42-dev --env-file .env.local
```

`.env.local` is ignored; `.env.example` contains placeholders. The generator refuses overwrites. Local default UI/API are loopback3000/8000; PostgreSQL/Redis stay private. Actual acceptance used the separate `autotrader-v42-acceptance` project on13042/18042. Grafana remains quarantined.

Genuine historical data must already be verified under `.data/research`. Existing immutable datasets/runs must not be overwritten. The original48datasets/351,788observations and original losing outcomes are retained. See [backtests](docs/V4_2_BACKTEST_RESULTS.md), [diagnostics](docs/V4_2_TRADE_FAILURE_ANALYSIS.md) and [limitations](docs/V4_2_KNOWN_LIMITATIONS.md).

## Verify locally

```sh
# Supply a private disposable LOCAL PostgreSQL admin URL; never production.
# Tests create separate prefixed databases and fail if PostgreSQL is unavailable.
python -m pytest tests -q -s
python -m ruff check src tests scripts alembic deploy
python -m mypy src/autotrader
npm ci --prefix frontend
npm run typecheck --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
# Real API/worker + built React synthetic lifecycle acceptance:
AUTOTRADER_BROWSER_ACCEPTANCE=1 python -m pytest tests/test_v42_lifecycle.py -q -s
```

The financial lifecycle uses real PostgreSQL/API/worker/broker components with deterministic external observations. A separate public-feed smoke verifies genuine market acquisition. [Local validation](docs/V4_2_LOCAL_VALIDATION.md) and [test evidence](docs/V4_2_TEST_EVIDENCE.md) distinguish final native, Docker, browser, earlier Ubuntu and actual deployment results. No completed30-day experiment is claimed.

## Release and deployment

```sh
# Only after tests, clean commits, push and immutable tag verification:
python deploy/release.py prepare --ref v4.4.0 --output .tools/releases/v4.4.0
```

The archive/manifest identify the exact Git commit and every released source hash, excluding secrets and runtime data. Production source operations require that manifest plus the approved full commit. **Stop after Stage A and obtain explicit approval.** Then follow the [V4.4 deployment and rollback plan](docs/V4_4_DEPLOYMENT_AND_ROLLBACK.md). Keep Compose project `autotrader-v41`; preserve Nginx/TLS, all financial volumes/backups and unrelated apps. ARM64 local tests do not replace verification of the LinuxAMD64 deployment build.

An earlier authorized rollout completed while the later local-first instruction arrived. Its actual state and remaining verification are recorded candidly in [executed upgrade](docs/V4_2_VPS_UPGRADE.md). It preceded the final Git release and must not be described as deployment of that final commit. Further deployment, data publication, shadow activation and cleanup are approval-gated.

[Release notes](docs/V4_2_RELEASE_NOTES.md) · [Completion matrix](docs/V4_2_COMPLETION_MATRIX.md) · [Security](docs/V4_2_SECURITY_EVIDENCE.md) · [Shadow financial integrity](docs/V4_2_SHADOW_FINANCIAL_INTEGRITY.md) · [Architecture](docs/V4_2_SHADOW_TRADING_ARCHITECTURE.md)

Earlier V1–V4.1 reports remain historical evidence. Thirty prospective days and a defensible net advantage require future observations under a frozen configuration; failed gates are never lowered to force trades.

V4.5 Stage A trade-gate investigation and deployment limitations: [report](docs/V4_5_TRADE_GATE_INVESTIGATION.md). Production deployment requires separate exact-release approval.
