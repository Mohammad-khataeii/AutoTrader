# AutoTrader V4.4 reliability and intelligence release

Stage A only. Branch `feature/autotrader-v44-engine-and-ux`, based on `738abcb24bb58e395cd1a6caa395deb21f4e01cb`. The release commit is the commit containing this report; the immutable release manifest records its full SHA. The existing `v4.2.0` tag remains untouched. Production has not been accessed, changed or deployed during this task. See the [approval-gated deployment and rollback plan](V4_4_DEPLOYMENT_AND_ROLLBACK.md).

## Findings and changes

**Frozen-source integrity was the release blocker.** V4.2 authorizes shadow BUYs using a hash of all Python source, including API code. An API-only change therefore invalidated otherwise unchanged accounts. V4.4 ships the original 71 Python files byte for byte under `_frozen/v42`, with the original `9f03f481049165cba9b54082d6f45f6e06e76d4b0a1625832b5f8434f8ace23a` fingerprint. A scoped importer redirects the original package imports into this verified namespace. It does not rewrite source, manifests, identities, funding or financial journals. Legacy execution uses original strategy, decision, risk, gateway, monitoring and repository implementations. Shared raw observations cross a typed boundary; frozen validation and indicator calculation run again. There is no second provider fetch per shadow account.

`shadow/versions.py` verifies every file against the sealed fingerprint and fails closed on tampering or an unknown implementation. `shadow/legacy.py` runs the old runtime and preserves original entry policy checks. Current repositories cannot authorize legacy BUYs by weakening their source check. New accounts retain full application provenance and additionally freeze a conservative execution closure; API/UI and observation-only changes do not change that closure. Execution changes do invalidate new accounts. This is compatibility for this release and the verified V4.2 implementation, not a promise that arbitrary future changes to shared acquisition or candidate selection are safe. Such changes require renewed compatibility tests.

**Momentum veto frequency did not establish a single cause.** The supplied production sample had a momentum veto in 65/78 observations for each active account, completed context in 78/78 and predominantly COMPRESSION. Those observations do not prove that removing D2 would qualify an entry. A2 independently requires bullish completed 15m/1h context, EMA9 recovery, recovering close and previous-high reclaim. B2 independently requires bullish context, a compressed pre-break range, prior breakout, retained range, no close reversal and breakout volume. Their frozen thresholds are unchanged. The new explanation records each observed condition separately, unknown inputs as null, actual primary-signal eligibility, concurrent momentum/regime vetoes, and only the risk/quality stages actually reached. Allocation advice may also be requested for a WAIT decision; it cannot overwrite the recorded strategy rejection. Calling the gateway for that WAIT returns before a quality check; this is not labeled a quality rejection. Allowed regimes come from the corresponding frozen strategy registry.

Explanations are additive `system_state` observations keyed by original decision ID. Original decisions/signals are not rewritten. Gateway observation preserves its original return value. Diagnostic write failures are logged and do not authorize or alter orders. `scripts/shadow_counterfactual.py` counts independently unmet conditions and single observed blockers offline; it cannot order, change parameters, rewrite outcomes or promote a strategy. [Recorded local examples](evidence/v4_4/decision-examples.json) and [offline analysis](evidence/v4_4/counterfactual.json) use explicitly synthetic flat replay, not production trading evidence. Old decisions without structured observations remain labeled as such.

**Large responses came from loading account histories for ordinary views.** Summary and detail/page APIs now separate workspace cards from histories; full legacy APIs and all five authenticated complete shadow exports remain available. The UI keeps Overview, Experiments, Trades and Research. It loads timelines, histories, linked trade records and historical research evidence on demand. Flat recorded equity has a compact unchanged-equity message. Stopped accounts occupy a small historical section. Explicit refresh reloads mounted resources, not every resource visited in the session.

**Official control and infrastructure health were conflated.** `/api/monitoring/summary` reports worker heartbeat, scan freshness, official control, official approval policy, shadow state/compatibility/latest evaluation, protection heartbeat, actual research job states, last scan, cached actual reconciliation and historical operator actions separately. Official STOPPED can coexist with a healthy worker and active shadows. Historical operator incidents retain original severity; they are separated from current runtime errors. A stopped or unavailable worker does not get a fabricated running label. Cached reconciliation exposes its check time and staleness; the explicit release preflight runs full reconciliation. Financial summary queries use a consistent PostgreSQL snapshot.

