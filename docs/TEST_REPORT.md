# Test Report

Local verification completed on 2026-10-12.

Expected suites:

- Backend unit tests: `python3 -m pytest`
- Frontend smoke tests: `npm test`
- Frontend build: `npm run build`

Actual results:

- `python3 -m ruff check .`: passed
- `python3 -m pytest`: 10 passed, 1 third-party deprecation warning from Starlette/AnyIO
- `python3 -m mypy src/autotrader`: passed
- `cd frontend && npm test`: 1 passed
- `cd frontend && npm run build`: passed, with a bundle-size warning for the Recharts-heavy main chunk
- `cd frontend && npm audit --audit-level=moderate`: 0 vulnerabilities

Coverage focus:

- Indicator ordering and insufficient-history handling
- Hard capital constraints and cash reserve preservation
- Paper broker simulated fills and partial fills
- Duplicate fill idempotency
- AI cannot override risk limits
- Live trading configuration rejection
- Backtest report generation without fabricated profitability claims
