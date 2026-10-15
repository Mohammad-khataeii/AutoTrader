# V4 completion matrix

States: NOT_STARTED, IMPLEMENTED_UNVERIFIED, INTEGRATION_TESTED, END_TO_END_VERIFIED, BLOCKED. Software verification does not establish trading edge. Implementation paths are relative to src/autotrader. Evidence paths are relative to docs/evidence. Final suite counts are in V4_TEST_EVIDENCE.md.

| ID | Requirement | State | Implementation | Executed evidence | Limit |
|---|---|---|---|---|---|
| BASE | Preserve original baseline | END_TO_END_VERIFIED | Original repository/worker/API | v4-baseline.xml:80passed; SQLite hash unchanged | Isolated databases |
| M1 | Side-aware executable prices | END_TO_END_VERIFIED | execution/pricing.py, position_manager.py, persistence/accounting.py | v4-execution-current.xml:12passed; real lifecycle | Paper only |
| M2 | Finite depth and truthful costs | END_TO_END_VERIFIED | execution/pricing.py, quality.py | Shared depth, restart and partial fills | IOC model |
| M3 | Financial integrity | END_TO_END_VERIFIED | accounting.py, recovery.py, risk.py | Full native/installed-Linux suites and killed PIDs | User DB preserved |
| M4 | Genuine historical data | INTEGRATION_TESTED | research/data.py, cli.py | v4-datasets.json:48datasets/76606bar records | Daily multi-year; other TF shorter |
| M5 | Causal regimes | INTEGRATION_TESTED | research/regimes.py, panel.py | v4-causal-research.xml:8passed; source-matching study | Heuristic labels |
| M6 | Versioned integrated strategies | END_TO_END_VERIFIED | research/strategies.py, scanner.py, decision.py | v4-lifecycle.xml; six strategies in research | None validated |
| M7 | Frozen optimization and validation | INTEGRATION_TESTED | research/workflow.py, simulation.py | research-20261015T205023; JSON/CSV exports | Reused holdouts disclosed |
| M8 | Allocation and protection | END_TO_END_VERIFIED | allocation.py, protection.py, research_policy.py | Promotion checks and actual worker lifecycle | Approval defaults empty |
| M9 | Event-driven AI | INTEGRATION_TESTED | ai.py, persistence/ai_events.py | AI/cache tests; matched rules/mock comparison | Paid model unverified |
| M10 | Genuine dashboard | END_TO_END_VERIFIED | frontend/src/ResearchPanels.tsx, api/analytics.py | Browser15pages; completed real queued job and curves | Bundle warning |
| M11 | Security remediation | BLOCKED | api/security.py, Dockerfile.* | Auth11passed; app scans clear; patched Prometheus verified | PostgreSQL/Grafana findings remain |
| M12 | Full acceptance verification | BLOCKED | Docker, worker, API, research worker | Functional suites/browser/restart/restore verified | Depends on unresolved M11 security gate |

## Execution acceptance A-J

| ID | Contract | State | Implementation / evidence | Limit |
|---|---|---|---|---|
| A | Bid crosses stop while midpoint does not | INTEGRATION_TESTED | position_manager.py; v4-execution-current.xml | Executable fresh book required |
| B | Midpoint target cannot trigger without net bid proceeds | INTEGRATION_TESTED | pricing.target_gross_floor; target floor in accounting | No fictional fill |
| C | Wide spread rejects entry but permits protection | INTEGRATION_TESTED | quality.py; execution XML | Depth still finite |
| D | Insufficient depth supports only a partial fill | END_TO_END_VERIFIED | Account-locked book consumption; lifecycle XML | Remainder persists |
| E | Stop gap executes available bid levels | INTEGRATION_TESTED | pricing.py; execution XML | Stop price not guaranteed |
| F | TP/stop collision prioritizes protection | INTEGRATION_TESTED | position_manager.py, simulation.py; execution XML | Conservative OHLCV order |
| G | Restart preserves partial target and ledger | END_TO_END_VERIFIED | Actual killed-worker PIDs in full suite logs | Disposable PG databases |
| H | Costs destroy apparent advantage | END_TO_END_VERIFIED | Actual scanner rejects BTC on costs in lifecycle | Feasibility is not win probability |
| I | Stale book records durable wait and recovers | INTEGRATION_TESTED | protection_watch; execution XML | No stale-price liquidation |
| J | Repeated symbol positions keep identity | END_TO_END_VERIFIED | Original identity/reconciliation tests | Immutable audit preserved |

