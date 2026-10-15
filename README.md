# Revolut X AutoTrader V1.0

Autonomous cryptocurrency research and paper-trading platform for Revolut X markets.

This milestone is deliberately paper-only:

- live trading configuration is rejected at startup
- Revolut X integration is read-only market data
- order execution is simulated by `PaperBroker`
- AI assessments cannot bypass deterministic risk controls

## Quick Start

```bash
docker compose up --build
```

Dashboard: http://localhost:3000

API health: http://localhost:8000/healthz

Default dashboard/API basic auth: `admin` / `change-me`.

## Local Verification

```bash
python3 -m pip install -e ".[dev]"
python3 -m ruff check .
python3 -m pytest
python3 -m mypy src/autotrader
cd frontend
npm install
npm test
npm run build
npm audit --audit-level=moderate
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Operations](docs/OPERATIONS.md)
- [Test Report](docs/TEST_REPORT.md)

## Current Limitations

The requested V0.2 repository was not present in this workspace, so this is a new implementation rather than a refactor. Persistence is scaffolded with migrations for core audit tables, while full repository-backed runtime state and production-grade worker reconciliation remain the next major hardening step.

