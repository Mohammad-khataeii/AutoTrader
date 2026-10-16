# AutoTrader V4.3 interface redesign

V4.3 replaces eighteen primary tabs with **Overview, Experiments, Trades and Research**. This is a local frontend release based on V4.2 commit `4df605687aeb54d24f70e511f6d8e8dc5ff9dcec`, on branch `feature/autotrader-ui-simplification`. No SSH, production login, deployment, container restart, production configuration change or production account action was performed. The public production login was inspected without signing in. The authenticated acceptance environment is local.

## What changed

| Page | Default experience | Secondary capabilities |
|---|---|---|
| Overview | Four KPIs, recorded current activity, active experiment summaries, last-update times and one account-selected equity chart | Account history and explicit refresh; financial balances are never summed across accounts |
| Experiments | Compact cards with strategy, short instance ID, creation time, status, equity, P&L, closed trades and open positions | Account details, actual evaluation times, chart, positions, orders, partial fills, full statistics and technical disclosure |
| Trades | Open positions / Trade history with account filter | Position/order details, protective stops and targets, fees, fills, linked decisions and exit intents |
| Research | Historical strategy comparison, losses and validation status | Strategy rationale, failed gates, linked shadow instances and Advanced Research |

The permanent five-button control row, eighteen-tab navigation, raw manifests/JSON, repeated financial tables and five simultaneous export buttons have been removed from the default workspace. Financial errors, source mismatches and uncertainty remain visible. Advanced material is disclosed on demand rather than erased.

**Advanced** contains Official Account Controls, Market monitor, Decision journal, Execution diagnostics, AI & budgets, Risk & recovery, System & data health, Paper pilot and Settings. **Research → Advanced Research** contains Historical lab, Historical replay, Trade failure diagnostics, Opportunity outcomes and Paper pilot. The [workflow inventory](V4_3_WORKFLOW_MAP.md) maps every original workflow to its replacement.

Experiment creation requires review and explicit confirmation of permanent slot use. Four retained accounts, including stopped accounts, remove the create action. Repeated strategies retain distinct instance IDs and creation times. Active accounts show Pause, paused accounts Resume, stopped accounts neither. Permanent Stop lives under a secondary menu, warns that it cannot be resumed and does not free a slot, and requires confirmation. All five authenticated complete exports remain under Export. No reset or delete action exists.

Official controls expose only state-valid actions and require confirmation. Emergency Halt remains identifiable under Advanced → Official Account Controls. Research approval gates are unchanged. Paper pilot creation is explicit and confirmed. The UI never creates or changes an account on page load.

## Data loading and truthful presentation

`api.tsx` provides an in-memory cache scoped to the signed-in session, in-flight request deduplication, last-good-data retention, timestamped refresh warnings and cancellation on logout. Completion-based timers prevent overlapping requests; unmounted views stop timers and browser visibility suspends polling. No credentials or financial cache are persisted in browser storage.

The shell refreshes system health every 15 seconds. Overview refreshes the official account every 30 seconds. Its shadow snapshot and selected official history are cached for 60 seconds and disclose snapshot age. Experiments and Trades refresh the currently mounted account view every 20 seconds. Research summaries cache for five minutes; the lab polls only while an actual job is queued/running. Advanced resources load only when selected. Selecting a historical run uses its own cached summary and waits before loading that run's evidence, preventing an asynchronous selection race. Refreshes preserve selected filters, pagination and expanded sections within the mounted view.

No API contract or endpoint changed. `/readyz` now uses the same configurable Vite development proxy as `/api` and `/healthz`. The frontend package version is 4.3.0; the unchanged API remains V4.2.

The existing shadow registry endpoint returns full account details and history. Without an API change it cannot be reduced to a lightweight registry response. Shadow open-position marks lack a verifiable per-position observation age in this contract, so their current price/open P&L display **Unavailable**. Official marks require a consistent positive bid/ask, an in-range midpoint, no unavailable reason and no more than 90 seconds total age, including elapsed browser time since request start. Realized closed-position P&L remains visible. No historic signal price substitutes for a current mark.

Evaluation times come only from recorded decision creation times. Missing values are Unavailable. No trade, performance curve, creation time or acceptance success is invented for live accounts. Historical negatives remain red; unvalidated evidence is never promoted to a success badge. Streamed exports remain complete; recent detail/chart limits are disclosed separately.

## Verification

Final results are recorded in [validation.json](evidence/v4_3/validation.json), [Playwright report](evidence/v4_3/playwright.json) and [financial lifecycle](evidence/v4_3/frontend-lifecycle.json).

- TypeScript typecheck and production build passed; 9 unit tests passed across three files.
- All 16 browser tests passed without skips or retries. They cover real local authentication/logout, current balances/research-only status, original research artifacts, a completed PostgreSQL-backed research job, LIMIT replay, every official paper control through confirmation, mock-AI budgets, pilot evidence/CSV, shadow pause/resume, all five complete exports and trade-failure diagnostics. Fixtures additionally cover the exact four user-supplied IDs, three B2 instances, capacity, stopped accounts, confirmed permanent Stop, cancel/confirm creation, stale recovery, missing marks, cached navigation, polling and keyboard navigation at four widths.
- The unchanged existing financial lifecycle test passed against disposable local PostgreSQL with a real API, actual worker and the built React frontend. It generated five real persisted simulated fills, interrupted/restarted the worker during a partial second take-profit, closed the position, rendered both experiment and trade details, and verified official equity €500 with no official orders/fills and no reconciliation problems. Its external observations are explicitly `SYNTHETIC_ACCEPTANCE`; its positive test P&L is not investment evidence.
- Manually inspected screenshots at 1440, 1024, 768 and 375 pixels. Automated checks report zero horizontal page overflow. Raw JSON is hidden until requested. Local viewport checks are in [local-viewports.json](evidence/v4_3/local-viewports.json).
- The controlled browser request comparison uses the actual V4.2 and V4.3 frontends with the same mocked API and an accelerated 65-second clock. [request-comparison.json](evidence/v4_3/request-comparison.json) records observed counts and the reduction. This is a regression comparison, not production traffic or a latency benchmark; accelerated asynchronous scheduling can change counts between runs. No mutations occur in this comparison.

