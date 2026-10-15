# V4 completion matrix

Allowed states: NOT_STARTED, IMPLEMENTED_UNVERIFIED, INTEGRATION_TESTED,
END_TO_END_VERIFIED, BLOCKED. Passing software tests does not establish trading edge.

| ID | Requirement | State | Runtime/files | Executed evidence | Limitation |
|---|---|---|---|---|---|
| BASE | Fresh unchanged baseline | END_TO_END_VERIFIED | V3.4 worker/repository/API | evidence/v4-baseline.xml: 80 passed | Isolated PostgreSQL |
| M1 | Executable bid stops and net target floors | INTEGRATION_TESTED | execution/pricing.py, position_manager.py, accounting.py | evidence/v4-execution.xml: 9 passed | No live orders |
| M2 | Shared finite depth and execution quality | INTEGRATION_TESTED | execution/pricing.py, accounting.py | evidence/v4-execution.xml: 9 passed | IOC model |
| M3 | V4 financial regression/restarts | END_TO_END_VERIFIED | full original suite plus execution/data tests | evidence/v4-financial-regression.xml: 98 passed in455.16s | Isolated PostgreSQL; subsequent strategy integration needs rerun |
| M4 | Long horizon genuine dataset pipeline | INTEGRATION_TESTED | research/data.py, research/cli.py | v4-data-unit.xml: 9 passed; v4-datasets.json: 48 datasets, 76606 observations | Daily multi-year; other timeframes shorter, gaps retained |
| M5 | Point-in-time regimes | INTEGRATION_TESTED | research/regimes.py, panel.py, indicators.py | v4-regimes-strategies.xml and causal-prefix checks | Heuristic states, not truth labels |
| M6 | Versioned integrated strategies | END_TO_END_VERIFIED | research/strategies.py, scanner.py, decision.py | v4-lifecycle.xml: real scanner and worker | No candidate validated |
| M7 | Frozen optimization/OOS/benchmarks | INTEGRATION_TESTED | research/workflow.py, simulation.py | full genuine daily/4h studies, final portable-source rerun pending | No predictive edge; historical test reused during engineering |
| M8 | Validated allocation/position policy | END_TO_END_VERIFIED | allocation.py, research_policy.py, execution/protection.py | v4-promotion-policy.xml and v4-lifecycle.xml | Production holds cash until approval and validation |
| M9 | Event-driven AI/comparison | INTEGRATION_TESTED | ai.py, ai_events.py | v4-ai-security.xml: 9 passed; matched mock study | Paid Sol account access not tested |
| M10 | Genuine execution/research UI | IMPLEMENTED_UNVERIFIED | ResearchPanels.tsx, API, research worker | TypeScript build and API tests pass; browser/queued-job proof in progress | Windows/Linux report pointer fixed, retest pending |
| M11 | Security remediation/rate limits | BLOCKED | api/security.py, Docker images | Auth test passes; support images rescanned | Support image findings require disposition/remediation |
| M12 | V4 lifecycle/deployment gates | IMPLEMENTED_UNVERIFIED | worker/API/Docker/frontend | v4-lifecycle.xml passes; full Linux/browser/restore gates pending | Not release complete yet |
