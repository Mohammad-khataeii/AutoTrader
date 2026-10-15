# V4 completion matrix

Allowed states: NOT_STARTED, IMPLEMENTED_UNVERIFIED, INTEGRATION_TESTED,
END_TO_END_VERIFIED, BLOCKED. Passing software tests does not establish trading edge.

| ID | Requirement | State | Runtime/files | Executed evidence | Limitation |
|---|---|---|---|---|---|
| BASE | Fresh unchanged baseline | END_TO_END_VERIFIED | V3.4 worker/repository/API | evidence/v4-baseline.xml: 80 passed | Isolated PostgreSQL |
| M1 | Executable bid stops and net target floors | INTEGRATION_TESTED | execution/pricing.py, position_manager.py, accounting.py | evidence/v4-execution.xml: 9 passed | No live orders |
| M2 | Shared finite depth and execution quality | INTEGRATION_TESTED | execution/pricing.py, accounting.py | evidence/v4-execution.xml: 9 passed | IOC model |
| M3 | V4 financial regression/restarts | NOT_STARTED | tests | Pending | Baseline precedes changes |
| M4 | Long horizon genuine dataset pipeline | INTEGRATION_TESTED | research/data.py, research/cli.py | v4-data-unit.xml: 9 passed; v4-datasets.json: 48 datasets, 76606 observations | Daily multi-year; other timeframes shorter, gaps retained |
| M5 | Point-in-time regimes | NOT_STARTED | Pending | None | V3 rules only |
| M6 | Versioned integrated strategies | NOT_STARTED | Pending | None | V3 strategies only |
| M7 | Frozen optimization/OOS/benchmarks | NOT_STARTED | Pending | None | No V4 performance result |
| M8 | Validated allocation/position policy | NOT_STARTED | Pending | None | V3 hard limits retained |
| M9 | Event-driven AI/comparison | NOT_STARTED | Pending | None | AI mock/off |
| M10 | Genuine execution/research UI | NOT_STARTED | Pending | None | Existing UI only |
| M11 | Security remediation/rate limits | NOT_STARTED | Pending | V3 scan only | Support image findings remain |
| M12 | V4 lifecycle/deployment gates | NOT_STARTED | Pending | None | Not V4 complete |