The browser runs caught and corrected a native-fetch receiver error, an uppercase pilot label, a missing development readiness proxy and a historical-run selection race. Test selectors were updated to the new semantic tabs and scoped confirmation dialogs. Final reports contain the successful rerun. Backend source was not modified, so the full backend suite was not rerun; the extra financial lifecycle test was run and passed.

Reproduce with a private **local-only** API environment, verified historical data and disposable PostgreSQL:

```sh
npm ci --prefix frontend
npm run typecheck --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
# Start V4.3 with the local API (leave V4.2 acceptance UI on 13042 for comparison).
cd frontend
AUTOTRADER_API_PROXY=http://127.0.0.1:18042 npm run dev -- --host 127.0.0.1 --port 13043
# In another terminal, from frontend; env file contains only local acceptance credentials:
AUTOTRADER_BROWSER_ENV=../.tools/v42-test.env npm run test:e2e
# From repository root, with a disposable local PostgreSQL admin URL in the environment:
AUTOTRADER_BROWSER_ACCEPTANCE=1 python3 -m pytest tests/test_v42_lifecycle.py -q -s
```

This repository's ignored local helper `.tools/with_pg.py` supplied the disposable PostgreSQL URL for the recorded run; no credential is committed. Real-API browser regressions explicitly exercise paper controls and create research/replay records in the local acceptance project. Never point these tests at production. The fixture tests alone can run with `npx playwright test v43.spec.ts` from `frontend`.

## Before / after evidence

These before/after images use the same real local API environment, with two retained A2 accounts. The observed old source mismatch is retained and visible. Recorded local emergency-control test incidents also remain visible. Runtime timestamps can differ between captures. They are not screenshots of authenticated production.

| Width | V4.2 Overview | V4.3 Overview | V4.3 Experiments |
|---|---|---|---|
| 1440 | [Before](evidence/v4_3/before-overview-1440.png) | [After](evidence/v4_3/after-overview-1440.png) | [After](evidence/v4_3/after-experiments-1440.png) |
| 1024 | [Before](evidence/v4_3/before-overview-1024.png) | [After](evidence/v4_3/after-overview-1024.png) | [After](evidence/v4_3/after-experiments-1024.png) |
| 768 | [Before](evidence/v4_3/before-overview-768.png) | [After](evidence/v4_3/after-overview-768.png) | [After](evidence/v4_3/after-experiments-768.png) |
| 375 | [Before](evidence/v4_3/before-overview-375.png) | [After](evidence/v4_3/after-overview-375.png) | [After](evidence/v4_3/after-experiments-375.png) |

[Old experiment workspace](evidence/v4_3/before-experiments-1440.png), [new experiment details with persisted fills](evidence/v4_3/shadow-lifecycle.png) and [new closed-trade details](evidence/v4_3/trade-lifecycle.png) show the secondary workflows.

Separate `acceptance-*.png` images exercise the four user-supplied production IDs using **synthetic acceptance states, dates and balances**. Those values were not read from production. [Four accounts on desktop](evidence/v4_3/acceptance-experiments-1440.png) and [mobile](evidence/v4_3/acceptance-experiments-375.png) prove duplicate identification, full capacity and state-valid controls without touching those production accounts.

## Changed files and boundaries

- Shell, authentication and navigation: `frontend/src/main.tsx`.
- Main pages: `Overview.tsx`, `Experiments.tsx`, `Trades.tsx`, `Research.tsx`.
- Shared cache, formatting and presentation: `api.tsx`, `model.ts`, `ui.tsx`, `styles.css`.
- Advanced workflows: `advanced.tsx`, `ResearchPanels.tsx`, `ShadowPanels.tsx`, `PilotPanel.tsx`.
- Unit coverage: `api.test.ts`, `model.test.ts`; the original `main.test.ts` is unchanged.
- Browser regressions and evidence: `frontend/e2e/dashboard.spec.ts`, `v42.spec.ts`, `lifecycle-proof.mjs`, `v43.spec.ts`, `fetch-budget.spec.ts`, `fixtures/v43.ts`, `frontend/playwright.config.ts`.
- Frontend release/development configuration: `frontend/package.json`, `package-lock.json`, `vite.config.ts`; no dependency added.
- Documentation: this report, workflow inventory, README release pointer and `docs/evidence/v4_3/`.

No backend Python, strategies, risk limits, workers, migration, database schema, ledger, Compose, Nginx or deployment code changed. The backend source fingerprint remains `9f03f481049165cba9b54082d6f45f6e06e76d4b0a1625832b5f8434f8ace23a`. The existing `v4.2.0` tag is preserved. Real-money trading remains disabled.

The production bundle currently has one approximately 592 kB JavaScript chunk (about 167 kB gzip); Vite reports its non-fatal chunk-size warning. No large UI framework or new runtime dependency was introduced. Authenticated production layout/state and an actual Linux production build were not verified in this local-only task. Deployment requires a separate explicit user authorization.