**Provider limits were already conservative.** Existing shared PostgreSQL family pacing, incremental completed-candle cache, protected-monitoring priority, bounded retries and long-outage deferral remain. The change rotates the same bounded market set across cycles, never enlarging it, and prevents a later cooldown from shortening an existing deadline. HTTP 429 observations now include family/symbol dimensions and identifiable 15-minute windows; old cumulative counters retain their original meaning. Revolut documents public rate limits and millisecond Retry-After values in its [official API reference](https://developer.revolut.com/docs/api/revolut-x-crypto-exchange). The user-supplied ETH-heavy log sample cannot establish a provider-side ETH defect or a sustained per-symbol rate. New measurements allow that hypothesis to be tested after an approved deployment. No production request reduction or live 429 improvement is claimed.

**Readiness was an SPA fallback.** Frontend Nginx now proxies exact `/readyz` to backend JSON with `Cache-Control: no-store`. The client rejects HTML, non-JSON and a missing boolean real-money flag. [Local Docker Nginx proof](evidence/v4_4/nginx-readiness.json) records valid JSON and real-money disabled.

**Pilot replay classification had an integration mismatch.** The test API previously classified a pilot differently from the worker when shadows were enabled. Both now explicitly use synthetic acceptance in the test environment, with replay provenance. This does not enable official strategy approval or real-money orders.

## User-approved experiment archival

The user explicitly approved archiving history and freeing a slot. Delete is available under a paused or stopped experiment's management menu, including stopped accounts reached through View history. Confirmation says “Archive and free slot.” Active accounts cannot be deleted. Accounts with open positions, unsettled orders, reserved open exits or failed reconciliation cannot be archived; protective monitoring remains available.

Deletion durably stops the flat account, marks its workspace membership archived and releases one of four workspace slots. The experiment database, frozen manifest, identity, all trades/orders/fills/journal/equity and complete exports remain. Archives stay accessible under Archived experiments and cannot resume. A replacement receives a fresh identity and independent original funding; an old identity or balance is never reused. Stopping alone still frees no slot. No production account was archived by this work.

The registry uses an additive `system_state` marker, not deletion of the original experiment record. If stopping succeeds but the official registry transaction fails, the account remains stopped and still occupies a slot until the idempotent operation succeeds. Capacity checks and registry mutations use the official account lock. Lifetime retained records may exceed four after explicit archival; unarchived workspace accounts cannot.

## API and database changes

No new Alembic revision, table, column or index is introduced; V4.2 schema remains current. Structured explanations, archive membership and identifiable metric windows use existing metadata storage. Financial writes, money precision, official approval, account isolation, reservations, journal idempotency and real-money prohibition remain guarded.

| Additive authenticated route | Contract |
|---|---|
| `/api/overview/summary` | Official aggregate account values |
| `/api/shadow/summary?archived=false` | Compact registry, balances, counts, version compatibility, latest explanation and actual reconciliation status |
| `/api/shadow/{id}/view` | One manifest, aggregate statistics and explicitly bounded recent records |
| `/api/shadow/{id}/pages/{kind}` | Decisions, signals, positions, orders, fills, journal, equity, incidents, exit intents, transitions; at most 100 per page |
| `/api/history/page/{kind}` | Official history using the same bounded keyset |
| `/api/trades` | Account-scoped/grouped position or order pages, at most 100 total |
| `/api/trades/{account}/{kind}/{id}` | One identified record and up to 100 linked records; complete shadow exports remain separate |
| `/api/intelligence/summary` and `/record/{id}` | Bounded feedback and explicit complete per-decision evidence |
| `/api/research/summary` | Hash-verified published verdicts, aggregate metrics, failed gates and publication errors |
| `/api/monitoring/summary` | Independent health and operating states |
| `/api/shadow/{id}/diagnostics` | Bounded, explicitly observational offline eligibility counts |
| `/api/release/compatibility` | Full read-only registry identity/runtime/reconciliation preflight; COMPATIBLE or BLOCKED |
| `DELETE /api/shadow/{id}?confirm={id}` | Explicit confirmed archive, preserved history, released workspace slot |

Financial and feedback keysets use insertion watermarks and timestamp/immutable-ID tie-breaking. Cursor scope includes account and kind (and position filter). New inserts do not appear midway through an existing page chain. Mutable positions/orders show their current committed state; this is not an MVCC snapshot across multiple HTTP requests. Trades cursors also freeze the account cohort/filter. The frontend exposes next/previous pages for position and order lists and earlier decisions/history. Original detail/history windows remain original contracts; complete exports are not silently truncated.

## Measurements

These are local engineering measurements. Production values below are the user's single bounded sample, not new remote measurements. Latency conditions are not comparable.

| Resource | Supplied production complete response | Local legacy → bounded response |
|---|---:|---:|
| Shadows | 3,074,748 B / 652 ms | Seeded four-account test: 3,690,502 → 5,349 B, about 99.85% smaller; 45 SQL queries, no historical-signal SELECT |
| Official history | 1,414,748 B / 199 ms | Dedicated local replay: 1,177,743 → 35,388 B |
| Intelligence | 1,559,183 B / 94 ms | Seeded 240-record fixture: legacy 200-row window 3,023,387 → 30-row summary 8,528 B. Dedicated replay had no feedback (188 → 275 B), so no reduction is claimed for that empty sample |
| Research | 1,345,702 B / 152 ms | Local historical publication: 537,534 → 19,389 B |

[Seeded response/query benchmark](evidence/v4_4/api-benchmark.json) includes elapsed time and provenance. [Real local endpoint measurements](evidence/v4_4/local-endpoint-measurements.json) include each elapsed time; the [seeded intelligence benchmark](evidence/v4_4/intelligence-benchmark.json) labels its artificial evidence volume explicitly. Summary test limits are 30 KB, 130 queries and 5 seconds on the seeded fixture; they are regression ceilings, not production SLOs. Further query optimization/indexing requires actual profiling; no speculative migration was added.

The [controlled 65-second browser comparison](evidence/v4_4/request-comparison.json) uses immutable V4.3 frontend code and V4.4 with identical mocked API data: both made 10 requests, no mutations. V4.3 made two broad history requests; V4.4 made zero. Polling cadence is preserved; the gain is bounded bytes, not an invented request-count reduction.

## Research publication audit and limits

The original local research store was read only. Both latest pointers and their summary SHA256s verify; all 48 datasets and 351,788 observations pass content/provenance validation. Their provider is Coinbase public historical data, including aggregated timeframes; historical L2 is unavailable. Both original and experimental reports retain **NO STRATEGY PASSED VALIDATION**, including negative out-of-sample outcomes. [Research audit](evidence/v4_4/research-audit.json) records original source fingerprints and pointer hashes. Historical source identity is preserved; it is not relabeled as matching the current application or promoted as an approved live strategy.

Production's missing experimental verdict remains **unverified**: this task prohibits SSH and production access. Existing deployment publication logic explicitly publishes the original pointer and catalog, not the experimental pointer; that is a concrete candidate publication-path gap, but it does not prove the remote mount/pointer state. Approved Stage B must inspect the actual research mount and both pointers, verify exact report/dataset hashes, and publish missing immutable artifacts/pointers only after review. Never overwrite a valid conflicting report or pointer, and never use the original-only sync command as proof that experimental research was published. The new summary surfaces publication errors instead of silently implying a verdict exists.

No frozen strategy threshold was relaxed. No new strategy hypothesis, profitability, prospective-market success or completed 30-day validation is claimed.

## Verification and artifacts

Final results: **201 backend tests, 12 frontend unit tests, 21 browser tests and two compiled-frontend financial lifecycle scenarios passed**. Ruff, mypy (76 source files), TypeScript typecheck, production frontend build and both local Docker builds passed.

Final machine-readable results are in [validation.json](evidence/v4_4/validation.json), [full backend JUnit](evidence/v4_4/backend-final.xml), [browser report](evidence/v4_4/playwright.json) and [financial frontend lifecycle JUnit](evidence/v4_4/frontend-financial-lifecycle.xml).

Coverage includes unchanged financial regressions; V4.1/V4.2 migration failure injection and rollback; isolated account locks; replay/partial fill/SIGKILL recovery; four original V4.2 accounts; verified legacy BUY and protective exits; API-only identity independence; genuine strategy/tamper rejection; no duplicate funding; complete exports; tied timestamps/new insertions/cross-account cursors; structured failures and unobserved stages; HTTP 429 recovery/outage/cancellation; stale-depth and cache guards; independent official STOPPED/healthy worker; invalid readiness; archival guards, idempotency, capacity and preserved history.

Both native and legacy compiled-dashboard lifecycle proofs display five persisted fills, one closed position, partial TP2 interrupted by SIGKILL, resumed protection, official €500 with no official orders/fills, and reconciliation `[]`. External observations are synthetic acceptance. See [legacy lifecycle](evidence/v4_4/legacy-frontend-lifecycle.json) and [native lifecycle](evidence/v4_4/native-frontend-lifecycle.json). The old V4.2 repository also reads additive V4.4 observations without financial restore or manifest rewrite; rollback constraints remain in the deployment plan.

Local Docker builds verify the installed wheel includes all 71 original sources and the manifest. These are local ARM64 builds, not production Linux AMD64 verification. The frontend build retains its pre-existing advisory about a JavaScript chunk above 500 KB. A non-fatal Starlette/AnyIO deprecation warning does not fail backend tests. The original frozen files retain their original extra EOF blank lines, so Git whitespace checks flag those copied lines; they are deliberately preserved to keep the exact verified bytes. Non-frozen changed files pass the whitespace check.

Manual viewport review and automated overflow checks cover 1440, 1024, 768 and 375 pixels with hidden default JSON. [Viewport report](evidence/v4_4/local-viewports.json) and same-backend before/after captures distinguish local synthetic accounts from production.

| Width | V4.3 Overview | V4.4 Overview | V4.4 Experiments |
|---|---|---|---|
| 1440 | [Before](evidence/v4_4/before-overview-1440.png) | [After](evidence/v4_4/after-overview-1440.png) | [After](evidence/v4_4/after-experiments-1440.png) |
| 1024 | [Before](evidence/v4_4/before-overview-1024.png) | [After](evidence/v4_4/after-overview-1024.png) | [After](evidence/v4_4/after-experiments-1024.png) |
| 768 | [Before](evidence/v4_4/before-overview-768.png) | [After](evidence/v4_4/after-overview-768.png) | [After](evidence/v4_4/after-experiments-768.png) |
| 375 | [Before](evidence/v4_4/before-overview-375.png) | [After](evidence/v4_4/after-overview-375.png) | [After](evidence/v4_4/after-experiments-375.png) |

## Changed source groups

- Version dispatch/import integrity: `src/autotrader/shadow/versions.py`, `legacy.py`, `runtime.py`, `repository.py`, original `_frozen/v42/**` and its hash manifest.
- Registry/archival: `shadow/lab.py`; read models and explanations: `shadow/views.py`, `diagnostics.py`, `api/v44.py`, additive registration in `api/main.py`; offline tool: `scripts/shadow_counterfactual.py`.
- Market scheduling/measurements: `market_data/service.py`, `revolut.py`, `persistence/market_state.py`; synthetic pilot provenance: `api/main.py`, `persistence/pilot.py`.
- Frontend shell/cache/pages: `main.tsx`, `api.tsx`, `model.ts`, `Overview.tsx`, `Experiments.tsx`, `Trades.tsx`, `Research.tsx`, `advanced.tsx`, `ui.tsx`, `styles.css`, new `DecisionTimeline.tsx` and `HistoryExplorer.tsx`; exact readiness proxy: `frontend/nginx.conf`.
- Release versions/package manifest: `pyproject.toml`, `src/autotrader/__init__.py`, frontend package files. Regression tests, browser fixtures, evidence, README and these reports accompany the change.

## Remaining release conditions

Local compatibility is proven for four source-pinned V4.2 fixture accounts with unchanged manifest hashes, not remotely asserted for production account IDs. Actual production backup/restore, source/manifest inventory, research-volume verification, Linux AMD64 build, compatibility checks against all four restored production financial domains and public post-deployment verification require separate approval. Any mismatch, failed backup, failed reconciliation, unknown runner or failed migration blocks Stage B. No SSH, production container restart, production database/configuration write, destructive cleanup or real exchange order was performed.
