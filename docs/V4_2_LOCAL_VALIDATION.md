# V4.2 Stage A local validation

Final package source `9f03f481049165cba9b54082d6f45f6e06e76d4b0a1625832b5f8434f8ace23a`; version 4.2.0. Repository `/Users/mohammadkhataei/Desktop/AutoTrader`, branch `feature/autotrader-v4.2`, existing GitHub origin retained. Release commit/tag and archive checksum are emitted after final documentation is committed; resolve the immutable `v4.2.0` tag and matching release manifest rather than a floating branch HEAD.

| Check | Actual result | Evidence |
|---|---|---|
| Full native backend/PG/API/research/worker suite |183passed,0 failed/errors/skipped,488.42s |evidence/v4_2-stage-a-regression.xml |
| Ruff |All checks passed |Executed `python3 -m ruff check src tests scripts alembic deploy` |
| Strict mypy |No issues in71 source files |Executed `python3 -m mypy src/autotrader` |
| Frontend typecheck/build |Passed |`npm run typecheck --prefix frontend`; `npm run build --prefix frontend` |
| Component test |1passed |`npm test --prefix frontend` |
| Existing+new browser flows |2passed,0 failed/skipped,57.7s |evidence/v4_2-stage-a-playwright.json |
| Real worker/API lifecycle plus React |1passed,24.40s;5 fills,1 closedposition |evidence/v4_2-frontend-lifecycle.xml/json; shadow-lifecycle-v4_2.png |
| Original backtests |All12exact across every fill/curve field |evidence/v4_2-original-reproduction.json |
| Original diagnostics |833 positions/2,204 fills, all included;177cost sign crossings |evidence/v4_2-diagnostics-summary.json |
| Genuine public data smoke |6 GOODobservations,10 successful requests,1 actual429handled,0 orders |evidence/v4_2-stage-a-public-market-smoke.json |
| Local Docker build/runtime |LinuxARM64,source hash matches,UID10001,metadata readable/unwritable |evidence/v4_2-stage-a-docker-runtime.json |
| Final local image scan |0high/critical |evidence/v4_2-stage-a-image-binding.json; SARIF |
| Locked Python/npm dependency audits |No known vulnerabilities/zero npm findings |evidence/v4_2-stage-a-pip-audit.json; v4_2-stage-a-npm-audit.json |
| Fresh local Compose |4.2ready,allhealthy,EUR 500,noorders,reconciled |evidence/v4_2-stage-a-fresh-install.json |
| Populated local Compose |Verified fresh backup/full restore,EUR 500 preserved |evidence/v4_2-stage-a-populated-install.json |
| Funding continuity |OneINITIAL_FUNDING,oneaccount,zeroorders/fills |evidence/v4_2-stage-a-funding-continuity.json |
| Release verifier |5 tests pass; dirty/tampered/unsafe/wrong-ref rejected |tests/test_v42_release.py; included in183 |

The lifecycle uses actual causal A2 indicators and real DecisionEngine, allocation, risk, broker, PostgreSQL journal and worker processes. Worker15676→15685 recovered a partialTP2 after SIGKILL. React read the real API and displayed all 5 persisted fills and the closed position, netEUR 0.273417762120 and feesEUR 0.149796346379, while officialEUR 500 had no orders. This positive **synthetic acceptance** P&L is a deterministic fixture outcome and provides no profitability evidence. All financial domains reconciled. Browser errors were empty.

The official browser pilot test preserves an interrupted older-source pilot and starts a new active pilot; no history is reset. Its research job changes the local latest-original report pointer to its completed1hjob. The pre-test5mreport pointer was restored as an explicit test precondition. Source changes correctly invalidate frozen experiments/pilots instead of mixing results.

The full-suite Stage A rerun before static corrections was intentionally interrupted after43passes and is not counted as a final pass. A lifecycle harness attempt used an invalid relative Playwright request URL and was corrected locally. Final results above are completed runs. The retained earlier178testUbuntuAMD64 suite and dual-architecture scans apply to source 072, not final source 9f03. No new remote build/test/deployment was performed after the local-first instruction. The final target-native AMD64 build and final Git release deployment belong to approved Stage B; source distribution remains platform-independent.

Reproduce using the commands in README.md and V4_2_TEST_EVIDENCE.md, with a private local AUTOTRADER_TEST_PG_ADMIN_URL and isolated Compose environment. All required backend tests fail rather than silently skip if PostgreSQL is unavailable. One Starlette/AnyIO deprecation warning remains; no test was skipped because of it.

All12 original outcomes reproduce exactly under the final source. The final bounded experimental study research-20261016T114522 reproduced all five earlier negative/zero outcomes exactly and reports NO STRATEGY PASSED VALIDATION. It is reported independently in V4_2_BACKTEST_RESULTS.md; no hypothesis, parameter grid, execution cost or promotion threshold was changed after inspecting negative results.

Stage A stops after commit/push/tag/archive verification. Production state from the earlier in-flight rollout is documented in V4_2_VPS_UPGRADE.md; it is not deployment of this final release. Explicit approval is required for any further production source transfer, mutation, experiment activation, publication or cleanup.