## Detailed contracts

| ID | Contract | State | Implementation / executed evidence | Limit |
|---|---|---|---|---|
| R01 | Hashes, UTC, provenance, gaps, suspicious bars | INTEGRATION_TESTED | research/data.py; data XML and48manifests | No invented gaps or FX conversion |
| R02 | Eight direct EUR assets and six TF | INTEGRATION_TESTED | v4-datasets.json; V4_HISTORICAL_DATA.md | Overlapping records not independent |
| R03 | Train-only finite grid frozen before holdouts | INTEGRATION_TESTED | workflow.py; frozen_parameters artifacts | Three predeclared choices |
| R04 | Purged splits and four walk-forward windows | INTEGRATION_TESTED | workflow.py; full study | Executed full study daily/4h |
| R05 | Cost stress, block bootstrap, search correction | INTEGRATION_TESTED | simulation.py/workflow.py; report gates | Approximate dependence |
| R06 | Cash/BTC/ETH/equal-weight/V3.4/ensemble | INTEGRATION_TESTED | V4_BACKTEST_RESULTS.md | Common execution; passive exposure differs |
| R07 | Curves, fills, MFE/MAE and residual positions | INTEGRATION_TESTED |623fills/4260curve rows exported | Historical depth assumptions |
| R08 | Reject weak or tiny-sample strategies | INTEGRATION_TESTED | No strategy passed validation | Valid research outcome |
| R09 | Exact source/live TF/frozen-parameter promotion | INTEGRATION_TESTED | research_policy.py; policy XML | Daily/4h cannot approve live5m |
| R10 | Quality only known after close; same legacy gate | INTEGRATION_TESTED | panel.py/simulation.py;8causal tests | Earlier studies diagnostic |
| S01 | EUR500; reserve150/exposure350/position100/max3 | END_TO_END_VERIFIED | Hard repository risk limits; full suite | No shorts/leverage/averaging |
| S02 | EUR5 planned loss/15day/35week/6entries | END_TO_END_VERIFIED | risk.py/accounting.py; equity480 halt proof | Durable risk halt |
| S03 | Three allocation profiles/correlation | INTEGRATION_TESTED | allocation.py; risk tests | No return superiority claim |
| S04 | ATR trailing/BE/expiry/failed-breakout/stress | INTEGRATION_TESTED | protection.py/position_manager.py; execution tests | Monotonic stops |
| S05 | Persistent USD10 AI cap/holds/unknown settlement | END_TO_END_VERIFIED | Original concurrent budget tests | Mock/off; no paid call |
| S06 | Qualified events/cache/schema validation | INTEGRATION_TESTED | ai.py/ai_events.py; AI/cache tests | Mock proves integration only |
| S07 | Mature missed-opportunity feedback | INTEGRATION_TESTED | analytics.py; v4-feedback.xml | Unobserved outcomes unavailable |
| U01 | Actual research jobs/leases/heartbeat/artifacts | END_TO_END_VERIFIED | research worker/API/browser | Crash recomputes job |
| U02 | Execution/research/intelligence/system pages | END_TO_END_VERIFIED | API/frontend; screenshots and Playwright | Explicit unavailable states |
| U03 | Authenticated API/metrics and failed-guess cooldown | INTEGRATION_TESTED | security.py; v4-auth-final.xml:11passed | Per-process throttle |
| D01 | Native Windows and installed Linux/real PG | END_TO_END_VERIFIED | Full suites; Dockerfile.tests | Test tools separate from runtime |
| D02 | Autonomous rejection/entry/TP1/partial TP2/restart/exit | END_TO_END_VERIFIED | v4-lifecycle.xml and full suites | Explicit isolated acceptance policy |
| D03 | Persistent Compose restart and isolated restore | END_TO_END_VERIFIED | v4-deployment-verification.json/v4-backup-restore.json | Volumes retained |
| D04 | Reproducible patched Prometheus | END_TO_END_VERIFIED | Dockerfile.prometheus; clear scan and functional JSON | Monitoring stopped for Grafana |
| D05 | Source secrets/GET-only exchange/loopback audit | INTEGRATION_TESTED | scripts/verify_security.py | Not penetration testing |

V4_SECURITY_REMEDIATION.md retains raw findings, exact image IDs, library/binary paths, scoped dispositions and remaining work. End-to-end application success does not clear the security gate.
